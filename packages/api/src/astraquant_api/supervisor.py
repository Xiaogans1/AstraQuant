from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing import get_context
from multiprocessing.process import BaseProcess
from queue import Empty
from threading import Event, Lock, Thread
from typing import Any

from astraquant_api.repository import TaskRepository
from astraquant_api.task_model import (
    TERMINAL_TASK_STATUSES,
    TaskRecord,
    TaskStatus,
    transition_task,
)
from astraquant_api.worker import (
    DEFAULT_DEMO_STEP_DELAY,
    WorkerMessage,
    WorkerMessageKind,
    run_demo_worker,
)

WorkerTarget = Callable[..., None]


@dataclass(slots=True)
class _Job:
    process: BaseProcess
    queue: Any
    cancel: Any


class TaskSupervisor:
    def __init__(
        self,
        repository: TaskRepository,
        *,
        step_delay: float = DEFAULT_DEMO_STEP_DELAY,
        worker_target: WorkerTarget = run_demo_worker,
    ) -> None:
        self._repository = repository
        self._step_delay = step_delay
        self._worker_target = worker_target
        self._context = get_context("spawn")
        self._jobs: dict[str, _Job] = {}
        self._lock = Lock()
        self._stop = Event()
        self._monitor = Thread(
            target=self._monitor_jobs,
            name="astraquant-worker-monitor",
            daemon=True,
        )
        self._monitor.start()

    def start_demo(self, task: TaskRecord) -> TaskRecord:
        return self.start(task, self._worker_target, (self._step_delay,))

    def start(
        self,
        task: TaskRecord,
        worker_target: WorkerTarget,
        worker_args: tuple[object, ...],
    ) -> TaskRecord:
        if task.status is not TaskStatus.PENDING:
            raise ValueError("only pending tasks can be started")

        queue = self._context.Queue()
        cancel = self._context.Event()
        process = self._context.Process(
            target=worker_target,
            args=(task.task_id, queue, cancel, *worker_args),
        )
        process.start()
        running = task.evolve(
            status=transition_task(task.status, TaskStatus.RUNNING),
            current_step="started",
            worker_pid=process.pid,
            started_at=datetime.now(UTC),
        )
        if not self._repository.update(
            running,
            expected_revision=task.revision,
            event_type="task.started",
        ):
            process.terminate()
            process.join(timeout=1)
            queue.close()
            raise RuntimeError("task changed before worker startup completed")
        with self._lock:
            self._jobs[task.task_id] = _Job(process, queue, cancel)
        return running

    def cancel(self, task_id: str) -> TaskRecord:
        task = self._repository.get(task_id)
        if task is None:
            raise KeyError(task_id)
        if task.status in TERMINAL_TASK_STATUSES:
            return task
        if task.status is TaskStatus.PENDING:
            canceled = task.evolve(
                status=transition_task(task.status, TaskStatus.CANCELED),
                current_step="canceled",
                finished_at=datetime.now(UTC),
            )
            self._repository.update(
                canceled,
                expected_revision=task.revision,
                event_type="task.canceled",
            )
            return canceled
        if task.status is TaskStatus.RUNNING:
            requested = task.evolve(
                status=transition_task(
                    task.status,
                    TaskStatus.CANCEL_REQUESTED,
                ),
                current_step="cancel_requested",
            )
            if self._repository.update(
                requested,
                expected_revision=task.revision,
                event_type="task.cancel_requested",
            ):
                task = requested
            else:
                current = self._repository.get(task_id)
                if current is None:
                    raise KeyError(task_id)
                task = current
        with self._lock:
            job = self._jobs.get(task_id)
            if job is not None:
                job.cancel.set()
        return task

    def active_count(self) -> int:
        with self._lock:
            return len(self._jobs)

    def shutdown(self, timeout_seconds: float) -> None:
        with self._lock:
            task_ids = list(self._jobs)
        for task_id in task_ids:
            self.cancel(task_id)

        deadline = time.monotonic() + timeout_seconds
        while self.active_count() and time.monotonic() < deadline:
            time.sleep(0.01)

        with self._lock:
            remaining = list(self._jobs.items())
        for task_id, job in remaining:
            if job.process.is_alive():
                job.process.terminate()
            job.process.join(timeout=1)
            task = self._repository.get(task_id)
            if task is not None and task.status not in TERMINAL_TASK_STATUSES:
                interrupted = task.evolve(
                    status=transition_task(task.status, TaskStatus.INTERRUPTED),
                    current_step="interrupted",
                    finished_at=datetime.now(UTC),
                )
                self._repository.update(
                    interrupted,
                    expected_revision=task.revision,
                    event_type="task.interrupted",
                    reason="shutdown_timeout",
                )
            self._remove_job(task_id)

        self._stop.set()
        self._monitor.join(timeout=1)

    def _monitor_jobs(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                jobs = list(self._jobs.items())
            for task_id, job in jobs:
                self._poll_job(task_id, job)
            self._stop.wait(0.01)

    def _poll_job(self, task_id: str, job: _Job) -> None:
        saw_terminal = False
        while True:
            try:
                message: WorkerMessage = job.queue.get_nowait()
            except Empty:
                break
            saw_terminal = self._handle_message(message) or saw_terminal
        if saw_terminal:
            self._remove_job(task_id)
            return
        if job.process.is_alive():
            return
        try:
            message = job.queue.get(timeout=0.05)
        except Empty:
            self._mark_unexpected_exit(task_id, job.process.exitcode)
        else:
            if self._handle_message(message):
                self._remove_job(task_id)

    def _handle_message(self, message: WorkerMessage) -> bool:
        task = self._repository.get(message.task_id)
        if task is None or task.status in TERMINAL_TASK_STATUSES:
            return True
        if message.kind is WorkerMessageKind.PROGRESS:
            updated = task.evolve(
                progress=message.progress,
                current_step=message.current_step,
            )
            self._repository.update(
                updated,
                expected_revision=task.revision,
                event_type="task.progress",
            )
            return False

        target = {
            WorkerMessageKind.SUCCEEDED: TaskStatus.SUCCEEDED,
            WorkerMessageKind.FAILED: TaskStatus.FAILED,
            WorkerMessageKind.CANCELED: TaskStatus.CANCELED,
        }[message.kind]
        updated = task.evolve(
            status=transition_task(task.status, target),
            progress=message.progress,
            current_step=message.current_step,
            finished_at=datetime.now(UTC),
            result=message.payload if target is TaskStatus.SUCCEEDED else None,
            error_code="worker_failed" if target is TaskStatus.FAILED else None,
            error_message=(
                str(message.payload.get("error_type"))
                if target is TaskStatus.FAILED and message.payload is not None
                else None
            ),
        )
        self._repository.update(
            updated,
            expected_revision=task.revision,
            event_type=f"task.{target.value.lower()}",
        )
        return True

    def _mark_unexpected_exit(self, task_id: str, exit_code: int | None) -> None:
        task = self._repository.get(task_id)
        if task is not None and task.status not in TERMINAL_TASK_STATUSES:
            failed = task.evolve(
                status=transition_task(task.status, TaskStatus.FAILED),
                current_step="failed",
                finished_at=datetime.now(UTC),
                error_code="worker_exited",
                error_message=f"worker exited with code {exit_code}",
            )
            self._repository.update(
                failed,
                expected_revision=task.revision,
                event_type="task.failed",
                reason="worker_exited",
            )
        self._remove_job(task_id)

    def _remove_job(self, task_id: str) -> None:
        with self._lock:
            job = self._jobs.pop(task_id, None)
        if job is None:
            return
        job.process.join(timeout=1)
        job.queue.close()
        job.queue.join_thread()

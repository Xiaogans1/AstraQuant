import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from astraquant_api.database import create_database, migrate_database
from astraquant_api.repository import TaskRepository
from astraquant_api.supervisor import TaskSupervisor
from astraquant_api.task_model import TERMINAL_TASK_STATUSES, TaskRecord, TaskStatus


def crash_worker(
    _task_id: str,
    _queue: Any,
    _cancel: Any,
    _step_delay: float,
) -> None:
    os._exit(7)


def build_repository(tmp_path: Path) -> TaskRepository:
    database_url = f"sqlite:///{tmp_path / 'supervisor.sqlite3'}"
    migrate_database(database_url)
    return TaskRepository(create_database(database_url))


def wait_for(
    repository: TaskRepository,
    task_id: str,
    predicate: Callable[[TaskRecord], bool],
    timeout: float = 10,
) -> TaskRecord:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = repository.get(task_id)
        assert task is not None
        if predicate(task):
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach expected state")


def create_task(repository: TaskRepository, key: str) -> TaskRecord:
    task = TaskRecord.create("demo.self_check", key)
    repository.create(task, event_type="task.created")
    return task


def test_start_demo_reports_progress_and_success(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    task = create_task(repository, "idem-success")
    supervisor = TaskSupervisor(repository, step_delay=0.001)

    running = supervisor.start_demo(task)
    completed = wait_for(
        repository,
        task.task_id,
        lambda current: current.status is TaskStatus.SUCCEEDED,
    )
    supervisor.shutdown(1)

    assert running.status is TaskStatus.RUNNING
    assert running.worker_pid is not None
    assert completed.progress == 100
    assert completed.result == {"checks": 6, "status": "healthy"}
    assert supervisor.active_count() == 0


def test_cancel_is_idempotent(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    task = create_task(repository, "idem-cancel")
    supervisor = TaskSupervisor(repository, step_delay=0.2)
    supervisor.start_demo(task)

    requested = supervisor.cancel(task.task_id)
    canceled = wait_for(
        repository,
        task.task_id,
        lambda current: current.status is TaskStatus.CANCELED,
    )
    repeated = supervisor.cancel(task.task_id)
    supervisor.shutdown(1)

    assert requested.status is TaskStatus.CANCEL_REQUESTED
    assert canceled.status is TaskStatus.CANCELED
    assert repeated == canceled


def test_unexpected_worker_exit_marks_task_failed(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    task = create_task(repository, "idem-crash")
    supervisor = TaskSupervisor(
        repository,
        step_delay=0,
        worker_target=crash_worker,
    )

    supervisor.start_demo(task)
    failed = wait_for(
        repository,
        task.task_id,
        lambda current: current.status in TERMINAL_TASK_STATUSES,
    )
    supervisor.shutdown(1)

    assert failed.status is TaskStatus.FAILED
    assert failed.error_code == "worker_exited"


def test_shutdown_cancels_live_jobs(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    task = create_task(repository, "idem-shutdown")
    supervisor = TaskSupervisor(repository, step_delay=0.2)
    supervisor.start_demo(task)

    supervisor.shutdown(2)

    stopped = repository.get(task.task_id)
    assert stopped is not None
    assert stopped.status is TaskStatus.CANCELED
    assert supervisor.active_count() == 0

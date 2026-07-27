from multiprocessing import get_context
from queue import Empty
from typing import Any

from astraquant_api.worker import WorkerMessage, WorkerMessageKind, run_demo_worker


def collect_messages(cancel_immediately: bool) -> list[WorkerMessage]:
    context = get_context("spawn")
    queue = context.Queue()
    cancel = context.Event()
    if cancel_immediately:
        cancel.set()
    process = context.Process(
        target=run_demo_worker,
        args=("task-1", queue, cancel, 0.001),
    )
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 0
    messages: list[WorkerMessage] = []
    while True:
        try:
            message: Any = queue.get_nowait()
            messages.append(message)
        except Empty:
            return messages


def test_demo_worker_reports_six_steps_and_success() -> None:
    messages = collect_messages(cancel_immediately=False)

    kinds = [message.kind for message in messages]
    assert kinds.count(WorkerMessageKind.PROGRESS) == 6
    assert kinds[-1] is WorkerMessageKind.SUCCEEDED
    assert messages[-1].payload == {"checks": 6, "status": "healthy"}


def test_demo_worker_honors_cancellation() -> None:
    messages = collect_messages(cancel_immediately=True)

    assert messages[-1].kind is WorkerMessageKind.CANCELED

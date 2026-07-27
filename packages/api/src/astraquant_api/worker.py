from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class WorkerMessageKind(StrEnum):
    PROGRESS = "PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


@dataclass(frozen=True, slots=True)
class WorkerMessage:
    task_id: str
    kind: WorkerMessageKind
    progress: int
    current_step: str
    payload: dict[str, object] | None = None


DEMO_STEPS = (
    "check_runtime",
    "check_state_directory",
    "check_database",
    "check_worker_channel",
    "check_logging",
    "finalize",
)

DEFAULT_DEMO_STEP_DELAY = 1.0


def run_demo_worker(
    task_id: str,
    queue: Any,
    cancel: Any,
    step_delay: float,
) -> None:
    try:
        for index, step in enumerate(DEMO_STEPS, start=1):
            if cancel.is_set():
                queue.put(
                    WorkerMessage(
                        task_id=task_id,
                        kind=WorkerMessageKind.CANCELED,
                        progress=round((index - 1) / len(DEMO_STEPS) * 100),
                        current_step="canceled",
                    )
                )
                return
            time.sleep(step_delay)
            queue.put(
                WorkerMessage(
                    task_id=task_id,
                    kind=WorkerMessageKind.PROGRESS,
                    progress=round(index / len(DEMO_STEPS) * 100),
                    current_step=step,
                )
            )

        queue.put(
            WorkerMessage(
                task_id=task_id,
                kind=WorkerMessageKind.SUCCEEDED,
                progress=100,
                current_step="completed",
                payload={"checks": 6, "status": "healthy"},
            )
        )
    except Exception as error:
        queue.put(
            WorkerMessage(
                task_id=task_id,
                kind=WorkerMessageKind.FAILED,
                progress=0,
                current_step="failed",
                payload={"error_type": type(error).__name__},
            )
        )

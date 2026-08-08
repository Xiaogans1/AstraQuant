from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypedDict, Unpack
from uuid import uuid4


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    INTERRUPTED = "INTERRUPTED"


ACTIVE_TASK_STATUSES = frozenset(
    {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}
)
TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELED,
        TaskStatus.INTERRUPTED,
    }
)

_TRANSITIONS = MappingProxyType(
    {
        TaskStatus.PENDING: frozenset(
            {TaskStatus.RUNNING, TaskStatus.CANCELED, TaskStatus.INTERRUPTED}
        ),
        TaskStatus.RUNNING: frozenset(
            {
                TaskStatus.CANCEL_REQUESTED,
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.INTERRUPTED,
            }
        ),
        TaskStatus.CANCEL_REQUESTED: frozenset(
            {
                TaskStatus.CANCELED,
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.INTERRUPTED,
            }
        ),
        TaskStatus.SUCCEEDED: frozenset(),
        TaskStatus.FAILED: frozenset(),
        TaskStatus.CANCELED: frozenset(),
        TaskStatus.INTERRUPTED: frozenset(),
    }
)


class InvalidTaskTransition(ValueError):
    """Raised when a platform task attempts an illegal state transition."""


class TaskChanges(TypedDict, total=False):
    status: TaskStatus
    progress: int
    current_step: str
    worker_pid: int | None
    started_at: datetime | None
    finished_at: datetime | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None


def transition_task(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if target not in _TRANSITIONS[current]:
        raise InvalidTaskTransition(f"cannot transition task from {current} to {target}")
    return target


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    task_type: str
    status: TaskStatus
    progress: int
    current_step: str
    correlation_id: str
    idempotency_key: str
    worker_pid: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    revision: int

    def __post_init__(self) -> None:
        if not 0 <= self.progress <= 100:
            raise ValueError("progress must be between 0 and 100")
        for value in (self.created_at, self.started_at, self.finished_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("task timestamps must be timezone-aware")

    @classmethod
    def create(cls, task_type: str, idempotency_key: str) -> TaskRecord:
        return cls(
            task_id=str(uuid4()),
            task_type=task_type,
            status=TaskStatus.PENDING,
            progress=0,
            current_step="queued",
            correlation_id=str(uuid4()),
            idempotency_key=idempotency_key,
            worker_pid=None,
            created_at=datetime.now(UTC),
            started_at=None,
            finished_at=None,
            result=None,
            error_code=None,
            error_message=None,
            revision=0,
        )

    def evolve(self, **changes: Unpack[TaskChanges]) -> TaskRecord:
        return replace(self, revision=self.revision + 1, **changes)

from datetime import UTC, datetime
from uuid import UUID

import pytest

from astraquant_api.task_model import (
    ACTIVE_TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
    InvalidTaskTransition,
    TaskRecord,
    TaskStatus,
    transition_task,
)


def test_create_pending_task() -> None:
    task = TaskRecord.create("demo.self_check", "idem-1")

    assert UUID(task.task_id)
    assert UUID(task.correlation_id)
    assert task.status is TaskStatus.PENDING
    assert task.progress == 0
    assert task.revision == 0
    assert task.idempotency_key == "idem-1"
    assert task.created_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.RUNNING),
        (TaskStatus.PENDING, TaskStatus.CANCELED),
        (TaskStatus.PENDING, TaskStatus.INTERRUPTED),
        (TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED),
        (TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
        (TaskStatus.RUNNING, TaskStatus.FAILED),
        (TaskStatus.CANCEL_REQUESTED, TaskStatus.CANCELED),
    ],
)
def test_allow_valid_transition(current: TaskStatus, target: TaskStatus) -> None:
    assert transition_task(current, target) is target


@pytest.mark.parametrize("terminal", sorted(TERMINAL_TASK_STATUSES))
def test_terminal_state_rejects_transition(terminal: TaskStatus) -> None:
    with pytest.raises(InvalidTaskTransition):
        transition_task(terminal, TaskStatus.RUNNING)


def test_status_sets_are_disjoint() -> None:
    assert ACTIVE_TASK_STATUSES.isdisjoint(TERMINAL_TASK_STATUSES)


def test_progress_must_be_bounded() -> None:
    with pytest.raises(ValueError, match="progress"):
        TaskRecord(
            task_id="1",
            task_type="demo.self_check",
            status=TaskStatus.RUNNING,
            progress=101,
            current_step="invalid",
            correlation_id="2",
            idempotency_key="idem",
            worker_pid=None,
            created_at=datetime.now(UTC),
            started_at=None,
            finished_at=None,
            result=None,
            error_code=None,
            error_message=None,
            revision=0,
        )

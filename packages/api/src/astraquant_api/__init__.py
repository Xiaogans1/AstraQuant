"""Local control-plane package for AstraQuant."""

from astraquant_api.task_model import (
    ACTIVE_TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
    InvalidTaskTransition,
    TaskRecord,
    TaskStatus,
    transition_task,
)

__version__ = "0.1.0"

__all__ = [
    "ACTIVE_TASK_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "InvalidTaskTransition",
    "TaskRecord",
    "TaskStatus",
    "__version__",
    "transition_task",
]

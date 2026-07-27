from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from astraquant_api.logging import ActivityRecord
from astraquant_api.task_model import TaskRecord, TaskStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    protocol_version: Literal[1] = 1
    service_version: str


class RuntimeResponse(StrictModel):
    active_workers: int = Field(ge=0)
    database_size_bytes: int = Field(ge=0)
    shutting_down: bool


class TaskResponse(StrictModel):
    task_id: str
    task_type: str
    status: TaskStatus
    progress: int = Field(ge=0, le=100)
    current_step: str
    correlation_id: str
    worker_pid: int | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    revision: int = Field(ge=0)

    @classmethod
    def from_record(cls, task: TaskRecord) -> TaskResponse:
        return cls(
            task_id=task.task_id,
            task_type=task.task_type,
            status=task.status,
            progress=task.progress,
            current_step=task.current_step,
            correlation_id=task.correlation_id,
            worker_pid=task.worker_pid,
            created_at=task.created_at.isoformat(),
            started_at=None if task.started_at is None else task.started_at.isoformat(),
            finished_at=(
                None if task.finished_at is None else task.finished_at.isoformat()
            ),
            result=task.result,
            error_code=task.error_code,
            error_message=task.error_message,
            revision=task.revision,
        )


class ActivityItem(StrictModel):
    timestamp: str
    level: str
    event: str
    component: str | None
    correlation_id: str | None
    task_id: str | None

    @classmethod
    def from_record(cls, record: ActivityRecord) -> ActivityItem:
        return cls.model_validate(record, from_attributes=True)


class Settings(StrictModel):
    theme: Literal["astra-minimal", "astra-light"] = "astra-minimal"
    reduced_motion: bool = False
    sidebar_collapsed: bool = False
    background_effect: Literal["none", "nebula", "grid"] = "nebula"

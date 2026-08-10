from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Engine, RowMapping
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from astraquant_api.task_model import (
    ACTIVE_TASK_STATUSES,
    TaskRecord,
    TaskStatus,
    transition_task,
)

metadata = sa.MetaData()

tasks = sa.Table(
    "tasks",
    metadata,
    sa.Column("task_id", sa.String(36), primary_key=True),
    sa.Column("task_type", sa.String(100), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("progress", sa.Integer(), nullable=False),
    sa.Column("current_step", sa.String(200), nullable=False),
    sa.Column("correlation_id", sa.String(36), nullable=False),
    sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
    sa.Column("worker_pid", sa.Integer()),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("result_json", sa.Text()),
    sa.Column("error_code", sa.String(100)),
    sa.Column("error_message", sa.Text()),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_tasks_progress"),
    sa.Index("ix_tasks_created_at", "created_at"),
)

task_events = sa.Table(
    "task_events",
    metadata,
    sa.Column("event_id", sa.String(36), primary_key=True),
    sa.Column(
        "task_id",
        sa.String(36),
        sa.ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("event_type", sa.String(100), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("progress", sa.Integer(), nullable=False),
    sa.Column("reason", sa.String(200)),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Index("ix_task_events_task_id", "task_id"),
)

settings = sa.Table(
    "settings",
    metadata,
    sa.Column("key", sa.String(100), primary_key=True),
    sa.Column("value_json", sa.Text(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True, slots=True)
class TaskEventRecord:
    event_id: str
    task_id: str
    event_type: str
    status: TaskStatus
    progress: int
    reason: str | None
    occurred_at: datetime
    revision: int


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _task_values(task: TaskRecord) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "status": task.status.value,
        "progress": task.progress,
        "current_step": task.current_step,
        "correlation_id": task.correlation_id,
        "idempotency_key": task.idempotency_key,
        "worker_pid": task.worker_pid,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "result_json": None if task.result is None else _json_dump(task.result),
        "error_code": task.error_code,
        "error_message": task.error_message,
        "revision": task.revision,
    }


def _row_to_task(row: RowMapping) -> TaskRecord:
    result_json = row["result_json"]
    return TaskRecord(
        task_id=row["task_id"],
        task_type=row["task_type"],
        status=TaskStatus(row["status"]),
        progress=row["progress"],
        current_step=row["current_step"],
        correlation_id=row["correlation_id"],
        idempotency_key=row["idempotency_key"],
        worker_pid=row["worker_pid"],
        created_at=_as_utc(row["created_at"]),
        started_at=None if row["started_at"] is None else _as_utc(row["started_at"]),
        finished_at=(None if row["finished_at"] is None else _as_utc(row["finished_at"])),
        result=None if result_json is None else json.loads(result_json),
        error_code=row["error_code"],
        error_message=row["error_message"],
        revision=row["revision"],
    )


def _event_values(
    task: TaskRecord,
    event_type: str,
    reason: str | None,
) -> dict[str, object]:
    return {
        "event_id": str(uuid4()),
        "task_id": task.task_id,
        "event_type": event_type,
        "status": task.status.value,
        "progress": task.progress,
        "reason": reason,
        "occurred_at": datetime.now(UTC),
        "revision": task.revision,
    }


class TaskRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, task: TaskRecord, *, event_type: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(tasks.insert().values(**_task_values(task)))
            connection.execute(task_events.insert().values(**_event_values(task, event_type, None)))

    def get(self, task_id: str) -> TaskRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(sa.select(tasks).where(tasks.c.task_id == task_id))
                .mappings()
                .one_or_none()
            )
        return None if row is None else _row_to_task(row)

    def get_by_idempotency_key(self, key: str) -> TaskRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(sa.select(tasks).where(tasks.c.idempotency_key == key))
                .mappings()
                .one_or_none()
            )
        return None if row is None else _row_to_task(row)

    def list_tasks(self, *, limit: int = 100) -> list[TaskRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.select(tasks).order_by(tasks.c.created_at.desc()).limit(limit)
            ).mappings()
            return [_row_to_task(row) for row in rows]

    def update(
        self,
        task: TaskRecord,
        *,
        expected_revision: int,
        event_type: str,
        reason: str | None = None,
    ) -> bool:
        values = _task_values(task)
        values.pop("task_id")
        with self._engine.begin() as connection:
            result = connection.execute(
                tasks.update()
                .where(tasks.c.task_id == task.task_id)
                .where(tasks.c.revision == expected_revision)
                .values(**values)
            )
            if result.rowcount != 1:
                return False
            connection.execute(
                task_events.insert().values(**_event_values(task, event_type, reason))
            )
        return True

    def list_events(
        self,
        task_id: str,
        *,
        limit: int = 100,
    ) -> list[TaskEventRecord]:
        with self._engine.connect() as connection:
            rows = list(
                connection.execute(
                    sa.select(task_events)
                    .where(task_events.c.task_id == task_id)
                    .order_by(task_events.c.occurred_at.asc())
                    .limit(limit)
                ).mappings()
            )
        return [
            TaskEventRecord(
                event_id=row["event_id"],
                task_id=row["task_id"],
                event_type=row["event_type"],
                status=TaskStatus(row["status"]),
                progress=row["progress"],
                reason=row["reason"],
                occurred_at=_as_utc(row["occurred_at"]),
                revision=row["revision"],
            )
            for row in rows
        ]

    def interrupt_active_tasks(self, reason: str) -> int:
        recovered = 0
        for task in self.list_tasks():
            if task.status not in ACTIVE_TASK_STATUSES:
                continue
            interrupted = task.evolve(
                status=transition_task(task.status, TaskStatus.INTERRUPTED),
                current_step="interrupted",
                finished_at=datetime.now(UTC),
            )
            if self.update(
                interrupted,
                expected_revision=task.revision,
                event_type="task.interrupted",
                reason=reason,
            ):
                recovered += 1
        return recovered

    def get_setting(self, key: str) -> object | None:
        with self._engine.connect() as connection:
            value = connection.execute(
                sa.select(settings.c.value_json).where(settings.c.key == key)
            ).scalar_one_or_none()
        return None if value is None else json.loads(value)

    def set_setting(self, key: str, value: object) -> None:
        statement = sqlite_insert(settings).values(
            key=key,
            value_json=_json_dump(value),
            updated_at=datetime.now(UTC),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[settings.c.key],
            set_={
                "value_json": statement.excluded.value_json,
                "updated_at": statement.excluded.updated_at,
            },
        )
        with self._engine.begin() as connection:
            connection.execute(statement)

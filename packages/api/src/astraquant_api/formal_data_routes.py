"""Authenticated orchestration route for formal real-provider captures."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, Header, HTTPException
from fastapi.params import Depends
from fastapi.responses import JSONResponse

from astraquant_api.formal_data_schemas import (
    FormalCaptureRequest,
    ResolvedFormalCaptureCommand,
)
from astraquant_api.formal_data_service import FormalCaptureAdmissionError
from astraquant_api.formal_data_worker import run_formal_data_worker
from astraquant_api.repository import TaskRepository
from astraquant_api.schemas import TaskResponse
from astraquant_api.secret_store import SecretStore, SecretStoreUnavailable
from astraquant_api.task_model import TaskRecord


class FormalCaptureAdmission(Protocol):
    def resolve(
        self,
        request: FormalCaptureRequest,
        *,
        created_at: datetime,
    ) -> ResolvedFormalCaptureCommand: ...


class FormalCaptureSupervisor(Protocol):
    def start(
        self,
        task: TaskRecord,
        worker_target: Callable[..., None],
        worker_args: tuple[object, ...],
    ) -> TaskRecord: ...


class FormalDataRouteState(Protocol):
    @property
    def repository(self) -> TaskRepository: ...

    @property
    def supervisor(self) -> FormalCaptureSupervisor: ...

    @property
    def state_dir(self) -> Path: ...

    @property
    def secret_store(self) -> SecretStore | None: ...

    @property
    def formal_capture_service(self) -> FormalCaptureAdmission | None: ...

    @property
    def formal_sdk_python(self) -> Path | None: ...

    @property
    def formal_bridge_script(self) -> Path | None: ...

    @property
    def shutting_down(self) -> bool: ...


def build_formal_data_router(
    state: FormalDataRouteState,
    authenticated: Depends,
    validate_idempotency_key: Callable[[str | None], str],
) -> APIRouter:
    router = APIRouter(prefix="/v1/formal-data", dependencies=[authenticated])

    @router.post("/captures", response_model=TaskResponse)
    def create_capture(
        request: FormalCaptureRequest,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        key = validate_idempotency_key(idempotency_key)
        existing = state.repository.get_by_idempotency_key(key)
        if existing is not None:
            return _task_json(existing, 200)
        if state.shutting_down:
            raise HTTPException(503, "runtime is shutting down")
        if (
            state.formal_capture_service is None
            or state.secret_store is None
            or state.formal_sdk_python is None
            or state.formal_bridge_script is None
        ):
            raise HTTPException(503, "formal capture runtime is unavailable")
        try:
            token = state.secret_store.get_eastmoney_token()
        except SecretStoreUnavailable as error:
            raise HTTPException(503, "formal capture credential is unavailable") from error
        if token is None:
            raise HTTPException(503, "formal capture credential is unavailable")
        try:
            command = state.formal_capture_service.resolve(
                request,
                created_at=datetime.now(UTC),
            )
        except FormalCaptureAdmissionError as error:
            raise HTTPException(422, str(error)) from error
        task = TaskRecord.create("data.formal_capture", key)
        state.repository.create(task, event_type="task.created")
        running = state.supervisor.start(
            task,
            run_formal_data_worker,
            (
                command.model_dump(mode="json"),
                str(state.state_dir / "formal" / "capture"),
                str(state.formal_sdk_python),
                str(state.formal_bridge_script),
                token,
            ),
        )
        return _task_json(running, 201)

    return router


def _task_json(task: TaskRecord, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=TaskResponse.from_record(task).model_dump(mode="json"),
    )

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Annotated, Protocol, cast

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from astraquant_api import __version__
from astraquant_api.data_repository import DataCatalogRepository
from astraquant_api.logging import ActivityBuffer
from astraquant_api.market_service import MarketDataService
from astraquant_api.repository import TaskRepository
from astraquant_api.schemas import (
    ActivityItem,
    HealthResponse,
    RuntimeResponse,
    Settings,
    TaskResponse,
)
from astraquant_api.secret_store import SecretStore
from astraquant_api.task_model import TaskRecord
from astraquant_data.live_providers import LiveMarketProvider

if TYPE_CHECKING:
    from astraquant_api.paper_strategy_service import PaperStrategyService


class Supervisor(Protocol):
    def start_demo(self, task: TaskRecord) -> TaskRecord: ...

    def start(
        self,
        task: TaskRecord,
        worker_target: Callable[..., None],
        worker_args: tuple[object, ...],
    ) -> TaskRecord: ...

    def cancel(self, task_id: str) -> TaskRecord: ...

    def active_count(self) -> int: ...

    def shutdown(self, timeout_seconds: float) -> None: ...


class PaperLifecycle(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(slots=True)
class AppState:
    repository: TaskRepository
    data_catalog: DataCatalogRepository
    supervisor: Supervisor
    activity: ActivityBuffer
    session_token: str
    state_dir: Path
    market_service: MarketDataService | None = None
    paper_service: PaperLifecycle | None = None
    paper_strategy_service: PaperStrategyService | None = None
    secret_store: SecretStore | None = None
    market_provider_factory: Callable[[Path, float], LiveMarketProvider] | None = None
    allowed_data_instruments: frozenset[str] = frozenset({"600000.SSE", "RB0.SHFE"})
    enable_akshare: bool = False
    shutdown_grace_seconds: float = 5.0
    shutting_down: bool = False
    shutdown_event: Event = field(default_factory=Event)


@dataclass(frozen=True, slots=True)
class ApiProblem(Exception):
    status_code: int
    code: str
    message: str


def create_app(state: AppState) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        strategy_task: asyncio.Task[None] | None = None
        if state.market_service is not None:
            await state.market_service.start()
        if state.paper_service is not None:
            state.paper_service.start()
        if state.paper_strategy_service is not None:
            strategy_task = asyncio.create_task(state.paper_strategy_service.run_loop())
        try:
            yield
        finally:
            if strategy_task is not None:
                strategy_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await strategy_task
            if state.paper_service is not None:
                state.paper_service.stop()
            if state.market_service is not None:
                await state.market_service.stop()

    app = FastAPI(
        title="AstraQuant Local API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.runtime = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "tauri://localhost",
            "https://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.exception_handler(ApiProblem)
    async def handle_api_problem(
        _request: Request,
        problem: ApiProblem,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=problem.status_code,
            content={"code": problem.code, "message": problem.message},
        )

    def require_auth(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        scheme, separator, token = (authorization or "").partition(" ")
        valid = (
            separator == " "
            and scheme.lower() == "bearer"
            and secrets.compare_digest(token, state.session_token)
        )
        if not valid:
            raise ApiProblem(401, "unauthorized", "本地会话认证失败")

    authenticated = Depends(require_auth)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(service_version=__version__)

    @app.get(
        "/v1/runtime",
        response_model=RuntimeResponse,
        dependencies=[authenticated],
    )
    def runtime() -> RuntimeResponse:
        database_path = state.state_dir / "state" / "astraquant.sqlite3"
        return RuntimeResponse(
            active_workers=state.supervisor.active_count(),
            database_size_bytes=(database_path.stat().st_size if database_path.exists() else 0),
            shutting_down=state.shutting_down,
        )

    @app.get(
        "/v1/tasks",
        response_model=list[TaskResponse],
        dependencies=[authenticated],
    )
    def list_tasks(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[TaskResponse]:
        return [TaskResponse.from_record(task) for task in state.repository.list_tasks(limit=limit)]

    @app.post(
        "/v1/tasks/demo",
        response_model=TaskResponse,
        dependencies=[authenticated],
    )
    def create_demo_task(
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        key = _validate_idempotency_key(idempotency_key)
        existing = state.repository.get_by_idempotency_key(key)
        if existing is not None:
            return _task_json(existing, status_code=200)
        if state.shutting_down:
            raise ApiProblem(503, "runtime_shutting_down", "本地服务正在关闭")
        task = TaskRecord.create("demo.self_check", key)
        state.repository.create(task, event_type="task.created")
        running = state.supervisor.start_demo(task)
        return _task_json(running, status_code=201)

    @app.get(
        "/v1/tasks/{task_id}",
        response_model=TaskResponse,
        dependencies=[authenticated],
    )
    def get_task(task_id: str) -> TaskResponse:
        task = state.repository.get(task_id)
        if task is None:
            raise ApiProblem(404, "task_not_found", "未找到任务")
        return TaskResponse.from_record(task)

    @app.post(
        "/v1/tasks/{task_id}/cancel",
        response_model=TaskResponse,
        dependencies=[authenticated],
    )
    def cancel_task(task_id: str) -> TaskResponse:
        try:
            task = state.supervisor.cancel(task_id)
        except KeyError:
            raise ApiProblem(404, "task_not_found", "未找到任务") from None
        return TaskResponse.from_record(task)

    @app.get(
        "/v1/activity",
        response_model=list[ActivityItem],
        dependencies=[authenticated],
    )
    def activity(
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> list[ActivityItem]:
        return [ActivityItem.from_record(item) for item in state.activity.list_items(limit=limit)]

    @app.get(
        "/v1/settings",
        response_model=Settings,
        dependencies=[authenticated],
    )
    def get_settings() -> Settings:
        stored = state.repository.get_setting("ui")
        return Settings.model_validate(stored or {})

    @app.patch(
        "/v1/settings",
        response_model=Settings,
        dependencies=[authenticated],
    )
    def update_settings(settings: Settings) -> Settings:
        state.repository.set_setting("ui", settings.model_dump(mode="json"))
        return settings

    @app.post("/internal/shutdown", dependencies=[authenticated])
    def shutdown() -> JSONResponse:
        if not state.shutting_down:
            state.shutting_down = True
            state.supervisor.shutdown(state.shutdown_grace_seconds)
            state.shutdown_event.set()
        return JSONResponse(
            status_code=202,
            content={"status": "shutting_down"},
        )

    from astraquant_api.data_routes import build_data_router

    app.include_router(build_data_router(state, authenticated))
    if (
        state.market_service is not None
        and state.secret_store is not None
        and state.market_provider_factory is not None
    ):
        from astraquant_api.market_routes import build_market_router

        app.include_router(
            build_market_router(
                repository=state.repository,
                service=state.market_service,
                secret_store=state.secret_store,
                provider_factory=state.market_provider_factory,
                authenticated=authenticated,
            )
        )
    if state.paper_service is not None:
        from astraquant_api.paper_routes import build_paper_router
        from astraquant_api.paper_service import PaperService
        from astraquant_api.research_routes import build_research_router

        paper_service = cast(PaperService, state.paper_service)
        app.include_router(
            build_paper_router(
                service=paper_service,
                strategy_service=state.paper_strategy_service,
                authenticated=authenticated,
                validate_idempotency_key=_validate_idempotency_key,
                settings_store=state.repository,
            )
        )
        app.include_router(
            build_research_router(
                data_root=state.state_dir / "data",
                models=paper_service,
                authenticated=authenticated,
            )
        )
    return app


def _validate_idempotency_key(value: str | None) -> str:
    if value is None or not 8 <= len(value) <= 200:
        raise ApiProblem(
            400,
            "invalid_idempotency_key",
            "Idempotency-Key 长度必须为 8 到 200 个字符",
        )
    if any(ord(character) < 33 or ord(character) > 126 for character in value):
        raise ApiProblem(
            400,
            "invalid_idempotency_key",
            "Idempotency-Key 只能包含可见 ASCII 字符",
        )
    return value


def _task_json(task: TaskRecord, *, status_code: int) -> JSONResponse:
    response = TaskResponse.from_record(task)
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json"),
    )

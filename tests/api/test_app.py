from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from astraquant_api.app import AppState, create_app
from astraquant_api.data_repository import DataCatalogRepository
from astraquant_api.database import create_database, migrate_database
from astraquant_api.logging import ActivityBuffer
from astraquant_api.repository import TaskRepository
from astraquant_api.task_model import (
    TERMINAL_TASK_STATUSES,
    TaskRecord,
    TaskStatus,
    transition_task,
)

TOKEN = "t" * 43


class FakeSupervisor:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository
        self.shutdown_calls = 0

    def start_demo(self, task: TaskRecord) -> TaskRecord:
        running = task.evolve(
            status=transition_task(task.status, TaskStatus.RUNNING),
            current_step="started",
            started_at=datetime.now(UTC),
            worker_pid=4242,
        )
        assert self.repository.update(
            running,
            expected_revision=task.revision,
            event_type="task.started",
        )
        return running

    def start(
        self,
        task: TaskRecord,
        _worker_target: Callable[..., None],
        _worker_args: tuple[object, ...],
    ) -> TaskRecord:
        return self.start_demo(task)

    def cancel(self, task_id: str) -> TaskRecord:
        task = self.repository.get(task_id)
        if task is None:
            raise KeyError(task_id)
        if task.status in TERMINAL_TASK_STATUSES:
            return task
        requested = task.evolve(
            status=transition_task(task.status, TaskStatus.CANCEL_REQUESTED),
            current_step="cancel_requested",
        )
        assert self.repository.update(
            requested,
            expected_revision=task.revision,
            event_type="task.cancel_requested",
        )
        return requested

    def finish(self, task_id: str) -> TaskRecord:
        task = self.repository.get(task_id)
        assert task is not None
        finished = task.evolve(
            status=transition_task(task.status, TaskStatus.SUCCEEDED),
            progress=100,
            current_step="completed",
            finished_at=datetime.now(UTC),
            result={"checks": 6, "status": "healthy"},
        )
        assert self.repository.update(
            finished,
            expected_revision=task.revision,
            event_type="task.succeeded",
        )
        return finished

    def active_count(self) -> int:
        return len(
            [
                task
                for task in self.repository.list_tasks()
                if task.status not in TERMINAL_TASK_STATUSES
            ]
        )

    def shutdown(self, _timeout_seconds: float) -> None:
        self.shutdown_calls += 1


@pytest.fixture
def app_state(tmp_path: Path) -> AppState:
    database_url = f"sqlite:///{tmp_path / 'api.sqlite3'}"
    migrate_database(database_url)
    engine = create_database(database_url)
    repository = TaskRepository(engine)
    activity = ActivityBuffer()
    return AppState(
        repository=repository,
        data_catalog=DataCatalogRepository(engine),
        supervisor=FakeSupervisor(repository),
        activity=activity,
        session_token=TOKEN,
        state_dir=tmp_path,
    )


@pytest.fixture
def client(app_state: AppState) -> TestClient:
    return TestClient(create_app(app_state))


@pytest.fixture
def auth_client(app_state: AppState) -> TestClient:
    client = TestClient(create_app(app_state))
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "protocol_version": 1,
        "service_version": "0.1.0",
    }


def test_app_lifespan_starts_and_stops_paper_service(app_state: AppState) -> None:
    class FakePaperService:
        def __init__(self) -> None:
            self.started = 0
            self.stopped = 0

        def start(self) -> None:
            self.started += 1

        def stop(self) -> None:
            self.stopped += 1

    paper_service = FakePaperService()
    app_state.paper_service = paper_service

    with TestClient(create_app(app_state)):
        assert paper_service.started == 1

    assert paper_service.stopped == 1


def test_v1_requires_bearer_token(client: TestClient) -> None:
    assert client.get("/v1/runtime").status_code == 401
    assert (
        client.get(
            "/v1/runtime",
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )


def test_create_demo_task_is_idempotent(auth_client: TestClient) -> None:
    headers = {"Idempotency-Key": "demo-key-1"}
    first = auth_client.post("/v1/tasks/demo", headers=headers)
    second = auth_client.post("/v1/tasks/demo", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["task_id"] == second.json()["task_id"]


def test_cancel_terminal_task_is_idempotent(
    auth_client: TestClient,
    app_state: AppState,
) -> None:
    created = auth_client.post(
        "/v1/tasks/demo",
        headers={"Idempotency-Key": "demo-terminal"},
    ).json()
    task_id = created["task_id"]
    supervisor = app_state.supervisor
    assert isinstance(supervisor, FakeSupervisor)
    supervisor.finish(task_id)

    first = auth_client.post(f"/v1/tasks/{task_id}/cancel")
    second = auth_client.post(f"/v1/tasks/{task_id}/cancel")

    assert first.json()["status"] == "SUCCEEDED"
    assert second.json() == first.json()


def test_list_tasks_newest_first(auth_client: TestClient) -> None:
    first = auth_client.post(
        "/v1/tasks/demo",
        headers={"Idempotency-Key": "list-first"},
    ).json()
    second = auth_client.post(
        "/v1/tasks/demo",
        headers={"Idempotency-Key": "list-second"},
    ).json()

    response = auth_client.get("/v1/tasks")

    assert response.status_code == 200
    assert [item["task_id"] for item in response.json()] == [
        second["task_id"],
        first["task_id"],
    ]


def test_missing_task_returns_404(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/tasks/missing")
    assert response.status_code == 404
    assert response.json() == {
        "code": "task_not_found",
        "message": "未找到任务",
    }


def test_settings_reject_unknown_theme(auth_client: TestClient) -> None:
    response = auth_client.patch("/v1/settings", json={"theme": "unknown"})
    assert response.status_code == 422


def test_activity_honors_limit(
    auth_client: TestClient,
    app_state: AppState,
) -> None:
    from astraquant_api.logging import ActivityRecord

    for index in range(3):
        app_state.activity.append(
            ActivityRecord(
                timestamp=f"2026-07-27T00:00:0{index}Z",
                level="info",
                event=f"event.{index}",
                component="test",
                correlation_id=None,
                task_id=None,
            )
        )

    response = auth_client.get("/v1/activity", params={"limit": 2})

    assert response.status_code == 200
    assert [item["event"] for item in response.json()] == ["event.2", "event.1"]


def test_runtime_reports_active_worker_count(auth_client: TestClient) -> None:
    auth_client.post(
        "/v1/tasks/demo",
        headers={"Idempotency-Key": "runtime-active"},
    )

    response = auth_client.get("/v1/runtime")

    assert response.status_code == 200
    assert response.json()["active_workers"] == 1
    assert response.json()["shutting_down"] is False


def test_shutdown_requires_authentication(
    client: TestClient,
    auth_client: TestClient,
    app_state: AppState,
) -> None:
    assert client.post("/internal/shutdown").status_code == 401

    response = auth_client.post("/internal/shutdown")

    assert response.status_code == 202
    assert response.json() == {"status": "shutting_down"}
    assert app_state.shutting_down is True
    assert app_state.shutdown_event.is_set()

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.api.test_formal_data_worker import NOW, _command_values

from astraquant_api.app import AppState, create_app
from astraquant_api.data_repository import DataCatalogRepository
from astraquant_api.database import create_database, migrate_database
from astraquant_api.formal_data_schemas import (
    FormalCaptureRequest,
    FormalIncrementRequest,
    ResolvedFormalCaptureCommand,
)
from astraquant_api.logging import ActivityBuffer
from astraquant_api.repository import TaskRepository
from astraquant_api.secret_store import MemorySecretStore
from astraquant_api.task_model import TaskRecord, TaskStatus, transition_task
from astraquant_data.capture_reconciliation import (
    CaptureReconciliationReport,
    CaptureReconciliationStatus,
)

TOKEN = "z" * 43


class RecordingSupervisor:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository
        self.starts: list[tuple[Callable[..., None], tuple[object, ...]]] = []

    def start_demo(self, task: TaskRecord) -> TaskRecord:
        return self.start(task, lambda *_: None, ())

    def start(
        self,
        task: TaskRecord,
        worker_target: Callable[..., None],
        worker_args: tuple[object, ...],
    ) -> TaskRecord:
        self.starts.append((worker_target, worker_args))
        running = task.evolve(
            status=transition_task(task.status, TaskStatus.RUNNING),
            current_step="started",
            started_at=NOW,
            worker_pid=4242,
        )
        assert self.repository.update(
            running,
            expected_revision=task.revision,
            event_type="task.started",
        )
        return running

    def cancel(self, task_id: str) -> TaskRecord:
        task = self.repository.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def active_count(self) -> int:
        return 0

    def shutdown(self, _timeout_seconds: float) -> None:
        return None


class FakeAdmissionService:
    def __init__(self) -> None:
        self.command = ResolvedFormalCaptureCommand.model_validate(_command_values())
        self.requests: list[FormalCaptureRequest] = []

    def resolve(
        self,
        request: FormalCaptureRequest,
        *,
        created_at: datetime,
    ) -> ResolvedFormalCaptureCommand:
        assert created_at.tzinfo is not None
        self.requests.append(request)
        return self.command


def _state(tmp_path: Path, *, ready: bool = True) -> tuple[AppState, RecordingSupervisor]:
    database_path = tmp_path / "state" / "astraquant.sqlite3"
    database_path.parent.mkdir(parents=True)
    database_url = f"sqlite:///{database_path}"
    migrate_database(database_url)
    engine = create_database(database_url)
    repository = TaskRepository(engine)
    supervisor = RecordingSupervisor(repository)
    state = AppState(
        repository=repository,
        data_catalog=DataCatalogRepository(engine),
        supervisor=supervisor,
        activity=ActivityBuffer(),
        session_token=TOKEN,
        state_dir=tmp_path,
        secret_store=MemorySecretStore("private-eastmoney-token") if ready else None,
        formal_capture_service=FakeAdmissionService() if ready else None,
        formal_sdk_python=Path("D:/sdk/python.exe") if ready else None,
        formal_bridge_script=Path("D:/repo/tools/eastmoney_bridge.py") if ready else None,
    )
    return state, supervisor


def _body() -> dict[str, object]:
    values = _command_values()
    return {
        "approval_id": values["approval_id"],
        "instrument_id": values["instrument_id"],
        "frequency": values["frequency"],
        "start": values["start"],
        "end": values["end"],
        "adjustment": values["adjustment"],
    }


def test_formal_route_is_authenticated_idempotent_and_starts_only_formal_worker(
    tmp_path: Path,
) -> None:
    state, supervisor = _state(tmp_path)
    client = TestClient(create_app(state))
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Idempotency-Key": "formal-capture-600000-20260811",
    }

    first = client.post("/v1/formal-data/captures", json=_body(), headers=headers)
    second = client.post("/v1/formal-data/captures", json=_body(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["task_id"] == second.json()["task_id"]
    assert len(supervisor.starts) == 1
    target, args = supervisor.starts[0]
    assert target.__name__ == "run_formal_data_worker"
    assert isinstance(args[0], dict)
    assert args[1] == str(tmp_path / "formal" / "capture")
    serialized = first.text + second.text
    assert "private-eastmoney-token" not in serialized
    assert "D:/sdk" not in serialized


def test_formal_route_rejects_unauthenticated_and_legacy_provider_fields(tmp_path: Path) -> None:
    state, _ = _state(tmp_path)
    client = TestClient(create_app(state))

    unauthorized = client.post(
        "/v1/formal-data/captures",
        json=_body(),
        headers={"Idempotency-Key": "formal-capture-unauthorized"},
    )
    legacy = client.post(
        "/v1/formal-data/captures",
        json={**_body(), "provider": "fixture"},
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Idempotency-Key": "formal-capture-legacy-field",
        },
    )

    assert unauthorized.status_code == 401
    assert legacy.status_code == 422


def test_formal_route_fails_closed_without_trusted_runtime_dependencies(tmp_path: Path) -> None:
    state, supervisor = _state(tmp_path, ready=False)
    client = TestClient(create_app(state))

    response = client.post(
        "/v1/formal-data/captures",
        json=_body(),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Idempotency-Key": "formal-capture-runtime-unavailable",
        },
    )

    assert response.status_code == 503
    assert supervisor.starts == []


def test_increment_route_resolves_only_from_sealed_server_side_predecessor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, supervisor = _state(tmp_path)
    command = ResolvedFormalCaptureCommand.model_validate(
        {**_command_values(), "predecessor_capture_id": "sha256:" + "9" * 64}
    )
    seen: dict[str, object] = {}

    def resolve_increment(self: object, request: object, *, created_at: datetime) -> object:
        seen["request"] = request
        assert created_at.tzinfo is not None
        return command

    monkeypatch.setattr(
        "astraquant_api.formal_data_routes.FormalCaptureLineageService.resolve_increment",
        resolve_increment,
    )
    response = TestClient(create_app(state)).post(
        "/v1/formal-data/captures/increment",
        json={
            "predecessor_capture_id": "sha256:" + "9" * 64,
            "end": "2026-08-14",
        },
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Idempotency-Key": "formal-increment-600000-20260814",
        },
    )

    assert response.status_code == 201
    assert isinstance(seen["request"], FormalIncrementRequest)
    assert seen["request"].predecessor_capture_id == "sha256:" + "9" * 64
    assert len(supervisor.starts) == 1
    command_values = supervisor.starts[0][1][0]
    assert isinstance(command_values, dict)
    assert command_values["predecessor_capture_id"] == "sha256:" + "9" * 64


def test_reconcile_route_accepts_only_two_exact_capture_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, supervisor = _state(tmp_path, ready=False)
    left = "sha256:" + "7" * 64
    right = "sha256:" + "8" * 64
    seen: dict[str, object] = {}
    report = CaptureReconciliationReport(
        left_capture_id=left,
        right_capture_id=right,
        left_seal_digest="sha256:" + "1" * 64,
        right_seal_digest="sha256:" + "2" * 64,
        left_scope_digest="sha256:" + "3" * 64,
        right_scope_digest="sha256:" + "3" * 64,
        left_content_digest="sha256:" + "4" * 64,
        right_content_digest="sha256:" + "5" * 64,
        status=CaptureReconciliationStatus.CONTENT_MISMATCH,
        differences=("CONTENT",),
    )

    def reconcile(store: object, left_id: str, right_id: str) -> object:
        seen.update(store=store, left=left_id, right=right_id)
        return report

    monkeypatch.setattr("astraquant_api.formal_data_routes.reconcile_captures", reconcile)
    response = TestClient(create_app(state)).post(
        "/v1/formal-data/captures/reconcile",
        json={"left_capture_id": left, "right_capture_id": right},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json() == {**report.to_dict(), "report_digest": report.report_digest}
    assert seen["left"] == left
    assert seen["right"] == right
    assert supervisor.starts == []

    invalid = TestClient(create_app(state)).post(
        "/v1/formal-data/captures/reconcile",
        json={
            "left_capture_id": left,
            "right_capture_id": right,
            "provider": "fixture",
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert invalid.status_code == 422

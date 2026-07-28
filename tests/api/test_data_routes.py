from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from tests.data.factories import make_bar

from astraquant_api.app import AppState, create_app
from astraquant_api.data_repository import DataCatalogRepository
from astraquant_api.database import create_database, migrate_database
from astraquant_api.logging import ActivityBuffer
from astraquant_api.repository import TaskRepository
from astraquant_api.task_model import TaskRecord, TaskStatus, transition_task
from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_domain import FixedClock

TOKEN = "d" * 43


class RouteSupervisor:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    def start_demo(self, task: TaskRecord) -> TaskRecord:
        return self.start(task, lambda *_args: None, ())

    def start(
        self,
        task: TaskRecord,
        _worker_target: Callable[..., None],
        _worker_args: tuple[object, ...],
    ) -> TaskRecord:
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

    def cancel(self, task_id: str) -> TaskRecord:
        task = self.repository.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def active_count(self) -> int:
        return 0

    def shutdown(self, _timeout_seconds: float) -> None:
        return None


def _state(tmp_path: Path) -> AppState:
    database_path = tmp_path / "state" / "astraquant.sqlite3"
    database_path.parent.mkdir(parents=True)
    database_url = f"sqlite:///{database_path}"
    migrate_database(database_url)
    engine = create_database(database_url)
    tasks = TaskRepository(engine)
    return AppState(
        repository=tasks,
        data_catalog=DataCatalogRepository(engine),
        supervisor=RouteSupervisor(tasks),
        activity=ActivityBuffer(),
        session_token=TOKEN,
        state_dir=tmp_path,
        allowed_data_instruments=frozenset({"600000.SSE", "RB0.SHFE"}),
    )


def _client(tmp_path: Path) -> tuple[TestClient, AppState]:
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client, state


def _publish_sample(state: AppState) -> str:
    snapshot = ParquetSnapshotStore(
        state.state_dir / "data",
        clock=FixedClock(datetime(2026, 7, 28, tzinfo=UTC)),
    ).publish_bars(
        dataset_id="cn-equity-600000-sse-1d-none",
        bars=[make_bar(availability_estimated=False)],
        provider={"id": "fixture", "interface": "memory", "version": "1"},
        calendar_version="fixture-v1",
        availability_policy="fixture",
    )
    state.data_catalog.stage_snapshot(
        snapshot,
        name="600000.SSE 日线",
        asset_class="equity",
        frequency="1d",
    )
    assert state.data_catalog.mark_published(snapshot.snapshot_id)
    return snapshot.snapshot_id


def test_create_import_is_authenticated_idempotent_and_forbids_trade_fields(
    tmp_path: Path,
) -> None:
    client, _state_value = _client(tmp_path)
    body = {
        "provider": "fixture",
        "instrument_id": "600000.SSE",
        "frequency": "1d",
        "start": "2026-07-20",
        "end": "2026-07-24",
        "adjustment": "none",
    }
    headers = {"Idempotency-Key": "data-import-600000-20260724"}

    first = client.post("/v1/data/imports", json=body, headers=headers)
    second = client.post("/v1/data/imports", json=body, headers=headers)
    rejected = client.post(
        "/v1/data/imports",
        json={**body, "account_id": "forbidden"},
        headers={"Idempotency-Key": "data-import-reject-0001"},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["task_id"] == second.json()["task_id"]
    assert rejected.status_code == 422


def test_import_rejects_unconfigured_instrument_and_disabled_akshare(
    tmp_path: Path,
) -> None:
    client, _state_value = _client(tmp_path)
    body = {
        "provider": "fixture",
        "instrument_id": "000001.SZSE",
        "frequency": "1d",
        "start": "2026-07-20",
        "end": "2026-07-24",
        "adjustment": "none",
    }

    blocked = client.post(
        "/v1/data/imports",
        json=body,
        headers={"Idempotency-Key": "data-import-blocked-0001"},
    )
    akshare = client.post(
        "/v1/data/imports",
        json={**body, "provider": "akshare", "instrument_id": "600000.SSE"},
        headers={"Idempotency-Key": "data-import-akshare-0001"},
    )

    assert blocked.status_code == 403
    assert akshare.status_code == 403


def test_catalog_and_bar_preview_only_expose_published_snapshots(tmp_path: Path) -> None:
    client, state = _client(tmp_path)
    snapshot_id = _publish_sample(state)

    datasets = client.get("/v1/data/datasets")
    snapshots = client.get("/v1/data/datasets/cn-equity-600000-sse-1d-none/snapshots")
    detail = client.get(f"/v1/data/snapshots/{snapshot_id}")
    bars = client.get(f"/v1/data/snapshots/{snapshot_id}/bars", params={"limit": 10})

    assert datasets.status_code == 200
    assert datasets.json()[0]["latest_snapshot_id"] == snapshot_id
    assert snapshots.json()[0]["status"] == "PUBLISHED"
    assert detail.json()["snapshot_id"] == snapshot_id
    assert bars.json()[0]["instrument_id"] == "600000.SSE"
    assert set(bars.json()[0]) == {
        "instrument_id",
        "event_time",
        "available_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }


def test_data_routes_require_authentication_and_return_404(tmp_path: Path) -> None:
    state = _state(tmp_path)
    anonymous = TestClient(create_app(state))
    authenticated = TestClient(create_app(state))
    authenticated.headers.update({"Authorization": f"Bearer {TOKEN}"})

    assert anonymous.get("/v1/data/datasets").status_code == 401
    assert authenticated.get("/v1/data/datasets/missing/snapshots").status_code == 404
    assert authenticated.get("/v1/data/snapshots/missing").status_code == 404

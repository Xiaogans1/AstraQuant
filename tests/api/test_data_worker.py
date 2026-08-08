from __future__ import annotations

from pathlib import Path
from typing import Any

from astraquant_api.data_repository import DataCatalogRepository, SnapshotStatus
from astraquant_api.data_worker import run_data_import_worker
from astraquant_api.database import create_database, migrate_database
from astraquant_api.worker import WorkerMessage, WorkerMessageKind


class RecordingQueue:
    def __init__(self, cancel_on_step: str | None = None) -> None:
        self.messages: list[WorkerMessage] = []
        self.cancel_on_step = cancel_on_step
        self.cancel: ToggleCancel | None = None

    def put(self, message: WorkerMessage) -> None:
        self.messages.append(message)
        if message.current_step == self.cancel_on_step and self.cancel is not None:
            self.cancel.value = True


class ToggleCancel:
    def __init__(self, value: bool = False) -> None:
        self.value = value

    def is_set(self) -> bool:
        return self.value


def _request() -> dict[str, Any]:
    return {
        "provider": "fixture",
        "instrument_id": "600000.SSE",
        "frequency": "1d",
        "start": "2026-07-20",
        "end": "2026-07-24",
        "adjustment": "none",
    }


def _catalog(state_dir: Path) -> DataCatalogRepository:
    database_path = state_dir / "state" / "astraquant.sqlite3"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{database_path}"
    migrate_database(database_url)
    return DataCatalogRepository(create_database(database_url))


def test_fixture_worker_publishes_an_offline_snapshot(tmp_path: Path) -> None:
    _catalog(tmp_path)
    queue = RecordingQueue()
    cancel = ToggleCancel()

    run_data_import_worker("task-1", queue, cancel, _request(), str(tmp_path))

    terminal = queue.messages[-1]
    assert terminal.kind is WorkerMessageKind.SUCCEEDED
    assert terminal.payload is not None
    assert terminal.payload["row_count"] == 5
    record = _catalog(tmp_path).get_snapshot(str(terminal.payload["snapshot_id"]))
    assert record is not None
    assert record.status is SnapshotStatus.PUBLISHED
    assert Path(record.manifest_path).is_file()


def test_cancel_before_staging_leaves_no_manifest_or_catalog_row(tmp_path: Path) -> None:
    _catalog(tmp_path)
    queue = RecordingQueue()

    run_data_import_worker(
        "task-2",
        queue,
        ToggleCancel(value=True),
        _request(),
        str(tmp_path),
    )

    assert queue.messages[-1].kind is WorkerMessageKind.CANCELED
    assert list((tmp_path / "data").rglob("manifest.json")) == []
    assert _catalog(tmp_path).list_datasets() == []


def test_interruption_after_catalog_staging_is_hidden_then_recovered(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path)
    queue = RecordingQueue(cancel_on_step="publish_files")
    cancel = ToggleCancel()
    queue.cancel = cancel

    run_data_import_worker("task-3", queue, cancel, _request(), str(tmp_path))

    assert queue.messages[-1].kind is WorkerMessageKind.CANCELED
    assert catalog.list_datasets() == []
    staged = catalog.list_staged_snapshots()
    assert len(staged) == 1
    assert catalog.reconcile_staged() == 1
    assert len(catalog.list_datasets()) == 1

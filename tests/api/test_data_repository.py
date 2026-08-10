from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.data.factories import make_bar

from astraquant_api.data_repository import DataCatalogRepository, SnapshotStatus
from astraquant_api.data_worker import run_data_import_worker
from astraquant_api.database import create_database, migrate_database
from astraquant_api.repository import (
    TaskRepository,
    WorkerResultConflictError,
    WorkerResultValidationError,
)
from astraquant_api.task_model import TaskRecord, TaskStatus, transition_task
from astraquant_api.worker import DataImportResult, WorkerMessage, WorkerMessageKind
from astraquant_data.parquet_store import ParquetSnapshotStore, PublishedSnapshot
from astraquant_domain import FixedClock


def build_repository(tmp_path: Path) -> DataCatalogRepository:
    database_url = f"sqlite:///{tmp_path / 'state.sqlite3'}"
    migrate_database(database_url)
    return DataCatalogRepository(create_database(database_url))


def publish_fixture(tmp_path: Path) -> PublishedSnapshot:
    return ParquetSnapshotStore(
        tmp_path / "market-data",
        clock=FixedClock(datetime(2026, 7, 28, tzinfo=UTC)),
    ).publish_bars(
        dataset_id="cn-equity-daily",
        bars=[make_bar()],
        provider={"id": "fixture", "interface": "synthetic_csv", "version": "1"},
        calendar_version="fixture-calendar-v1",
        availability_policy="estimated_session_close_plus_1m",
    )


def test_staged_snapshot_is_hidden_until_marked_published(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    published = publish_fixture(tmp_path)

    repository.stage_snapshot(
        published,
        name="A 股日线样例",
        asset_class="equity",
        frequency="1d",
    )

    staged = repository.get_snapshot(published.snapshot_id)
    assert staged is not None
    assert staged.status is SnapshotStatus.STAGED
    assert repository.list_snapshots("cn-equity-daily") == []

    assert repository.mark_published(published.snapshot_id)
    assert repository.mark_published(published.snapshot_id)
    visible = repository.list_snapshots("cn-equity-daily")
    assert len(visible) == 1
    assert visible[0].status is SnapshotStatus.PUBLISHED
    assert len(repository.list_quality_issues(published.snapshot_id)) == 1


def test_catalog_staging_is_idempotent_by_snapshot_id(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    published = publish_fixture(tmp_path)

    for _ in range(2):
        repository.stage_snapshot(
            published,
            name="A 股日线样例",
            asset_class="equity",
            frequency="1d",
        )

    assert len(repository.list_quality_issues(published.snapshot_id)) == 1


def test_new_v1_snapshot_is_explicitly_legacy(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    published = publish_fixture(tmp_path)

    repository.stage_snapshot(
        published,
        name="A 股日线样例",
        asset_class="equity",
        frequency="1d",
    )

    record = repository.get_snapshot(published.snapshot_id)
    assert record is not None
    assert record.semantic_class == "LEGACY_SEMANTICS"
    assert record.evidence_class == "LEGACY_UNVERIFIED"
    assert record.run_class == "EXPLORATORY"
    assert record.manifest_schema == "1"
    assert record.content_digest is None


class _Queue:
    def __init__(self) -> None:
        self.messages: list[WorkerMessage] = []

    def put(self, message: WorkerMessage) -> None:
        self.messages.append(message)


class _NotCanceled:
    def is_set(self) -> bool:
        return False


def _worker_result(tmp_path: Path) -> DataImportResult:
    queue = _Queue()
    run_data_import_worker(
        "task-worker",
        queue,
        _NotCanceled(),
        {
            "provider": "fixture",
            "instrument_id": "600000.SSE",
            "frequency": "1d",
            "start": "2026-07-20",
            "end": "2026-07-24",
            "adjustment": "none",
        },
        str(tmp_path / "data"),
        clock=FixedClock(datetime(2026, 8, 10, 8, 30, tzinfo=UTC)),
    )
    terminal = queue.messages[-1]
    assert terminal.kind is WorkerMessageKind.SUCCEEDED
    assert isinstance(terminal.payload, DataImportResult)
    return terminal.payload


def _running_import(
    tmp_path: Path,
) -> tuple[TaskRepository, DataCatalogRepository, TaskRecord]:
    database_url = f"sqlite:///{tmp_path / 'state.sqlite3'}"
    migrate_database(database_url)
    engine = create_database(database_url)
    tasks = TaskRepository(engine, legacy_data_root=tmp_path / "data")
    catalog = DataCatalogRepository(engine)
    task = TaskRecord.create("data.import", "data-import-ingestion")
    tasks.create(task, event_type="task.created")
    running = task.evolve(
        status=transition_task(task.status, TaskStatus.RUNNING),
        current_step="started",
        started_at=datetime(2026, 8, 10, 8, 31, tzinfo=UTC),
    )
    assert tasks.update(running, expected_revision=task.revision, event_type="task.started")
    return tasks, catalog, running


def test_api_ingests_worker_result_and_task_in_one_transaction(tmp_path: Path) -> None:
    result = _worker_result(tmp_path)
    tasks, catalog, running = _running_import(tmp_path)

    completed = tasks.complete_data_import(running, result)

    stored = tasks.get(running.task_id)
    snapshot = catalog.get_snapshot(result.snapshot_id)
    assert completed.status is TaskStatus.SUCCEEDED
    assert stored == completed
    assert stored is not None
    assert stored.result == {
        "dataset_id": result.dataset_id,
        "snapshot_id": result.snapshot_id,
        "row_count": result.row_count,
        "quality": "PUBLISHED",
        "semantic_class": "LEGACY_SEMANTICS",
        "evidence_class": "LEGACY_UNVERIFIED",
        "run_class": "EXPLORATORY",
        "observed_received_time": result.observed_received_time.isoformat(),
    }
    assert snapshot is not None
    assert snapshot.status is SnapshotStatus.PUBLISHED
    assert tasks.list_events(running.task_id)[-1].event_type == "task.succeeded"


@pytest.mark.parametrize(
    "mutation",
    [
        {"manifest_digest": "sha256:" + "0" * 64},
        {"snapshot_id": "0" * 64},
        {"semantic_class": "FORMAL_SEMANTICS"},
        {"evidence_class": "REAL_API_MARKET"},
        {"run_class": "FORMAL"},
    ],
)
def test_api_rejects_tampered_worker_identity_without_catalog_state(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    result = replace(_worker_result(tmp_path), **mutation)  # type: ignore[arg-type]
    tasks, catalog, running = _running_import(tmp_path)

    with pytest.raises(WorkerResultValidationError):
        tasks.complete_data_import(running, result)

    assert catalog.list_datasets() == []
    assert tasks.get(running.task_id) == running


def test_api_rejects_manifest_escape_and_parquet_tamper(tmp_path: Path) -> None:
    result = _worker_result(tmp_path)
    tasks, catalog, running = _running_import(tmp_path)
    escaped = replace(result, manifest_path=str(tmp_path / "outside" / "manifest.json"))

    with pytest.raises(WorkerResultValidationError, match="legacy data root"):
        tasks.complete_data_import(running, escaped)

    parquet = next((Path(result.manifest_path).parent).rglob("*.parquet"))
    with parquet.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(WorkerResultValidationError, match="file digest"):
        tasks.complete_data_import(running, result)
    assert catalog.list_datasets() == []
    assert tasks.get(running.task_id) == running


def test_task_revision_conflict_rolls_back_catalog_insert(tmp_path: Path) -> None:
    result = _worker_result(tmp_path)
    tasks, catalog, running = _running_import(tmp_path)
    advanced = running.evolve(progress=50, current_step="advanced")
    assert tasks.update(
        advanced,
        expected_revision=running.revision,
        event_type="task.progress",
    )

    with pytest.raises(WorkerResultConflictError):
        tasks.complete_data_import(running, result)

    assert catalog.list_datasets() == []
    assert tasks.get(running.task_id) == advanced

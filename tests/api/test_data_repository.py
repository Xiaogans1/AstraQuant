from datetime import UTC, datetime
from pathlib import Path

from tests.data.factories import make_bar

from astraquant_api.data_repository import DataCatalogRepository, SnapshotStatus
from astraquant_api.database import create_database, migrate_database
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

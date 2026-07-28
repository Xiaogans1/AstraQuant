import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from astraquant_data.parquet_store import ParquetSnapshotStore, SnapshotRejected
from astraquant_domain import FixedClock

from .factories import make_bar

PROVIDER = {
    "id": "fixture",
    "interface": "synthetic_csv",
    "version": "1",
}


def test_publish_is_immutable_partitioned_and_reproducible(tmp_path: Path) -> None:
    clock = FixedClock(datetime(2026, 7, 28, tzinfo=UTC))
    store = ParquetSnapshotStore(tmp_path, clock=clock)

    first = store.publish_bars(
        dataset_id="cn-equity-daily",
        bars=[make_bar(availability_estimated=False)],
        provider=PROVIDER,
        calendar_version="fixture-calendar-v1",
        availability_policy="fixture_known_at_close_plus_1m",
    )
    second = store.publish_bars(
        dataset_id="cn-equity-daily",
        bars=[make_bar(availability_estimated=False)],
        provider=PROVIDER,
        calendar_version="fixture-calendar-v1",
        availability_policy="fixture_known_at_close_plus_1m",
    )

    assert second.snapshot_id == first.snapshot_id
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["snapshot_id"] == first.snapshot_id
    assert manifest["row_count"] == 1
    assert manifest["files"][0]["path"].startswith(
        "market=cn/asset_class=equity/frequency=1d/trading_date=2026-07-24/"
    )
    assert (first.snapshot_path / manifest["files"][0]["path"]).is_file()
    assert not any((tmp_path / ".staging").iterdir())


def test_rejected_snapshot_leaves_no_visible_manifest(tmp_path: Path) -> None:
    store = ParquetSnapshotStore(
        tmp_path,
        clock=FixedClock(datetime(2026, 7, 28, tzinfo=UTC)),
    )
    duplicate = make_bar(symbol="RB2610.SHFE", availability_estimated=False)

    with pytest.raises(SnapshotRejected):
        store.publish_bars(
            dataset_id="cn-futures-daily",
            bars=[duplicate, duplicate],
            provider=PROVIDER,
            calendar_version="fixture-calendar-v1",
            availability_policy="fixture_known_at_close_plus_1m",
        )

    assert list(tmp_path.rglob("manifest.json")) == []
    assert not any((tmp_path / ".staging").iterdir())


def test_dataset_id_cannot_escape_the_data_root(tmp_path: Path) -> None:
    store = ParquetSnapshotStore(
        tmp_path,
        clock=FixedClock(datetime(2026, 7, 28, tzinfo=UTC)),
    )

    with pytest.raises(ValueError, match="dataset_id"):
        store.publish_bars(
            dataset_id="../escape",
            bars=[make_bar()],
            provider=PROVIDER,
            calendar_version="fixture-calendar-v1",
            availability_policy="estimated",
        )

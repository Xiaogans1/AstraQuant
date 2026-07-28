from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from astraquant_data.parquet_store import (
    ParquetSnapshotStore,
    PublishedSnapshot,
)
from astraquant_data.query import MarketDataQuery
from astraquant_domain import Bar

from .factories import make_bar


def _publish(tmp_path: Path, bars: Sequence[Bar]) -> PublishedSnapshot:
    return ParquetSnapshotStore(tmp_path).publish_bars(
        dataset_id="revision-fixture",
        bars=bars,
        provider={"id": "fixture", "interface": "memory", "version": "1"},
        calendar_version="fixture-v1",
        availability_policy="fixture",
    )


def test_as_of_query_excludes_rows_not_yet_available(tmp_path: Path) -> None:
    cutoff = datetime(2026, 7, 24, 7, 1, tzinfo=UTC)
    visible = make_bar(symbol="600000.SSE", day=24, available_time=cutoff)
    revised = make_bar(
        symbol="600000.SSE",
        day=24,
        close="10.80",
        available_time=cutoff + timedelta(days=1),
    )
    snapshot = _publish(tmp_path, [visible, revised])
    query = MarketDataQuery.from_manifest(
        data_root=tmp_path,
        manifest_path=snapshot.manifest_path,
    )

    result = query.bars_as_of(
        instrument_ids=["600000.SSE"],
        decision_time=cutoff,
    )

    assert len(result) == 1
    assert str(result[0].close) == "10.50000000"


def test_as_of_query_selects_latest_visible_revision(tmp_path: Path) -> None:
    first_available = datetime(2026, 7, 24, 7, 1, tzinfo=UTC)
    snapshot = _publish(
        tmp_path,
        [
            make_bar(available_time=first_available),
            make_bar(close="10.80", available_time=first_available + timedelta(minutes=1)),
        ],
    )
    query = MarketDataQuery.from_manifest(
        data_root=tmp_path,
        manifest_path=snapshot.manifest_path,
    )

    result = query.bars_as_of(
        instrument_ids=["600000.SSE"],
        decision_time=first_available + timedelta(minutes=1),
    )

    assert [str(bar.close) for bar in result] == ["10.80000000"]


def test_range_query_filters_instruments_and_event_time(tmp_path: Path) -> None:
    snapshot = _publish(
        tmp_path,
        [
            make_bar(symbol="600000.SSE", day=23),
            make_bar(symbol="600000.SSE", day=24),
            make_bar(symbol="000001.SZSE", day=24),
        ],
    )
    query = MarketDataQuery.from_manifest(
        data_root=tmp_path,
        manifest_path=snapshot.manifest_path,
    )

    result = query.bars_between(
        instrument_ids=["600000.SSE"],
        start=datetime(2026, 7, 24, 0, 0, tzinfo=UTC),
        end=datetime(2026, 7, 24, 23, 59, tzinfo=UTC),
    )

    assert [(str(bar.instrument_id), bar.trading_date.day) for bar in result] == [
        ("600000.SSE", 24)
    ]


@pytest.mark.parametrize(
    ("instrument_ids", "start", "end", "match"),
    [
        (
            [],
            datetime(2026, 7, 24, tzinfo=UTC),
            datetime(2026, 7, 25, tzinfo=UTC),
            "instrument_ids",
        ),
        (
            ["600000.SSE"],
            datetime(2026, 7, 24),
            datetime(2026, 7, 25, tzinfo=UTC),
            "timezone-aware",
        ),
        (
            ["600000.SSE"],
            datetime(2026, 7, 25, tzinfo=UTC),
            datetime(2026, 7, 24, tzinfo=UTC),
            "start",
        ),
    ],
)
def test_range_query_rejects_invalid_boundaries(
    tmp_path: Path,
    instrument_ids: list[str],
    start: datetime,
    end: datetime,
    match: str,
) -> None:
    snapshot = _publish(tmp_path, [make_bar()])
    query = MarketDataQuery.from_manifest(
        data_root=tmp_path,
        manifest_path=snapshot.manifest_path,
    )

    with pytest.raises(ValueError, match=match):
        query.bars_between(instrument_ids=instrument_ids, start=start, end=end)


def test_manifest_must_be_inside_data_root(tmp_path: Path) -> None:
    outside_root = tmp_path / "outside"
    snapshot = _publish(outside_root, [make_bar()])

    with pytest.raises(ValueError, match="data root"):
        MarketDataQuery.from_manifest(
            data_root=tmp_path / "approved",
            manifest_path=snapshot.manifest_path,
        )

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_data.research_store import load_dataset_bars
from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId
from tools.research.build_training_set import build_features_json


def _publish_snapshot(data_root: Path, instrument: str = "159516.SZSE") -> str:
    store = ParquetSnapshotStore(data_root)
    instrument_id = InstrumentId.parse(instrument)
    start = datetime(2026, 8, 6, 1, 30, tzinfo=UTC)
    bars: list[Bar] = []
    for index in range(60):
        bars.append(
            Bar(
                instrument_id=instrument_id,
                frequency=BarFrequency.MINUTE,
                trading_date=start.date(),
                event_time=start + timedelta(minutes=index),
                available_time=start + timedelta(minutes=index + 1),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10"),
                volume=Decimal("100"),
                turnover=Decimal("1000"),
                open_interest=None,
                settlement=None,
                adjustment=Adjustment.NONE,
                availability_estimated=False,
            )
        )
    dataset_id = f"cn-equity-{instrument.lower().replace('.', '-')}-1m-none"
    store.publish_bars(
        dataset_id=dataset_id,
        bars=bars,
        provider={"id": "eastmoney", "interface": "bridge", "version": "1"},
        calendar_version="eastmoney",
        availability_policy="bar_end",
    )
    return dataset_id


def test_load_market_bars_reads_newest_snapshot(tmp_path: Path) -> None:
    dataset_id = _publish_snapshot(tmp_path / "data")

    bars, instrument_id = load_dataset_bars(tmp_path / "data", dataset_id)

    assert len(bars) == 60
    assert instrument_id == "159516.SZSE"
    assert bars[0].timestamp == datetime(2026, 8, 6, 1, 30, tzinfo=UTC)


def test_build_features_json_produces_labeled_rows(tmp_path: Path) -> None:
    dataset_id = _publish_snapshot(tmp_path / "data")

    payload = build_features_json(
        tmp_path / "data",
        dataset_id,
        horizon=5,
        threshold=Decimal("0.005"),
    )

    assert payload["instrument_id"] == "159516.SZSE"
    assert payload["row_count"] == 60 - 30 - 5
    assert payload["date_range"] == "2026-08-06..2026-08-06"
    rows = payload["rows"]
    assert isinstance(rows, list)
    for row in rows:
        assert row["label"] == 0
        assert "future_return" in row
        assert "return_5" in row

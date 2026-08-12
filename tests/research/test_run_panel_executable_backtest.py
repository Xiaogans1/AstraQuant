from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId
from tools.research.run_panel_executable_backtest import main


def _publish(data_root: Path, instrument: str, *, provider: str = "eastmoney") -> str:
    instrument_id = InstrumentId.parse(instrument)
    start = datetime(2026, 8, 3, 1, 30, tzinfo=UTC)
    bars = [
        Bar(
            instrument_id=instrument_id,
            frequency=BarFrequency.MINUTE,
            trading_date=start.date(),
            event_time=start + timedelta(minutes=index),
            available_time=start + timedelta(minutes=index + 1),
            open=Decimal("10") + Decimal(index % 7) / 100,
            high=Decimal("10.2") + Decimal(index % 7) / 100,
            low=Decimal("9.8") + Decimal(index % 7) / 100,
            close=Decimal("10.1") + Decimal(index % 7) / 100,
            volume=Decimal("100000"),
            turnover=Decimal("1000000"),
            open_interest=None,
            settlement=None,
            adjustment=Adjustment.NONE,
            availability_estimated=False,
        )
        for index in range(90)
    ]
    dataset_id = f"cn-equity-{instrument.lower().replace('.', '-')}-1m-none"
    ParquetSnapshotStore(data_root).publish_bars(
        dataset_id=dataset_id,
        bars=bars,
        provider={"id": provider, "interface": "test", "version": "1"},
        calendar_version="eastmoney",
        availability_policy="bar_end",
    )
    return dataset_id


def test_cli_runs_arbitrary_eastmoney_datasets_repeatably(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    datasets = [
        _publish(data_root, "159516.SZSE"),
        _publish(data_root, "512480.SSE"),
    ]
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    common = [
        *datasets,
        "--data-root",
        str(data_root),
        "--minimum-train-timestamps",
        "30",
        "--test-timestamp-count",
        "5",
        "--fold-count",
        "2",
        "--holding-bars",
        "2",
    ]

    assert main([*common, "--output", str(first)]) == 0
    assert main([*common, "--output", str(second)]) == 0

    assert first.read_bytes() == second.read_bytes()
    report = json.loads(first.read_text(encoding="utf-8"))
    assert report["schema_version"] == "astraquant.multi-etf-panel-executable/v1"
    assert len(report["sources"]) == 2
    assert {item["provider_id"] for item in report["sources"]} == {"eastmoney"}
    assert set(report["models"]) == {"NO_SKILL", "LOGISTIC_REGRESSION", "LIGHTGBM"}
    assert {item["evidence_status"] for item in report["models"].values()} == {
        "INSUFFICIENT_EVIDENCE"
    }
    assert len({item["test_rows"] for item in report["models"].values()}) == 1
    for model in report["models"].values():
        assert [item["fold_id"] for item in model["folds"]] == ["fold-01", "fold-02"]
        assert all(item["test_start"].endswith("+00:00") for item in model["folds"])
        assert all(item["test_start"] <= item["test_end"] for item in model["folds"])
        assert model["positive_folds"] == sum(item["net_return"] > 0 for item in model["folds"])


def test_cli_rejects_non_eastmoney_dataset(tmp_path: Path) -> None:
    dataset = _publish(tmp_path / "data", "159516.SZSE", provider="fixture")
    output = tmp_path / "report.json"

    assert main([dataset, "--data-root", str(tmp_path / "data"), "--output", str(output)]) == 1
    assert not output.exists()

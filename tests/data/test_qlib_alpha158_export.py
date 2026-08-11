from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from astraquant_data.exports.qlib_alpha158 import (
    ALPHA158_CONFIG_DIGEST,
    export_qlib_alpha158_request,
)
from astraquant_data.market_bars import MarketBar
from astraquant_quant.baseline_matrix import expanding_walk_forward
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS


def _bars(count: int = 100) -> list[MarketBar]:
    start = datetime(2026, 8, 3, 1, 30, tzinfo=UTC)
    return [
        MarketBar(
            timestamp=start + timedelta(minutes=index),
            open=Decimal("10") + Decimal(index) / 100,
            high=Decimal("10.1") + Decimal(index) / 100,
            low=Decimal("9.9") + Decimal(index) / 100,
            close=Decimal("10.05") + Decimal(index) / 100,
            volume=Decimal(100 + index),
            turnover=(Decimal("10.02") + Decimal(index) / 100) * Decimal(100 + index),
        )
        for index in range(count)
    ]


def _rows(count: int = 60) -> list[dict[str, float | int]]:
    return [
        {
            **{
                name: float(index + position) for position, name in enumerate(MODEL_FEATURE_COLUMNS)
            },
            "label": index % 2,
            "future_return": 0.01 if index % 2 else -0.01,
        }
        for index in range(count)
    ]


def _export(root: Path, **changes: object):  # type: ignore[no-untyped-def]
    rows = _rows()
    values: dict[str, object] = {
        "output_root": root,
        "dataset_id": "cn-equity-159516-szse-1m-none",
        "source_snapshot_id": "a" * 64,
        "provider_id": "eastmoney",
        "rows": rows,
        "folds": expanding_walk_forward(rows, minimum_train_size=30, test_size=10, fold_count=2),
        "fee_rate": Decimal("0.00025"),
        "prediction_threshold": 0.5,
        "seed": 7,
        "raw_bars": _bars(),
        "row_bar_indices": list(range(30, 90)),
    }
    values.update(changes)
    return export_qlib_alpha158_request(**values)  # type: ignore[arg-type]


def test_alpha158_export_freezes_bars_mapping_and_official_config(tmp_path: Path) -> None:
    first = _export(tmp_path / "first")
    second = _export(tmp_path / "second")

    assert first.content_digest == second.content_digest
    assert first.bars_path.read_bytes() == second.bars_path.read_bytes()
    request = json.loads(first.request_path.read_text(encoding="utf-8"))
    assert request["schema_version"] == "astraquant.qlib-alpha158-request/v1"
    assert request["alpha158_config_digest"] == ALPHA158_CONFIG_DIGEST
    assert request["row_bar_indices"] == list(range(30, 90))
    assert request["bars_file"]["digest"].startswith("sha256:")
    table = pq.read_table(first.bars_path)
    assert table.column_names == [
        "bar_id",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
    ]
    assert table.column("vwap").to_pylist()[0] == pytest.approx(10.02)


def test_alpha158_export_identity_changes_when_one_raw_bar_changes(tmp_path: Path) -> None:
    baseline = _export(tmp_path / "baseline")
    bars = _bars()
    bars[50] = MarketBar(
        timestamp=bars[50].timestamp,
        open=bars[50].open,
        high=bars[50].high + Decimal("1"),
        low=bars[50].low,
        close=bars[50].close,
        volume=bars[50].volume,
        turnover=bars[50].turnover,
    )

    changed = _export(tmp_path / "changed", raw_bars=bars)

    assert changed.content_digest != baseline.content_digest


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        (list(range(30, 89)), "mapping length"),
        ([*range(30, 60), 59, *range(61, 90)], "strictly increasing"),
        ([*range(30, 89), 100], "out of range"),
    ],
)
def test_alpha158_export_rejects_invalid_row_bar_mapping(
    tmp_path: Path, mapping: list[int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _export(tmp_path / "invalid", row_bar_indices=mapping)

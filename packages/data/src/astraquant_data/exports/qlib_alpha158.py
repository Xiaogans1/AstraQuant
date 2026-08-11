"""Frozen raw-bar export for Qlib's official Alpha158 expression engine."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.exports.qlib import (
    _DATASET_PATTERN,
    QLIB_FEATURE_COLUMNS,
    QLIB_UPSTREAM_COMMIT,
    FoldLike,
    _file_digest,
    _object_digest,
    _rows_table,
    _validate_folds,
    _validate_rows,
    _validate_snapshot,
)
from astraquant_data.market_bars import MarketBar

QLIB_ALPHA158_SCHEMA = "astraquant.qlib-alpha158-request/v1"
ALPHA158_CONFIG_DIGEST = "sha256:e645c1f75957e9a564fc9b0b8da232b9aa6fd887f673c92addc8a0276f6f5644"


@dataclass(frozen=True, slots=True)
class QlibAlpha158Export:
    content_digest: str
    request_path: Path
    rows_path: Path
    bars_path: Path


def export_qlib_alpha158_request(
    *,
    output_root: Path,
    dataset_id: str,
    source_snapshot_id: str,
    provider_id: str,
    rows: Sequence[dict[str, float | int]],
    folds: Sequence[FoldLike],
    fee_rate: Decimal,
    prediction_threshold: float,
    seed: int,
    raw_bars: Sequence[MarketBar],
    row_bar_indices: Sequence[int],
) -> QlibAlpha158Export:
    if provider_id != "eastmoney":
        raise ValueError("Alpha158 research input must come from Eastmoney")
    if not _DATASET_PATTERN.fullmatch(dataset_id):
        raise ValueError("invalid dataset_id")
    _validate_snapshot(source_snapshot_id)
    exact_rows = tuple(rows)
    _validate_rows(exact_rows)
    fold_values = _validate_folds(tuple(folds), row_count=len(exact_rows))
    exact_bars = tuple(raw_bars)
    _validate_bars(exact_bars)
    exact_mapping = tuple(row_bar_indices)
    _validate_mapping(exact_mapping, row_count=len(exact_rows), bar_count=len(exact_bars))
    if fee_rate < 0:
        raise ValueError("fee_rate must not be negative")
    if not 0 < prediction_threshold < 1:
        raise ValueError("prediction_threshold must be between zero and one")

    root = output_root.resolve()
    if root.exists():
        raise ValueError("Alpha158 export output_root must not already exist")
    root.mkdir(parents=True)
    rows_path = root / "rows.parquet"
    bars_path = root / "bars.parquet"
    pq.write_table(_rows_table(exact_rows), rows_path, compression="zstd", version="2.6")
    pq.write_table(_bars_table(exact_bars), bars_path, compression="zstd", version="2.6")
    body: dict[str, object] = {
        "schema_version": QLIB_ALPHA158_SCHEMA,
        "upstream_commit": QLIB_UPSTREAM_COMMIT,
        "alpha158_config_digest": ALPHA158_CONFIG_DIGEST,
        "alpha158_feature_count": 158,
        "feature_set": "QLIB_ALPHA158",
        "provider_id": provider_id,
        "dataset_id": dataset_id,
        "source_snapshot_id": source_snapshot_id,
        "source_feature_columns": list(QLIB_FEATURE_COLUMNS),
        "row_count": len(exact_rows),
        "bar_count": len(exact_bars),
        "rows_file": {"path": "rows.parquet", "digest": _file_digest(rows_path)},
        "bars_file": {"path": "bars.parquet", "digest": _file_digest(bars_path)},
        "row_bar_indices": list(exact_mapping),
        "folds": fold_values,
        "fee_rate": str(fee_rate),
        "prediction_threshold": prediction_threshold,
        "seed": seed,
    }
    content_digest = _object_digest(body)
    request_path = root / "request.json"
    request_path.write_text(
        json.dumps(
            {"content_digest": content_digest, **body},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return QlibAlpha158Export(
        content_digest=content_digest,
        request_path=request_path,
        rows_path=rows_path,
        bars_path=bars_path,
    )


def _validate_bars(bars: tuple[MarketBar, ...]) -> None:
    if not bars:
        raise ValueError("Alpha158 raw bars must not be empty")
    timestamps = [bar.timestamp for bar in bars]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise ValueError("Alpha158 raw bars must be strictly time ordered")


def _validate_mapping(mapping: tuple[int, ...], *, row_count: int, bar_count: int) -> None:
    if len(mapping) != row_count:
        raise ValueError("row-bar mapping length must match rows")
    if any(isinstance(index, bool) or not isinstance(index, int) for index in mapping):
        raise ValueError("row-bar mapping must contain integer indices")
    if any(left >= right for left, right in pairwise(mapping)):
        raise ValueError("row-bar mapping must be strictly increasing")
    if not mapping or mapping[0] < 0 or mapping[-1] >= bar_count:
        raise ValueError("row-bar mapping index is out of range")


def _bars_table(bars: tuple[MarketBar, ...]) -> pa.Table:
    schema = pa.schema(
        [
            pa.field("bar_id", pa.int64(), nullable=False),
            pa.field("timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("open", pa.float64(), nullable=False),
            pa.field("high", pa.float64(), nullable=False),
            pa.field("low", pa.float64(), nullable=False),
            pa.field("close", pa.float64(), nullable=False),
            pa.field("volume", pa.float64(), nullable=False),
            pa.field("vwap", pa.float64(), nullable=False),
        ],
        metadata={b"schema_version": QLIB_ALPHA158_SCHEMA.encode("ascii")},
    )
    return pa.Table.from_pylist(
        [
            {
                "bar_id": bar_id,
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
                "vwap": float(bar.close if bar.volume == 0 else bar.turnover / bar.volume),
            }
            for bar_id, bar in enumerate(bars)
        ],
        schema=schema,
    )

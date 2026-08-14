"""Sealed wide-market temporal panels for the Stage B v2 StockMixer challenger."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_domain.run_manifest import canonical_json_bytes

STAGE_B_V2_STOCKMIXER_PANEL_SCHEMA = "astraquant.stage-b-v2-stockmixer-panel/v1"
STOCKMIXER_TEMPORAL_COLUMNS = (
    "open_relative",
    "high_relative",
    "low_relative",
    "close_relative",
    "log_volume_change",
    "log_turnover_change",
)
_RAW_SCHEMA = "astraquant.stage-b-v2-request/v1"
_MATERIALIZATION_SCHEMA = "astraquant.stage-b-v2-materialization/v1"


@dataclass(frozen=True, slots=True)
class StageBV2StockMixerPanel:
    content_digest: str
    manifest_path: Path
    panel_path: Path
    rows_path: Path
    instrument_count: int
    panel_row_count: int
    row_count: int


def export_stage_b_v2_stockmixer_panel(
    *,
    raw_export_root: Path,
    materialization_root: Path,
    output_root: Path,
    lookback: int = 64,
) -> StageBV2StockMixerPanel:
    """Build one deterministic time-by-instrument panel from exact Stage B v2 inputs."""

    root = output_root.resolve()
    if root.exists():
        raise ValueError("StockMixer v2 output_root must not already exist")
    if lookback != 64:
        raise ValueError("StockMixer v2 lookback must equal the frozen value 64")
    raw_root = raw_export_root.resolve()
    materialized_root = materialization_root.resolve()
    raw = _load_manifest(raw_root / "request.json", _RAW_SCHEMA, "raw export")
    materialized = _load_manifest(
        materialized_root / "manifest.json",
        _MATERIALIZATION_SCHEMA,
        "materialization",
    )
    if materialized.get("request_content_digest") != raw["content_digest"]:
        raise ValueError("StockMixer v2 raw export and materialization identity mismatch")
    horizons = materialized.get("horizons")
    if (
        not isinstance(horizons, list)
        or not horizons
        or any(value not in {1, 5, 10} for value in horizons)
        or horizons != sorted(set(horizons))
    ):
        raise ValueError("StockMixer v2 materialization horizons schema mismatch")

    bars_path = _exact_file(raw_root, raw.get("bars_file"), "bars.parquet", "bars")
    context_path = _exact_file(
        raw_root,
        raw.get("context_file"),
        "context.parquet",
        "context",
    )
    _exact_file(raw_root, raw.get("labels_file"), "labels.parquet", "labels")
    matrix_path = _exact_file(
        materialized_root,
        materialized.get("matrix_file"),
        "matrix.parquet",
        "matrix",
    )
    context_columns = _context_columns(raw)
    rows = _materialized_rows(matrix_path, tuple(horizons))
    instrument_ids = tuple(sorted(set(cast(list[str], rows["instrument_id"].to_pylist()))))
    if not instrument_ids:
        raise ValueError("StockMixer v2 horizon contains no instruments")
    bars = _read_bars(bars_path, set(instrument_ids))
    context = _read_context(context_path, context_columns, set(instrument_ids))
    sessions = tuple(sorted({timestamp for values in bars.values() for timestamp in values}))
    if len(sessions) < lookback:
        raise ValueError("StockMixer v2 raw history is shorter than lookback")
    transforms = {
        instrument_id: _temporal_features(values)
        for instrument_id, values in bars.items()
    }

    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=root.parent,
        prefix=f".{root.name}-staging-",
        ignore_cleanup_errors=True,
    ) as staging_name:
        staging = Path(staging_name)
        panel_path = staging / "temporal-panel.parquet"
        panel_row_count = _write_panel(
            panel_path,
            sessions=sessions,
            instrument_ids=instrument_ids,
            bars=bars,
            transforms=transforms,
            context=context,
            context_columns=context_columns,
        )
        rows_path = staging / "rows.parquet"
        pq.write_table(rows, rows_path, compression="zstd", version="2.6")
        body: dict[str, object] = {
            "schema_version": STAGE_B_V2_STOCKMIXER_PANEL_SCHEMA,
            "source_raw_export_digest": raw["content_digest"],
            "source_materialization_digest": materialized["content_digest"],
            "horizons": horizons,
            "lookback": lookback,
            "price_transform": "PREVIOUS_CLOSE_RELATIVE_V1",
            "volume_transform": "LOG1P_DIFFERENCE_V1",
            "context_visibility": "DECISION_TIME_ONLY",
            "temporal_columns": list(STOCKMIXER_TEMPORAL_COLUMNS),
            "context_columns": list(context_columns),
            "instrument_count": len(instrument_ids),
            "session_count": len(sessions),
            "panel_row_count": panel_row_count,
            "row_count": rows.num_rows,
            "temporal_panel_file": {
                "path": "temporal-panel.parquet",
                "digest": _digest_file(panel_path),
                "row_count": panel_row_count,
            },
            "rows_file": {"path": "rows.parquet", "digest": _digest_file(rows_path)},
        }
        content_digest = _object_digest(body)
        (staging / "manifest.json").write_bytes(
            canonical_json_bytes({"content_digest": content_digest, **body}) + b"\n"
        )
        staging.replace(root)

    return StageBV2StockMixerPanel(
        content_digest=content_digest,
        manifest_path=root / "manifest.json",
        panel_path=root / "temporal-panel.parquet",
        rows_path=root / "rows.parquet",
        instrument_count=len(instrument_ids),
        panel_row_count=panel_row_count,
        row_count=rows.num_rows,
    )


def _load_manifest(path: Path, schema: str, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != schema:
        raise ValueError(f"StockMixer v2 {label} schema mismatch")
    body = {key: item for key, item in value.items() if key != "content_digest"}
    if value.get("content_digest") != _object_digest(body):
        raise ValueError(f"StockMixer v2 {label} digest mismatch")
    return value


def _exact_file(root: Path, value: object, expected: str, label: str) -> Path:
    if not isinstance(value, dict) or value.get("path") != expected:
        raise ValueError(f"StockMixer v2 {label} file schema mismatch")
    path = root / expected
    if not path.is_file() or value.get("digest") != _digest_file(path):
        raise ValueError(f"StockMixer v2 {label} digest mismatch")
    return path


def _context_columns(raw: dict[str, Any]) -> tuple[str, ...]:
    value = raw.get("context_feature_columns")
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("StockMixer v2 context columns schema mismatch")
    reserved = {
        "slot_time",
        "instrument_id",
        "event_time",
        "feature_mask",
        "context_mask",
        "presence_mask",
        "tradable_mask",
        *STOCKMIXER_TEMPORAL_COLUMNS,
    }
    if set(value) & reserved:
        raise ValueError("StockMixer v2 context columns collide with panel schema")
    return tuple(value)


def _materialized_rows(path: Path, horizons: tuple[int, ...]) -> pa.Table:
    required = (
        "row_id",
        "decision_time",
        "instrument_id",
        "horizon_sessions",
        "cross_sectional_rank",
        "training_eligible",
    )
    schema_names = pq.read_schema(path).names
    if any(name not in schema_names for name in required):
        raise ValueError("StockMixer v2 materialized rows schema mismatch")
    table = pq.read_table(path, columns=list(required))
    if not table.num_rows:
        raise ValueError("StockMixer v2 materialization has no rows")
    observed_horizons = tuple(
        sorted(set(cast(list[int], table["horizon_sessions"].to_pylist())))
    )
    if observed_horizons != horizons:
        raise ValueError("StockMixer v2 materialized horizon coverage mismatch")
    values = table.to_pylist()
    values.sort(key=lambda row: int(row["row_id"]))
    row_ids = [int(row["row_id"]) for row in values]
    if len(set(row_ids)) != len(row_ids):
        raise ValueError("StockMixer v2 materialized row identifiers are not unique")
    return pa.Table.from_pylist(values, schema=table.schema)


def _read_bars(
    path: Path,
    instruments: set[str],
) -> dict[str, dict[datetime, tuple[float, float, float, float, float, float]]]:
    required = (
        "timestamp",
        "instrument_id",
        "benchmark",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
    )
    table = pq.read_table(path, columns=list(required))
    result: dict[
        str,
        dict[datetime, tuple[float, float, float, float, float, float]],
    ] = {instrument_id: {} for instrument_id in instruments}
    for row in table.to_pylist():
        instrument_id = cast(str, row["instrument_id"])
        if instrument_id not in result or bool(row["benchmark"]):
            continue
        timestamp = cast(datetime, row["timestamp"])
        if timestamp in result[instrument_id]:
            raise ValueError("StockMixer v2 bars contain duplicate identities")
        values = tuple(
            float(row[name])
            for name in ("open", "high", "low", "close", "volume", "turnover")
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("StockMixer v2 bars contain non-finite values")
        if min(values[:4]) <= 0 or min(values[4:]) < 0:
            raise ValueError("StockMixer v2 bars contain invalid price or liquidity values")
        result[instrument_id][timestamp] = cast(
            tuple[float, float, float, float, float, float], values
        )
    if any(not values for values in result.values()):
        raise ValueError("StockMixer v2 bars do not cover every materialized instrument")
    return result


def _read_context(
    path: Path,
    columns: tuple[str, ...],
    instruments: set[str],
) -> dict[tuple[datetime, str], tuple[float, ...]]:
    table = pq.read_table(path, columns=["decision_time", "instrument_id", *columns])
    result: dict[tuple[datetime, str], tuple[float, ...]] = {}
    for row in table.to_pylist():
        instrument_id = cast(str, row["instrument_id"])
        if instrument_id not in instruments:
            continue
        identity = (cast(datetime, row["decision_time"]), instrument_id)
        if identity in result:
            raise ValueError("StockMixer v2 context contains duplicate identities")
        values = tuple(float(row[name]) for name in columns)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("StockMixer v2 context contains non-finite values")
        result[identity] = values
    if not result:
        raise ValueError("StockMixer v2 context has no matching rows")
    return result


def _temporal_features(
    bars: dict[datetime, tuple[float, float, float, float, float, float]],
) -> dict[datetime, tuple[float, float, float, float, float, float]]:
    result: dict[datetime, tuple[float, float, float, float, float, float]] = {}
    previous: tuple[float, float, float, float, float, float] | None = None
    for timestamp, current in sorted(bars.items()):
        if previous is not None:
            previous_close = previous[3]
            result[timestamp] = (
                current[0] / previous_close - 1.0,
                current[1] / previous_close - 1.0,
                current[2] / previous_close - 1.0,
                current[3] / previous_close - 1.0,
                math.log1p(current[4]) - math.log1p(previous[4]),
                math.log1p(current[5]) - math.log1p(previous[5]),
            )
        previous = current
    return result


def _write_panel(
    path: Path,
    *,
    sessions: tuple[datetime, ...],
    instrument_ids: tuple[str, ...],
    bars: dict[str, dict[datetime, tuple[float, float, float, float, float, float]]],
    transforms: dict[str, dict[datetime, tuple[float, float, float, float, float, float]]],
    context: dict[tuple[datetime, str], tuple[float, ...]],
    context_columns: tuple[str, ...],
) -> int:
    schema = _panel_schema(context_columns)
    writer = pq.ParquetWriter(path, schema, compression="zstd", version="2.6")
    try:
        for start in range(0, len(sessions), 32):
            rows: list[dict[str, object]] = []
            for timestamp in sessions[start : start + 32]:
                for instrument_id in instrument_ids:
                    identity = (timestamp, instrument_id)
                    temporal = transforms[instrument_id].get(timestamp)
                    context_values = context.get(identity)
                    bar = bars[instrument_id].get(timestamp)
                    feature_mask = temporal is not None
                    context_mask = context_values is not None
                    presence_mask = context_mask
                    tradable_mask = (
                        presence_mask and feature_mask and bar is not None and bar[4] > 0
                    )
                    rows.append(
                        {
                            "slot_time": timestamp,
                            "instrument_id": instrument_id,
                            "event_time": timestamp if feature_mask else None,
                            "feature_mask": feature_mask,
                            "context_mask": context_mask,
                            "presence_mask": presence_mask,
                            "tradable_mask": tradable_mask,
                            **{
                                name: value
                                for name, value in zip(
                                    STOCKMIXER_TEMPORAL_COLUMNS,
                                    temporal or (0.0,) * len(STOCKMIXER_TEMPORAL_COLUMNS),
                                    strict=True,
                                )
                            },
                            **{
                                name: value
                                for name, value in zip(
                                    context_columns,
                                    context_values or (0.0,) * len(context_columns),
                                    strict=True,
                                )
                            },
                        }
                    )
            writer.write_table(pa.Table.from_pylist(rows, schema=schema))
    finally:
        writer.close()
    return len(sessions) * len(instrument_ids)


def _panel_schema(context_columns: tuple[str, ...]) -> pa.Schema:
    return pa.schema(
        [
            pa.field("slot_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=True),
            pa.field("feature_mask", pa.bool_(), nullable=False),
            pa.field("context_mask", pa.bool_(), nullable=False),
            pa.field("presence_mask", pa.bool_(), nullable=False),
            pa.field("tradable_mask", pa.bool_(), nullable=False),
            *(pa.field(name, pa.float64(), nullable=False) for name in STOCKMIXER_TEMPORAL_COLUMNS),
            *(pa.field(name, pa.float64(), nullable=False) for name in context_columns),
        ],
        metadata={b"schema_version": STAGE_B_V2_STOCKMIXER_PANEL_SCHEMA.encode("ascii")},
    )


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _object_digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

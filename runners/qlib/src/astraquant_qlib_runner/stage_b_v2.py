"""Multi-instrument official Alpha158 materialization for Stage B v2."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import QLIB_UPSTREAM_COMMIT, _canonical_bytes, _digest
from .alpha158 import ALPHA158_CONFIG_DIGEST, compute_alpha158_features

REQUEST_SCHEMA = "astraquant.stage-b-v2-request/v1"
RESPONSE_SCHEMA = "astraquant.stage-b-v2-materialization/v1"
_RAW_COLUMNS = [
    "timestamp",
    "instrument_id",
    "benchmark",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
]
_LABEL_COLUMNS = [
    "decision_time",
    "instrument_id",
    "horizon_sessions",
    "entry_time",
    "exit_time",
    "raw_return",
    "benchmark_return",
    "market_excess_return",
    "cross_sectional_rank",
    "downside_risk",
    "training_eligible",
]


def run_stage_b_v2_request(request_path: Path, output_root: Path) -> dict[str, Any]:
    """Compute Alpha158 per instrument and atomically publish one joined matrix."""

    if output_root.exists():
        raise ValueError("Stage B v2 output_root must not already exist")
    request = _read_request(request_path)
    root = request_path.parent
    bars = _read_frame(root, request, "bars_file", "bars.parquet", "bars")
    context = _read_frame(root, request, "context_file", "context.parquet", "context")
    labels = _read_frame(root, request, "labels_file", "labels.parquet", "labels")
    context_columns = _string_list(request, "context_feature_columns")
    exact_bars = _validate_bars(bars, request)
    exact_context = _validate_context(context, context_columns, request)
    exact_labels = _validate_labels(labels, request)

    alpha_frames = []
    for instrument_id in sorted(exact_bars.loc[~exact_bars["benchmark"], "instrument_id"].unique()):
        instrument = exact_bars.loc[
            (exact_bars["instrument_id"] == instrument_id) & ~exact_bars["benchmark"]
        ].copy()
        values = instrument.set_index("timestamp")
        values["vwap"] = values["turnover"] / values["volume"].where(
            values["volume"] > 0,
            other=1.0,
        )
        raw = values.loc[:, ["open", "high", "low", "close", "volume", "vwap"]]
        alpha = compute_alpha158_features(raw).reset_index(names="decision_time")
        alpha.insert(1, "instrument_id", instrument_id)
        alpha_frames.append(alpha)
    if not alpha_frames:
        raise ValueError("Stage B v2 bars contain no instruments")
    alpha_frame = pd.concat(alpha_frames, ignore_index=True)
    alpha_columns = [
        str(column)
        for column in alpha_frame.columns
        if column not in {"decision_time", "instrument_id"}
    ]
    if len(alpha_columns) != 158:
        raise ValueError("Stage B v2 Alpha158 schema mismatch")
    features = exact_context.merge(
        alpha_frame,
        on=["decision_time", "instrument_id"],
        how="left",
        validate="one_to_one",
    )
    features.loc[:, alpha_columns] = features.loc[:, alpha_columns].replace(
        [float("inf"), float("-inf")],
        float("nan"),
    )
    alpha_missing_values = int(features[alpha_columns].isna().to_numpy().sum())
    matrix = exact_labels.merge(
        features,
        on=["decision_time", "instrument_id"],
        how="inner",
        validate="many_to_one",
    )
    matrix = matrix.sort_values(
        ["decision_time", "horizon_sessions", "instrument_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    if matrix.empty:
        raise ValueError("Stage B v2 materialized matrix has no aligned rows")
    matrix.insert(0, "row_id", range(len(matrix)))
    numeric_columns = [*context_columns, *_LABEL_COLUMNS[5:10]]
    if not matrix[numeric_columns].map(math.isfinite).to_numpy().all():
        raise ValueError("Stage B v2 matrix must contain finite values")

    with tempfile.TemporaryDirectory(
        dir=output_root.parent,
        prefix=f".{output_root.name}-staging-",
        ignore_cleanup_errors=True,
    ) as staging_name:
        staging = Path(staging_name)
        matrix_path = staging / "matrix.parquet"
        table = pa.Table.from_pandas(matrix, preserve_index=False)
        pq.write_table(table, matrix_path, compression="zstd", version="2.6")
        body: dict[str, Any] = {
            "schema_version": RESPONSE_SCHEMA,
            "request_content_digest": _text(request, "content_digest"),
            "upstream_commit": QLIB_UPSTREAM_COMMIT,
            "alpha158_config_digest": ALPHA158_CONFIG_DIGEST,
            "alpha158_feature_count": len(alpha_columns),
            "alpha158_missing_values": alpha_missing_values,
            "feature_columns": [*context_columns, *alpha_columns],
            "row_count": len(matrix),
            "instrument_count": int(matrix["instrument_id"].nunique()),
            "horizons": sorted(int(value) for value in matrix["horizon_sessions"].unique()),
            "matrix_file": {
                "path": "matrix.parquet",
                "digest": _digest(matrix_path.read_bytes()),
            },
        }
        content_digest = _digest(_canonical_bytes(body))
        response = {"content_digest": content_digest, **body}
        (staging / "manifest.json").write_bytes(_canonical_bytes(response) + b"\n")
        staging.replace(output_root)
    return response


def _read_request(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid Stage B v2 request JSON") from error
    if not isinstance(value, dict) or value.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("Stage B v2 request schema mismatch")
    body = {key: item for key, item in value.items() if key != "content_digest"}
    if _text(value, "content_digest") != _digest(_canonical_bytes(body)):
        raise ValueError("Stage B v2 request content digest mismatch")
    alpha = value.get("alpha158")
    if alpha != {
        "config_digest": ALPHA158_CONFIG_DIGEST,
        "feature_count": 158,
        "materializer": "PINNED_QLIB_RUNNER",
        "upstream_commit": QLIB_UPSTREAM_COMMIT,
    }:
        raise ValueError("Stage B v2 Alpha158 contract mismatch")
    return value


def _read_frame(
    root: Path,
    request: dict[str, Any],
    key: str,
    filename: str,
    label: str,
) -> pd.DataFrame:
    value = request.get(key)
    if not isinstance(value, dict) or value.get("path") != filename:
        raise ValueError(f"Stage B v2 {label} file schema mismatch")
    path = root / filename
    if not path.is_file() or _digest(path.read_bytes()) != value.get("digest"):
        raise ValueError(f"Stage B v2 {label} digest mismatch")
    return pq.read_table(path).to_pandas()


def _validate_bars(frame: pd.DataFrame, request: dict[str, Any]) -> pd.DataFrame:
    if list(frame.columns) != _RAW_COLUMNS or frame.empty:
        raise ValueError("Stage B v2 bars schema mismatch")
    if frame["instrument_id"].nunique() != _integer(request, "instrument_count") + 1:
        raise ValueError("Stage B v2 bar instrument coverage mismatch")
    if frame.duplicated(["timestamp", "instrument_id"]).any():
        raise ValueError("Stage B v2 bars contain duplicate identities")
    if frame["benchmark"].sum() != _integer(request, "session_count"):
        raise ValueError("Stage B v2 benchmark coverage mismatch")
    numeric = frame[["open", "high", "low", "close", "volume", "turnover"]]
    if not numeric.map(math.isfinite).to_numpy().all():
        raise ValueError("Stage B v2 bars must be finite")
    if (frame[["open", "high", "low", "close"]] <= 0).to_numpy().any():
        raise ValueError("Stage B v2 prices must be positive")
    return frame.sort_values(["timestamp", "instrument_id"], kind="mergesort")


def _validate_context(
    frame: pd.DataFrame,
    context_columns: list[str],
    request: dict[str, Any],
) -> pd.DataFrame:
    expected = ["decision_time", "instrument_id", *context_columns]
    if list(frame.columns) != expected or len(frame) != _integer(request, "context_row_count"):
        raise ValueError("Stage B v2 context schema mismatch")
    if frame.duplicated(["decision_time", "instrument_id"]).any():
        raise ValueError("Stage B v2 context identities must be unique")
    if not frame[context_columns].map(math.isfinite).to_numpy().all():
        raise ValueError("Stage B v2 context must be finite")
    return frame


def _validate_labels(frame: pd.DataFrame, request: dict[str, Any]) -> pd.DataFrame:
    if list(frame.columns) != _LABEL_COLUMNS or len(frame) != _integer(
        request,
        "label_row_count",
    ):
        raise ValueError("Stage B v2 labels schema mismatch")
    horizons = _integer_list(request, "horizons")
    if sorted(int(value) for value in frame["horizon_sessions"].unique()) != horizons:
        raise ValueError("Stage B v2 label horizons mismatch")
    if frame.duplicated(["decision_time", "horizon_sessions", "instrument_id"]).any():
        raise ValueError("Stage B v2 label identities must be unique")
    return frame


def _text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Stage B v2 {key} schema mismatch")
    return item


def _integer(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
        raise ValueError(f"Stage B v2 {key} schema mismatch")
    return item


def _string_list(value: dict[str, Any], key: str) -> list[str]:
    item = value.get(key)
    if not isinstance(item, list) or not item or any(
        not isinstance(entry, str) or not entry for entry in item
    ):
        raise ValueError(f"Stage B v2 {key} schema mismatch")
    return item


def _integer_list(value: dict[str, Any], key: str) -> list[int]:
    item = value.get(key)
    if not isinstance(item, list) or not item or any(
        isinstance(entry, bool) or not isinstance(entry, int) or entry <= 0 for entry in item
    ):
        raise ValueError(f"Stage B v2 {key} schema mismatch")
    return item

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from astraquant_qlib_runner.__main__ import run_cli_request
from astraquant_qlib_runner.alpha158 import ALPHA158_CONFIG_DIGEST
from astraquant_qlib_runner.stage_b_v2 import run_stage_b_v2_request

COMMIT = "79633dd9506ea689e5400dea0197717b5b3d74b7"


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write_request(root: Path) -> Path:
    root.mkdir()
    sessions = pd.date_range("2020-01-02 07:00", periods=100, freq="D", tz="UTC")
    bars = []
    for instrument_index, instrument_id in enumerate(("A.SSE", "B.SSE")):
        for index, timestamp in enumerate(sessions):
            close = (
                10.0
                + instrument_index * 20
                + index * 0.02
                + math.sin(index / (3 + instrument_index)) * 0.2
            )
            volume = 100000.0 + (index % 11) * 137 + instrument_index * 1000
            bars.append(
                {
                    "timestamp": timestamp,
                    "instrument_id": instrument_id,
                    "benchmark": False,
                    "open": close - 0.03,
                    "high": close + 0.12,
                    "low": close - 0.15,
                    "close": close,
                    "volume": volume,
                    "turnover": volume * (close - 0.01),
                }
            )
    for index, timestamp in enumerate(sessions):
        close = 100.0 + index * 0.01 + math.sin(index / 5) * 0.1
        bars.append(
            {
                "timestamp": timestamp,
                "instrument_id": "000985.CSI",
                "benchmark": True,
                "open": close - 0.03,
                "high": close + 0.12,
                "low": close - 0.15,
                "close": close,
                "volume": 1000000.0 + index,
                "turnover": (1000000.0 + index) * close,
            }
        )
    bars.sort(key=lambda row: (row["timestamp"], row["instrument_id"]))
    bars_path = root / "bars.parquet"
    pq.write_table(pa.Table.from_pylist(bars), bars_path)

    context = [
        {
            "decision_time": timestamp,
            "instrument_id": instrument_id,
            "market_breadth": 0.5 + instrument_index / 10,
            "relative_return_20": index / 1000,
        }
        for index, timestamp in enumerate(sessions[70:80], start=70)
        for instrument_index, instrument_id in enumerate(("A.SSE", "B.SSE"))
    ]
    context_path = root / "context.parquet"
    pq.write_table(pa.Table.from_pylist(context), context_path)

    labels = [
        {
            "decision_time": timestamp,
            "instrument_id": instrument_id,
            "horizon_sessions": horizon,
            "entry_time": timestamp + pd.Timedelta(days=1),
            "exit_time": timestamp + pd.Timedelta(days=1 + horizon),
            "raw_return": 0.01 * (1 if instrument_id == "A.SSE" else -1),
            "benchmark_return": 0.001,
            "market_excess_return": 0.009 * (1 if instrument_id == "A.SSE" else -1),
            "cross_sectional_rank": 1.0 if instrument_id == "A.SSE" else 0.0,
            "downside_risk": 0.02,
            "training_eligible": True,
        }
        for timestamp in sessions[70:80]
        for horizon in (1, 5, 10)
        for instrument_id in ("A.SSE", "B.SSE")
    ]
    labels_path = root / "labels.parquet"
    pq.write_table(pa.Table.from_pylist(labels), labels_path)
    body = {
        "schema_version": "astraquant.stage-b-v2-request/v1",
        "panel_content_digest": f"sha256:{'a' * 64}",
        "source_digest": f"sha256:{'b' * 64}",
        "universe_snapshot_digest": f"sha256:{'c' * 64}",
        "task_digest": f"sha256:{'d' * 64}",
        "horizons": [1, 5, 10],
        "context_feature_columns": ["market_breadth", "relative_return_20"],
        "alpha158": {
            "config_digest": ALPHA158_CONFIG_DIGEST,
            "feature_count": 158,
            "materializer": "PINNED_QLIB_RUNNER",
            "upstream_commit": COMMIT,
        },
        "bars_file": {"path": "bars.parquet", "digest": _digest(bars_path.read_bytes())},
        "context_file": {
            "path": "context.parquet",
            "digest": _digest(context_path.read_bytes()),
        },
        "labels_file": {
            "path": "labels.parquet",
            "digest": _digest(labels_path.read_bytes()),
        },
        "session_count": 100,
        "instrument_count": 2,
        "context_row_count": len(context),
        "label_row_count": len(labels),
    }
    request = root / "request.json"
    request.write_text(
        json.dumps(
            {"content_digest": _digest(_canonical(body)), **body},
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return request


def test_stage_b_v2_materializes_each_instrument_and_horizon_repeatably(
    tmp_path: Path,
) -> None:
    request = _write_request(tmp_path / "input")

    first = run_stage_b_v2_request(request, tmp_path / "first")
    second = run_stage_b_v2_request(request, tmp_path / "second")

    assert first == second
    assert (tmp_path / "first" / "manifest.json").read_bytes() == (
        tmp_path / "second" / "manifest.json"
    ).read_bytes()
    assert (tmp_path / "first" / "matrix.parquet").read_bytes() == (
        tmp_path / "second" / "matrix.parquet"
    ).read_bytes()
    matrix = pq.read_table(tmp_path / "first" / "matrix.parquet").to_pandas()
    assert len(matrix) == 60
    assert matrix["row_id"].tolist() == list(range(60))
    assert set(matrix["instrument_id"]) == {"A.SSE", "B.SSE"}
    assert set(matrix["horizon_sessions"]) == {1, 5, 10}
    assert first["alpha158_feature_count"] == 158
    assert len(first["feature_columns"]) == 160
    assert first["alpha158_missing_values"] > 0
    assert math.isfinite(matrix.loc[matrix["instrument_id"] == "A.SSE", "KMID"].iloc[0])


def test_stage_b_v2_cli_dispatch_and_tamper_gate(tmp_path: Path) -> None:
    request = _write_request(tmp_path / "input")

    response = run_cli_request(request, tmp_path / "output")

    assert response["schema_version"] == "astraquant.stage-b-v2-materialization/v1"
    with (request.parent / "context.parquet").open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(ValueError, match="context digest"):
        run_stage_b_v2_request(request, tmp_path / "tampered")

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from astraquant_data.exports.stage_b_v2_stockmixer import (
    export_stage_b_v2_stockmixer_panel,
)
from astraquant_domain.run_manifest import canonical_json_bytes


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _digest_file(path: Path) -> str:
    return _digest_bytes(path.read_bytes())


def _write_json(path: Path, body: dict[str, object]) -> None:
    value = {"content_digest": _digest_bytes(canonical_json_bytes(body)), **body}
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _sources(root: Path) -> tuple[Path, Path]:
    raw = root / "raw"
    materialization = root / "materialization"
    raw.mkdir(parents=True)
    materialization.mkdir()
    start = datetime(2020, 1, 2, 7, tzinfo=UTC)
    sessions = tuple(start + timedelta(days=index) for index in range(66))
    bars: list[dict[str, object]] = []
    context: list[dict[str, object]] = []
    labels: list[dict[str, object]] = []
    for session_index, timestamp in enumerate(sessions):
        for instrument_index, instrument_id in enumerate(("AAA.SSE", "BBB.SSE")):
            close = 10.0 + instrument_index + session_index * 0.1
            if not (instrument_id == "BBB.SSE" and session_index == 64):
                bars.append(
                    {
                        "timestamp": timestamp,
                        "instrument_id": instrument_id,
                        "benchmark": False,
                        "open": close - 0.05,
                        "high": close + 0.1,
                        "low": close - 0.1,
                        "close": close,
                        "volume": 1000.0 + session_index,
                        "turnover": 10000.0 + session_index * 10,
                    }
                )
            if session_index >= 63:
                context.append(
                    {
                        "decision_time": timestamp,
                        "instrument_id": instrument_id,
                        "market_return_1": 0.001 * session_index,
                        "volatility_20": 0.02 + instrument_index * 0.01,
                    }
                )
            if session_index >= 64:
                labels.append(
                    {
                        "decision_time": timestamp,
                        "instrument_id": instrument_id,
                        "horizon_sessions": 1,
                        "entry_time": timestamp + timedelta(days=1),
                        "exit_time": timestamp + timedelta(days=2),
                        "raw_return": 0.01,
                        "benchmark_return": 0.001,
                        "market_excess_return": 0.009,
                        "cross_sectional_rank": float(instrument_index),
                        "downside_risk": 0.0,
                        "training_eligible": True,
                    }
                )
    bars_path = raw / "bars.parquet"
    context_path = raw / "context.parquet"
    labels_path = raw / "labels.parquet"
    pq.write_table(pa.Table.from_pylist(bars), bars_path)
    pq.write_table(pa.Table.from_pylist(context), context_path)
    pq.write_table(pa.Table.from_pylist(labels), labels_path)
    raw_body: dict[str, object] = {
        "schema_version": "astraquant.stage-b-v2-request/v1",
        "panel_content_digest": "sha256:" + "1" * 64,
        "source_digest": "sha256:" + "2" * 64,
        "universe_snapshot_digest": "sha256:" + "3" * 64,
        "task_digest": "sha256:" + "4" * 64,
        "horizons": [1, 5, 10],
        "context_feature_columns": ["market_return_1", "volatility_20"],
        "alpha158": {
            "config_digest": "sha256:" + "5" * 64,
            "feature_count": 158,
            "materializer": "PINNED_QLIB_RUNNER",
            "upstream_commit": "79633dd9506ea689e5400dea0197717b5b3d74b7",
        },
        "bars_file": {"path": "bars.parquet", "digest": _digest_file(bars_path)},
        "context_file": {"path": "context.parquet", "digest": _digest_file(context_path)},
        "labels_file": {"path": "labels.parquet", "digest": _digest_file(labels_path)},
        "session_count": len(sessions),
        "instrument_count": 2,
        "context_row_count": len(context),
        "label_row_count": len(labels),
    }
    _write_json(raw / "request.json", raw_body)

    matrix_rows = [
        {
            "row_id": index,
            "decision_time": row["decision_time"],
            "instrument_id": row["instrument_id"],
            "horizon_sessions": 1,
            "cross_sectional_rank": row["cross_sectional_rank"],
            "training_eligible": True,
        }
        for index, row in enumerate(labels)
    ]
    matrix_path = materialization / "matrix.parquet"
    pq.write_table(pa.Table.from_pylist(matrix_rows), matrix_path)
    materialized_body: dict[str, object] = {
        "schema_version": "astraquant.stage-b-v2-materialization/v1",
        "request_content_digest": json.loads(
            (raw / "request.json").read_text(encoding="utf-8")
        )["content_digest"],
        "upstream_commit": "79633dd9506ea689e5400dea0197717b5b3d74b7",
        "alpha158_config_digest": "sha256:" + "5" * 64,
        "alpha158_feature_count": 158,
        "alpha158_missing_values": 0,
        "feature_columns": ["signal"],
        "row_count": len(matrix_rows),
        "instrument_count": 2,
        "horizons": [1],
        "matrix_file": {"path": "matrix.parquet", "digest": _digest_file(matrix_path)},
    }
    _write_json(materialization / "manifest.json", materialized_body)
    return raw, materialization


def test_export_builds_repeatable_dynamic_temporal_panel(tmp_path: Path) -> None:
    raw, materialization = _sources(tmp_path / "source")

    first = export_stage_b_v2_stockmixer_panel(
        raw_export_root=raw,
        materialization_root=materialization,
        output_root=tmp_path / "first",
        lookback=64,
    )
    second = export_stage_b_v2_stockmixer_panel(
        raw_export_root=raw,
        materialization_root=materialization,
        output_root=tmp_path / "second",
        lookback=64,
    )

    assert first.content_digest == second.content_digest
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
    assert first.panel_path.read_bytes() == second.panel_path.read_bytes()
    assert first.rows_path.read_bytes() == second.rows_path.read_bytes()
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["lookback"] == 64
    assert manifest["horizons"] == [1]
    assert manifest["instrument_count"] == 2
    assert manifest["context_columns"] == ["market_return_1", "volatility_20"]

    rows = pq.read_table(first.panel_path).to_pylist()
    assert rows == sorted(rows, key=lambda row: (row["slot_time"], row["instrument_id"]))
    missing = next(
        row
        for row in rows
        if row["slot_time"] == datetime(2020, 3, 6, 7, tzinfo=UTC)
        and row["instrument_id"] == "BBB.SSE"
    )
    assert missing["presence_mask"] is True
    assert missing["context_mask"] is True
    assert missing["feature_mask"] is False
    assert missing["tradable_mask"] is False
    assert all(
        missing[name] == 0.0
        for name in (
            "open_relative",
            "high_relative",
            "low_relative",
            "close_relative",
            "log_volume_change",
            "log_turnover_change",
        )
    )


def test_export_rejects_tampering_and_existing_output(tmp_path: Path) -> None:
    raw, materialization = _sources(tmp_path / "source")
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ValueError, match="output_root"):
        export_stage_b_v2_stockmixer_panel(
            raw_export_root=raw,
            materialization_root=materialization,
            output_root=output,
            lookback=64,
        )

    with (raw / "bars.parquet").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="bars digest"):
        export_stage_b_v2_stockmixer_panel(
            raw_export_root=raw,
            materialization_root=materialization,
            output_root=tmp_path / "tampered",
            lookback=64,
        )

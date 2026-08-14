from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch
from astraquant_stockmixer_runner.__main__ import main
from astraquant_stockmixer_runner.contracts import canonical_digest
from astraquant_stockmixer_runner.stage_b_v2_stockmixer import (
    run_stockmixer_v2_request,
)

TEMPORAL_COLUMNS = (
    "open_relative",
    "high_relative",
    "low_relative",
    "close_relative",
    "log_volume_change",
    "log_turnover_change",
)
MODEL_CONFIG = {
    "hidden_dim": 64,
    "market_dim": 32,
    "context_dim": 32,
    "scales": [1, 2, 4],
    "learning_rate": "0.001",
    "weight_decay": "0.0001",
    "ranking_weight": "0.1",
    "epochs": 80,
    "patience": 8,
    "validation_fraction": "0.20",
    "internal_purge_sessions": 11,
    "session_batch_size": 16,
    "batch_semantics": "DECISION_DATE_DYNAMIC_UNIVERSE",
}


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _write_request(root: Path, *, mutate_outer_labels: bool = False) -> Path:
    root.mkdir(parents=True)
    start = datetime(2020, 1, 2, 7, tzinfo=UTC)
    instruments = ("AAA.SSE", "BBB.SSE", "CCC.SSE", "DDD.SSE")
    context_columns = ("market_return_1", "volatility_20")
    panel_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    row_id = 0
    for session in range(96):
        timestamp = start + timedelta(days=session)
        for stock, instrument_id in enumerate(instruments):
            signal = stock / 10 + session / 1000
            panel_rows.append(
                {
                    "slot_time": timestamp,
                    "instrument_id": instrument_id,
                    "event_time": timestamp,
                    "feature_mask": True,
                    "context_mask": True,
                    "presence_mask": True,
                    "tradable_mask": True,
                    **{name: signal + column / 100 for column, name in enumerate(TEMPORAL_COLUMNS)},
                    "market_return_1": session / 1000,
                    "volatility_20": 0.02 + stock / 1000,
                }
            )
            if session >= 63:
                target = stock / (len(instruments) - 1)
                if mutate_outer_labels and session >= 91:
                    target = 1.0 - target
                label_rows.append(
                    {
                        "row_id": row_id,
                        "decision_time": timestamp,
                        "instrument_id": instrument_id,
                        "horizon_sessions": 1,
                        "cross_sectional_rank": target,
                        "training_eligible": not (stock == 0 and session % 5 == 0),
                    }
                )
                row_id += 1
    panel_path = root / "temporal-panel.parquet"
    rows_path = root / "rows.parquet"
    pq.write_table(pa.Table.from_pylist(panel_rows), panel_path)
    pq.write_table(pa.Table.from_pylist(label_rows), rows_path)
    panel_body = {
        "schema_version": "astraquant.stage-b-v2-stockmixer-panel/v1",
        "source_raw_export_digest": "sha256:" + "1" * 64,
        "source_materialization_digest": "sha256:" + "2" * 64,
        "horizons": [1],
        "lookback": 64,
        "price_transform": "PREVIOUS_CLOSE_RELATIVE_V1",
        "volume_transform": "LOG1P_DIFFERENCE_V1",
        "context_visibility": "DECISION_TIME_ONLY",
        "temporal_columns": list(TEMPORAL_COLUMNS),
        "context_columns": list(context_columns),
        "instrument_count": len(instruments),
        "session_count": 96,
        "panel_row_count": len(panel_rows),
        "row_count": len(label_rows),
        "temporal_panel_file": {
            "path": "temporal-panel.parquet",
            "digest": _file_digest(panel_path),
            "row_count": len(panel_rows),
        },
        "rows_file": {"path": "rows.parquet", "digest": _file_digest(rows_path)},
    }
    (root / "manifest.json").write_text(
        json.dumps(
            {"content_digest": canonical_digest(panel_body), **panel_body},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    fit = [row["row_id"] for row in label_rows if row["decision_time"] < start + timedelta(days=86)]
    valid = [
        row["row_id"]
        for row in label_rows
        if start + timedelta(days=86) <= row["decision_time"] < start + timedelta(days=91)
    ]
    test = [
        row["row_id"] for row in label_rows if row["decision_time"] >= start + timedelta(days=91)
    ]
    request_body = {
        "schema_version": "astraquant.stage-b-v2-stockmixer-v2-request/v1",
        "runner_identity": {
            "package": "astraquant-stockmixer-runner",
            "version": "0.1.0",
            "torch_version": torch.__version__,
            "device": "cpu",
        },
        "source_materialization_digest": panel_body["source_materialization_digest"],
        "source_raw_export_digest": panel_body["source_raw_export_digest"],
        "horizon_sessions": 1,
        "instrument_count": len(instruments),
        "row_count": len(label_rows),
        "temporal_panel_file": panel_body["temporal_panel_file"],
        "rows_file": panel_body["rows_file"],
        "feature_spec": {
            "lookback": 64,
            "temporal_columns": list(TEMPORAL_COLUMNS),
            "context_columns": list(context_columns),
            "price_transform": "PREVIOUS_CLOSE_RELATIVE_V1",
            "volume_transform": "LOG1P_DIFFERENCE_V1",
            "context_visibility": "DECISION_TIME_ONLY",
        },
        "model_config": MODEL_CONFIG,
        "trials": [
            {
                "trial_id": "h1-stockmixer_v2-s7-fold-01",
                "seed": 7,
                "fit_row_ids": fit,
                "inner_valid_row_ids": valid,
                "outer_test_row_ids": test,
            }
        ],
    }
    request_path = root / "request.json"
    request_path.write_text(
        json.dumps(
            {"content_digest": canonical_digest(request_body), **request_body},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return request_path


def test_runner_is_deterministic_resumable_and_cli_writes_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _write_request(tmp_path / "input")
    output = tmp_path / "output" / "response.json"

    first = run_stockmixer_v2_request(request, output)
    first_bytes = output.read_bytes()
    monkeypatch.setattr(
        "astraquant_stockmixer_runner.stage_b_v2_stockmixer._fit_trial",
        lambda **kwargs: pytest.fail("completed trial must resume from checkpoint"),
    )
    second = run_stockmixer_v2_request(request, output)

    assert second == first
    assert output.read_bytes() == first_bytes
    assert first["schema_version"] == "astraquant.stage-b-v2-stockmixer-v2-response/v1"
    assert first["trials"][0]["model_digest"].startswith("sha256:")
    assert main(["stockmixer-v2", str(request), "--output", str(output)]) == 0


def test_outer_labels_cannot_change_processor_model_or_predictions(tmp_path: Path) -> None:
    baseline_request = _write_request(tmp_path / "baseline")
    changed_request = _write_request(tmp_path / "changed", mutate_outer_labels=True)

    baseline = run_stockmixer_v2_request(
        baseline_request, tmp_path / "baseline-output" / "response.json"
    )["trials"][0]
    changed = run_stockmixer_v2_request(
        changed_request, tmp_path / "changed-output" / "response.json"
    )["trials"][0]

    assert baseline["processor_digest"] == changed["processor_digest"]
    assert baseline["model_digest"] == changed["model_digest"]
    assert baseline["inner_valid_predictions"] == changed["inner_valid_predictions"]
    assert baseline["outer_test_predictions"] == changed["outer_test_predictions"]


def test_runner_rejects_wrong_panel_identity(tmp_path: Path) -> None:
    request = _write_request(tmp_path / "input")
    value = json.loads(request.read_text(encoding="utf-8"))
    body = {key: item for key, item in value.items() if key != "content_digest"}
    body["source_raw_export_digest"] = "sha256:" + "9" * 64
    request.write_text(
        json.dumps(
            {"content_digest": canonical_digest(body), **body},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="raw export identity"):
        run_stockmixer_v2_request(request, tmp_path / "response.json")

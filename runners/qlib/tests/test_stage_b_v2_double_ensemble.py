from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from astraquant_qlib_runner.stage_b_v2_double_ensemble import run_double_ensemble_request


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _request(root: Path) -> Path:
    start = datetime(2020, 1, 2, 7, tzinfo=UTC)
    rows = [
        {
            "row_id": index,
            "decision_time": start + timedelta(days=index),
            "instrument_id": f"S{index % 10:03d}.SSE",
            "signal": index / 100,
            "missing": None if index % 4 == 0 else index / 50,
            "cross_sectional_rank": (index % 10) / 9,
            "training_eligible": index % 10 not in (0, 9),
        }
        for index in range(60)
    ]
    rows_path = root / "rows.parquet"
    pq.write_table(pa.Table.from_pylist(rows), rows_path)
    body = {
        "schema_version": "astraquant.stage-b-v2-double-ensemble-request/v1",
        "upstream_commit": "79633dd9506ea689e5400dea0197717b5b3d74b7",
        "source_materialization_digest": "sha256:" + "1" * 64,
        "feature_columns": ["signal", "missing"],
        "row_count": len(rows),
        "rows_file": {"path": "rows.parquet", "digest": _digest(rows_path.read_bytes())},
        "model_config": {
            "num_models": 3,
            "epochs": 28,
            "enable_sr": True,
            "enable_fs": True,
            "decay": 0.5,
        },
        "trials": [
            {
                "trial_id": "h5-double_ensemble-s7-fold-01",
                "seed": 7,
                "fit_row_ids": list(range(40)),
                "inner_valid_row_ids": list(range(40, 50)),
                "outer_test_row_ids": list(range(50, 60)),
            }
        ],
    }
    request = {"content_digest": _digest(_canonical(body)), **body}
    path = root / "request.json"
    path.write_bytes(_canonical(request) + b"\n")
    return path


class _FakeModel:
    def fit(self, dataset: object) -> None:
        del dataset

    def predict(self, dataset: object, segment: str) -> pd.Series:
        frame = dataset.prepare(segment, col_set="feature")
        return frame["signal"]


def test_runner_fits_train_only_processor_and_returns_valid_test_scores(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "astraquant_qlib_runner.stage_b_v2_double_ensemble.create_double_ensemble_model",
        lambda config, seed: _FakeModel(),
    )
    request = _request(tmp_path)

    first = run_double_ensemble_request(request, tmp_path / "first.json")
    second = run_double_ensemble_request(request, tmp_path / "second.json")

    assert first == second
    assert first["schema_version"] == "astraquant.stage-b-v2-double-ensemble-response/v1"
    assert first["upstream_commit"] == "79633dd9506ea689e5400dea0197717b5b3d74b7"
    trial = first["trials"][0]
    assert trial["trial_id"] == "h5-double_ensemble-s7-fold-01"
    assert trial["processor_digest"].startswith("sha256:")
    assert trial["model_digest"].startswith("sha256:")
    assert [item["row_id"] for item in trial["inner_valid_predictions"]] == list(range(40, 50))
    assert [item["row_id"] for item in trial["outer_test_predictions"]] == list(range(50, 60))
    assert (tmp_path / "first.json").read_bytes() == (tmp_path / "second.json").read_bytes()

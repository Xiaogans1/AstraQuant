from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
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


def test_runner_reuses_fold_preprocessing_for_adjacent_seeds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "astraquant_qlib_runner.stage_b_v2_double_ensemble.create_double_ensemble_model",
        lambda config, seed: _FakeModel(),
    )
    request_path = _request(tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    second = {**request["trials"][0], "trial_id": "h5-double_ensemble-s11-fold-01", "seed": 11}
    body = {
        key: value
        for key, value in {**request, "trials": [request["trials"][0], second]}.items()
        if key != "content_digest"
    }
    request_path.write_bytes(
        _canonical({"content_digest": _digest(_canonical(body)), **body}) + b"\n"
    )
    calls = {"fit": 0, "transform": 0}
    from astraquant_qlib_runner import stage_b_v2_double_ensemble as runner

    original_fit = runner._fit_processor
    original_transform = runner._transform

    def counted_fit(*args, **kwargs):
        calls["fit"] += 1
        return original_fit(*args, **kwargs)

    def counted_transform(*args, **kwargs):
        calls["transform"] += 1
        return original_transform(*args, **kwargs)

    monkeypatch.setattr(runner, "_fit_processor", counted_fit)
    monkeypatch.setattr(runner, "_transform", counted_transform)

    response = run_double_ensemble_request(request_path, tmp_path / "response.json")

    assert [trial["seed"] for trial in response["trials"]] == [7, 11]
    assert calls == {"fit": 1, "transform": 1}


def test_runner_resumes_completed_trials_after_later_trial_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _request(tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    second = {**request["trials"][0], "trial_id": "h5-double_ensemble-s11-fold-01", "seed": 11}
    body = {
        key: value
        for key, value in {**request, "trials": [request["trials"][0], second]}.items()
        if key != "content_digest"
    }
    request_path.write_bytes(
        _canonical({"content_digest": _digest(_canonical(body)), **body}) + b"\n"
    )
    first_seeds: list[int] = []

    def fail_second(config, seed):
        del config
        first_seeds.append(seed)
        if seed == 11:
            raise RuntimeError("interrupted")
        return _FakeModel()

    monkeypatch.setattr(
        "astraquant_qlib_runner.stage_b_v2_double_ensemble.create_double_ensemble_model",
        fail_second,
    )
    output = tmp_path / "response.json"
    with pytest.raises(RuntimeError, match="interrupted"):
        run_double_ensemble_request(request_path, output)

    assert first_seeds == [7, 11]
    assert len(tuple((tmp_path / "trial-checkpoints").glob("*.json"))) == 1

    resumed_seeds: list[int] = []

    def resume(config, seed):
        del config
        resumed_seeds.append(seed)
        return _FakeModel()

    monkeypatch.setattr(
        "astraquant_qlib_runner.stage_b_v2_double_ensemble.create_double_ensemble_model",
        resume,
    )
    response = run_double_ensemble_request(request_path, output)

    assert resumed_seeds == [11]
    assert [trial["seed"] for trial in response["trials"]] == [7, 11]
    assert len(tuple((tmp_path / "trial-checkpoints").glob("*.json"))) == 2

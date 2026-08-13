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
from astraquant_stockmixer_runner.stage_b_v2_shared_mlp import (
    run_shared_mlp_request,
)


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


def _write_request(
    root: Path, *, mutate_outer_labels: bool = False, two_trials: bool = False
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    start = datetime(2020, 1, 2, 7, tzinfo=UTC)
    rows = []
    for session in range(60):
        for stock in range(3 + session % 2):
            row_id = len(rows)
            signal = (stock + 1) / (4 + session % 2)
            target = signal
            if mutate_outer_labels and session >= 52:
                target = 1.0 - target
            rows.append(
                {
                    "row_id": row_id,
                    "decision_time": start + timedelta(days=session),
                    "instrument_id": f"S{stock:03d}.SSE",
                    "signal": signal + session / 1000,
                    "missing": None if row_id % 7 == 0 else stock / 10,
                    "cross_sectional_rank": target,
                    "training_eligible": not (session < 42 and stock == 0 and session % 5 == 0),
                }
            )
    rows_path = root / "rows.parquet"
    pq.write_table(pa.Table.from_pylist(rows), rows_path)
    fit = [row["row_id"] for row in rows if row["decision_time"] < start + timedelta(days=42)]
    valid = [
        row["row_id"]
        for row in rows
        if start + timedelta(days=42) <= row["decision_time"] < start + timedelta(days=52)
    ]
    test = [row["row_id"] for row in rows if row["decision_time"] >= start + timedelta(days=52)]
    trial = {
        "trial_id": "h5-shared_mlp-s7-fold-01",
        "seed": 7,
        "fit_row_ids": fit,
        "inner_valid_row_ids": valid,
        "outer_test_row_ids": test,
    }
    trials = [trial]
    if two_trials:
        trials.append({**trial, "trial_id": "h5-shared_mlp-s11-fold-01", "seed": 11})
    body = {
        "schema_version": "astraquant.stage-b-v2-shared-mlp-request/v1",
        "runner_identity": {
            "package": "astraquant-stockmixer-runner",
            "version": "0.1.0",
            "torch_version": torch.__version__,
            "device": "cpu",
        },
        "source_materialization_digest": "sha256:" + "1" * 64,
        "feature_columns": ["signal", "missing"],
        "row_count": len(rows),
        "rows_file": {"path": "rows.parquet", "digest": _digest(rows_path.read_bytes())},
        "model_config": {
            "hidden_dim": 64,
            "market_dim": 32,
            "encoder_layers": 2,
            "dropout": 0,
            "learning_rate": "0.001",
            "weight_decay": "0.0001",
            "epochs": 80,
            "patience": 8,
            "validation_fraction": "0.20",
            "internal_purge_sessions": 11,
            "session_batch_size": 16,
            "batch_semantics": "DECISION_DATE_CROSS_SECTION",
        },
        "trials": trials,
    }
    request = {"content_digest": _digest(_canonical(body)), **body}
    path = root / "request.json"
    path.write_bytes(_canonical(request) + b"\n")
    return path


def test_runner_is_deterministic_and_resumes_completed_trial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _write_request(tmp_path)
    output = tmp_path / "response.json"

    first = run_shared_mlp_request(request, output)
    first_bytes = output.read_bytes()
    monkeypatch.setattr(
        "astraquant_stockmixer_runner.stage_b_v2_shared_mlp._fit_trial",
        lambda **kwargs: pytest.fail("completed trial must be restored from checkpoint"),
    )
    second = run_shared_mlp_request(request, output)

    assert second == first
    assert output.read_bytes() == first_bytes
    assert first["runner_identity"]["device"] == "cpu"
    assert first["trials"][0]["model_digest"].startswith("sha256:")
    assert [item["row_id"] for item in first["trials"][0]["outer_test_predictions"]]


def test_outer_labels_cannot_change_processor_model_or_predictions(tmp_path: Path) -> None:
    baseline_request = _write_request(tmp_path / "baseline")
    changed_request = _write_request(tmp_path / "changed", mutate_outer_labels=True)

    baseline = run_shared_mlp_request(baseline_request, tmp_path / "baseline" / "response.json")
    changed = run_shared_mlp_request(changed_request, tmp_path / "changed" / "response.json")

    baseline_trial = baseline["trials"][0]
    changed_trial = changed["trials"][0]
    assert baseline_trial["processor_digest"] == changed_trial["processor_digest"]
    assert baseline_trial["model_digest"] == changed_trial["model_digest"]
    assert baseline_trial["inner_valid_predictions"] == changed_trial["inner_valid_predictions"]
    assert baseline_trial["outer_test_predictions"] == changed_trial["outer_test_predictions"]


def test_same_request_seed_and_device_are_byte_identical_without_shared_checkpoint(
    tmp_path: Path,
) -> None:
    request = _write_request(tmp_path / "input")
    first_path = tmp_path / "first" / "response.json"
    second_path = tmp_path / "second" / "response.json"

    first = run_shared_mlp_request(request, first_path)
    second = run_shared_mlp_request(request, second_path)

    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()


def test_runner_keeps_first_trial_when_later_trial_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _write_request(tmp_path, two_trials=True)
    output = tmp_path / "response.json"
    from astraquant_stockmixer_runner import stage_b_v2_shared_mlp as runner

    original = runner._fit_trial
    seen: list[int] = []

    def interrupt_second(**kwargs):
        seen.append(kwargs["seed"])
        if kwargs["seed"] == 11:
            raise RuntimeError("interrupted")
        return original(**kwargs)

    monkeypatch.setattr(runner, "_fit_trial", interrupt_second)
    with pytest.raises(RuntimeError, match="interrupted"):
        run_shared_mlp_request(request, output)
    assert seen == [7, 11]
    assert len(tuple((tmp_path / "trial-checkpoints").glob("*.json"))) == 1

    resumed: list[int] = []

    def record_resume(**kwargs):
        resumed.append(kwargs["seed"])
        return original(**kwargs)

    monkeypatch.setattr(runner, "_fit_trial", record_resume)
    response = run_shared_mlp_request(request, output)

    assert resumed == [11]
    assert [trial["seed"] for trial in response["trials"]] == [7, 11]


def test_runner_refuses_unavailable_cuda_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    request_path = _write_request(tmp_path)
    value = json.loads(request_path.read_text(encoding="utf-8"))
    body = {key: item for key, item in value.items() if key != "content_digest"}
    body["runner_identity"] = {**body["runner_identity"], "device": "cuda"}
    request_path.write_bytes(
        _canonical({"content_digest": _digest(_canonical(body)), **body}) + b"\n"
    )

    with pytest.raises(ValueError, match="CUDA is unavailable"):
        run_shared_mlp_request(request_path, tmp_path / "response.json")


def test_shared_mlp_cli_writes_response(tmp_path: Path) -> None:
    request = _write_request(tmp_path)
    output = tmp_path / "response.json"

    assert main(["shared-mlp", str(request), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == (
        "astraquant.stage-b-v2-shared-mlp-response/v1"
    )

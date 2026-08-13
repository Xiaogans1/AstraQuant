from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from tests.research.test_run_panel_executable_backtest import _publish

from astraquant_data.exports.qlib import QLIB_UPSTREAM_COMMIT
from astraquant_domain.run_manifest import canonical_json_bytes
from tools.research.prepare_kronos_weights import (
    KRONOS_MODEL_REVISION,
    KRONOS_TOKENIZER_REVISION,
)
from tools.research.run_kronos_zero_shot import (
    main,
    restrict_folds_to_eligibility,
    validate_kronos_response,
)


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(root: Path, name: str, revision: str, content: bytes) -> None:
    directory = root / ".astraquant" / "models" / "kronos" / name / revision
    directory.mkdir(parents=True)
    (directory / "config.json").write_bytes(b"{}")
    weights = directory / "model.safetensors"
    weights.write_bytes(content)
    manifest = {
        "schema_version": "astraquant.kronos-local-artifact/v1",
        "repo_id": "NeoQuasar/" + name,
        "revision": revision,
        "files": {
            "config.json": _sha(directory / "config.json"),
            "model.safetensors": _sha(weights),
        },
    }
    (directory / "artifact-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _specs(data_root: Path) -> list[str]:
    datasets = [_publish(data_root, "159516.SZSE"), _publish(data_root, "512480.SSE")]
    result = []
    for dataset_id in datasets:
        manifest = next(
            (data_root / "datasets" / dataset_id / "snapshots").glob("*/manifest.json")
        )
        result.append(f"{dataset_id}@{manifest.parent.name}")
    return result


def _kronos_response(
    request: Mapping[str, object], score_by_row: dict[int, float]
) -> dict[str, object]:
    model = request["model"]
    tokenizer = request["tokenizer"]
    assert isinstance(model, dict) and isinstance(model["weights"], dict)
    assert isinstance(tokenizer, dict) and isinstance(tokenizer["weights"], dict)
    rows = request["rows"]
    assert isinstance(rows, list)
    forecasts = []
    for raw in rows:
        assert isinstance(raw, dict)
        row_id = raw["row_id"]
        assert isinstance(row_id, int)
        score = score_by_row[row_id]
        forecasts.append(
            {
                "fold_id": raw["fold_id"],
                "row_id": row_id,
                "instrument_id": raw["instrument_id"],
                "decision_time": raw["decision_time"],
                "expected_return": score,
                "up_path_fraction": 1.0 if score > 0 else 0.0,
                "terminal_return_p10": score - 0.001,
                "terminal_return_p50": score,
                "terminal_return_p90": score + 0.001,
                "predicted_volatility": 0.001,
                "uncertainty_width": 0.002,
            }
        )
    body = {
        "schema_version": "astraquant.kronos-response/v1",
        "request_content_digest": request["content_digest"],
        "upstream_commit": request["upstream_commit"],
        "model": {
            "id": model["id"],
            "revision": model["revision"],
            "weights_digest": model["weights"]["digest"],
        },
        "tokenizer": {
            "id": tokenizer["id"],
            "revision": tokenizer["revision"],
            "weights_digest": tokenizer["weights"]["digest"],
        },
        "environment": {"python": "3.11", "torch": "2.7.1+cu128", "device": "cuda:0"},
        "forecasts": forecasts,
    }
    return {
        "content_digest": "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest(),
        **body,
    }


def test_prepare_and_evaluate_three_models_on_one_eligibility_mask(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    specs = _specs(data_root)
    _artifact(tmp_path, "Kronos-base", KRONOS_MODEL_REVISION, b"model")
    _artifact(
        tmp_path,
        "Kronos-Tokenizer-base",
        KRONOS_TOKENIZER_REVISION,
        b"tokenizer",
    )
    run_root = tmp_path / "run"
    assert (
        main(
            [
                "prepare",
                *specs,
                "--data-root",
                str(data_root),
                "--runner-root",
                str(tmp_path),
                "--output-root",
                str(run_root),
                "--minimum-train-timestamps",
                "30",
                "--test-timestamp-count",
                "5",
                "--fold-count",
                "2",
                "--holding-bars",
                "2",
                "--context-length",
                "8",
                "--sample-count",
                "3",
            ]
        )
        == 0
    )
    context = json.loads((run_root / "context.json").read_text())
    kronos_request = json.loads((run_root / "kronos" / "request.json").read_text())
    qlib_request = json.loads((run_root / "qlib" / "request.json").read_text())
    qlib_rows = pq.read_table(run_root / "qlib" / "rows.parquet").to_pylist()
    scores = {index: float(row["future_return"]) for index, row in enumerate(qlib_rows)}
    kronos_response = _kronos_response(kronos_request, scores)
    kronos_path = run_root / "kronos-response.json"
    kronos_path.write_text(json.dumps(kronos_response), encoding="utf-8")
    qlib_response = {
        "schema_version": "astraquant.qlib-response/v1",
        "request_content_digest": qlib_request["content_digest"],
        "upstream_commit": QLIB_UPSTREAM_COMMIT,
        "model": "qlib.contrib.model.double_ensemble.DEnsembleModel",
        "model_kind": "DOUBLE_ENSEMBLE",
        "score_semantics": "EXPECTED_RETURN",
        "training_task_digest": qlib_request["training_task_digest"],
        "predictions": [
            {"fold_id": fold["fold_id"], "row_id": row_id, "score": scores[row_id]}
            for fold in qlib_request["folds"]
            for row_id in fold["test_indices"]
        ],
    }
    qlib_path = run_root / "qlib-response.json"
    qlib_path.write_text(json.dumps(qlib_response), encoding="utf-8")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    common = [
        "evaluate",
        "--context",
        str(run_root / "context.json"),
        "--kronos-response",
        str(kronos_path),
        "--double-ensemble-response",
        str(qlib_path),
    ]
    assert main([*common, "--output", str(first)]) == 0
    assert main([*common, "--output", str(second)]) == 0

    assert first.read_bytes() == second.read_bytes()
    report = json.loads(first.read_text())
    assert report["schema_version"] == "astraquant.kronos-unified-executable/v1"
    assert set(report["models"]) == {"KRONOS_ZERO_SHOT", "DOUBLE_ENSEMBLE", "RIDGE"}
    assert report["shared_contract"]["eligible_rows"] == len(kronos_request["rows"])
    diagnostics = report["kronos_path_diagnostics"]
    assert diagnostics["truth_basis"] == "DECISION_CLOSE_TO_TERMINAL_CLOSE"
    assert diagnostics["forecast_horizon_bars"] == 2
    assert diagnostics["terminal_return_mae"] >= 0
    assert context["kronos_request_content_digest"] == kronos_request["content_digest"]


def test_response_validation_and_eligibility_fail_closed(tmp_path: Path) -> None:
    request: dict[str, object] = {
        "content_digest": "sha256:" + "1" * 64,
        "upstream_commit": "a" * 40,
        "model": {
            "id": "m",
            "revision": "b" * 40,
            "weights": {"digest": "sha256:" + "2" * 64},
        },
        "tokenizer": {
            "id": "t",
            "revision": "c" * 40,
            "weights": {"digest": "sha256:" + "3" * 64},
        },
        "rows": [
            {
                "fold_id": "fold-01",
                "row_id": 7,
                "instrument_id": "512800.SSE",
                "decision_time": "2026-08-07T07:00:00+00:00",
            }
        ],
    }
    response = _kronos_response(request, {7: 0.01})
    validate_kronos_response(response, request)
    broken = json.loads(json.dumps(response))
    broken["forecasts"][0]["expected_return"] = 0.02
    with pytest.raises(ValueError, match="median"):
        validate_kronos_response(broken, request)

    from astraquant_quant.baseline_matrix import WalkForwardFold

    folds = (WalkForwardFold("fold-01", (0, 1, 2), (3, 4, 5)),)
    restricted = restrict_folds_to_eligibility(folds, {("fold-01", 4), ("fold-01", 5)})
    assert restricted[0].train_indices == folds[0].train_indices
    assert restricted[0].test_indices == (4, 5)
    with pytest.raises(ValueError, match="unknown fold rows"):
        restrict_folds_to_eligibility(folds, {("fold-01", 99)})

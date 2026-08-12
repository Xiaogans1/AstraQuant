from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
from tests.research.test_run_panel_executable_backtest import _publish

from astraquant_data.exports.qlib import QLIB_UPSTREAM_COMMIT
from tools.research.run_double_ensemble_panel import main


def test_prepare_and_evaluate_exact_panel_repeatably(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    datasets = [_publish(data_root, "159516.SZSE"), _publish(data_root, "512480.SSE")]
    specs = []
    for dataset_id in datasets:
        manifest = next((data_root / "datasets" / dataset_id / "snapshots").glob("*/manifest.json"))
        specs.append(f"{dataset_id}@{manifest.parent.name}")
    run_root = tmp_path / "run"

    prepare = [
        "prepare",
        *specs,
        "--data-root",
        str(data_root),
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
    ]
    assert main(prepare) == 0

    request = json.loads((run_root / "export" / "request.json").read_text(encoding="utf-8"))
    rows = pq.read_table(run_root / "export" / "rows.parquet").to_pylist()
    response = {
        "schema_version": "astraquant.qlib-response/v1",
        "request_content_digest": request["content_digest"],
        "upstream_commit": QLIB_UPSTREAM_COMMIT,
        "model": "qlib.contrib.model.double_ensemble.DEnsembleModel",
        "model_kind": "DOUBLE_ENSEMBLE",
        "score_semantics": "EXPECTED_RETURN",
        "training_task_digest": request["training_task_digest"],
        "predictions": [
            {"fold_id": fold["fold_id"], "row_id": row_id, "score": rows[row_id]["future_return"]}
            for fold in request["folds"]
            for row_id in fold["test_indices"]
        ],
    }
    response_path = run_root / "response.json"
    response_path.write_text(json.dumps(response), encoding="utf-8")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    common = [
        "evaluate",
        "--context",
        str(run_root / "context.json"),
        "--response",
        str(response_path),
    ]
    assert main([*common, "--output", str(first)]) == 0
    assert main([*common, "--output", str(second)]) == 0

    assert first.read_bytes() == second.read_bytes()
    report = json.loads(first.read_text(encoding="utf-8"))
    assert report["schema_version"] == "astraquant.double-ensemble-panel-executable/v1"
    assert set(report["models"]) == {"RIDGE", "DOUBLE_ENSEMBLE"}
    assert len(report["sources"]) == 2
    assert all(
        "liquidity_bucket" in item
        for item in report["models"]["DOUBLE_ENSEMBLE"]["instruments"]
    )
    assert all("regime" in item for item in report["models"]["DOUBLE_ENSEMBLE"]["folds"])
    assert report["digests"]["input"] == request["content_digest"]
    assert report["digests"]["report"].startswith("sha256:")

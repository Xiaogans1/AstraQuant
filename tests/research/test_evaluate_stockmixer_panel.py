from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from tests.research.test_run_panel_executable_backtest import _publish

from astraquant_data.exports.stockmixer import (
    StockMixerSource,
    UniverseMembership,
    export_stockmixer_request,
)
from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.panel_research import build_panel, panel_walk_forward
from tools.research.build_training_set import build_features_json
from tools.research.evaluate_stockmixer_panel import main
from tools.research.run_panel_executable_backtest import _instrument


def _sha(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    data_root = tmp_path / "data"
    datasets = [_publish(data_root, "159516.SZSE"), _publish(data_root, "512480.SSE")]
    payloads = []
    for dataset_id in datasets:
        manifest = next((data_root / "datasets" / dataset_id / "snapshots").glob("*/manifest.json"))
        payloads.append(
            build_features_json(
                data_root,
                dataset_id,
                horizon=2,
                threshold=0.005,
                snapshot_id=manifest.parent.name,
            )
        )
    panel = build_panel(tuple(_instrument(payload) for payload in payloads))
    folds = panel_walk_forward(
        panel,
        minimum_train_timestamps=30,
        test_timestamp_count=5,
        fold_count=2,
        purge_timestamp_count=3,
    )
    times = {item.timestamp for item in panel.observations}
    export = export_stockmixer_request(
        output_root=tmp_path / "request",
        panel=panel,
        folds=folds,
        sources=tuple(
            StockMixerSource(
                str(payload["dataset_id"]),
                str(payload["instrument_id"]),
                str(payload["source_snapshot_id"]),
            )
            for payload in payloads
        ),
        universe=UniverseMembership(
            universe_id="two-etf",
            universe_snapshot_id=f"sha256:{'f' * 64}",
            members_by_time={
                timestamp: frozenset(str(payload["instrument_id"]) for payload in payloads)
                for timestamp in times
            },
        ),
        lookback=3,
        label_name="future_return",
    )
    request = json.loads(export.request_path.read_text())
    panel_rows = pq.read_table(export.panel_path).to_pylist()
    samples = pq.read_table(export.samples_path).to_pylist()
    instruments = [item["instrument_id"] for item in request["sources"]]
    slot_labels = {
        (row["slot_time"], row["instrument_id"]): float(row["label"])
        for row in panel_rows
    }
    artifact_root = tmp_path / "artifacts"
    for fold_id in sorted({str(item["fold_id"]) for item in samples}):
        fold_root = artifact_root / fold_id
        fold_root.mkdir(parents=True)
        model = fold_root / "model-state.bin"
        model.write_bytes(fold_id.encode())
        rows = []
        for sample in samples:
            if sample["fold_id"] != fold_id or sample["segment"] != "test":
                continue
            decision = sample["decision_time"]
            assert isinstance(decision, datetime)
            for instrument in instruments:
                rows.append(
                    {
                        "fold_id": fold_id,
                        "sample_id": sample["sample_id"],
                        "decision_time_us": round(decision.timestamp() * 1_000_000),
                        "instrument_id": instrument,
                        "score": slot_labels[(decision, instrument)],
                    }
                )
        predictions = fold_root / "predictions.parquet"
        pq.write_table(pa.Table.from_pylist(rows), predictions)
        body = {
            "schema_version": "astraquant.stockmixer-training-response/v1",
            "request_content_digest": request["content_digest"],
            "fold_id": fold_id,
            "training_config_digest": f"sha256:{'a' * 64}",
            "code_digest": f"sha256:{'b' * 64}",
            "files": {
                "model": {"path": "model-state.bin", "digest": _sha(model)},
                "predictions": {"path": "predictions.parquet", "digest": _sha(predictions)},
            },
        }
        response = {"content_digest": _digest(body), **body}
        (fold_root / "response.json").write_text(json.dumps(response), encoding="utf-8")
    return data_root, export.request_path, artifact_root


def test_evaluates_sealed_predictions_repeatably(tmp_path: Path) -> None:
    data_root, request, artifacts = _setup(tmp_path)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    common = [
        str(request),
        "--artifact-root",
        str(artifacts),
        "--data-root",
        str(data_root),
        "--holding-bars",
        "2",
        "--minimum-score",
        "-1",
    ]

    assert main([*common, "--output", str(first)]) == 0
    assert main([*common, "--output", str(second)]) == 0

    assert first.read_bytes() == second.read_bytes()
    report = json.loads(first.read_text())
    assert report["schema_version"] == "astraquant.stockmixer-panel-executable/v1"
    assert report["model"]["executed_trades"] > 0
    assert report["shared_contract"]["score_semantics"] == "EXPECTED_RETURN"
    assert report["digests"]["request"].startswith("sha256:")


def test_rejects_tampered_or_incomplete_prediction_artifact(tmp_path: Path) -> None:
    data_root, request, artifacts = _setup(tmp_path)
    prediction = artifacts / "fold-01" / "predictions.parquet"
    prediction.write_bytes(prediction.read_bytes() + b"tampered")

    assert (
        main(
            [
                str(request),
                "--artifact-root",
                str(artifacts),
                "--data-root",
                str(data_root),
                "--holding-bars",
                "2",
                "--output",
                str(tmp_path / "report.json"),
            ]
        )
        == 1
    )


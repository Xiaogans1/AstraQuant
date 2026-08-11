from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from astraquant_quant.baseline_matrix import expanding_walk_forward, run_baseline_matrix
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS
from tools.research.compare_alpha158 import main as compare_main
from tools.research.export_qlib_alpha158 import main as export_main


def _rows(count: int = 60) -> list[dict[str, float | int]]:
    return [
        {
            **{name: (1.0 if row_id % 2 else -1.0) for name in MODEL_FEATURE_COLUMNS},
            "label": row_id % 2,
            "future_return": 0.01 if row_id % 2 else -0.01,
        }
        for row_id in range(count)
    ]


def _training_payload(path: Path) -> list[dict[str, float | int]]:
    rows = _rows()
    path.write_text(
        json.dumps(
            {
                "dataset_id": "s1-fixture",
                "source_snapshot_id": "1" * 64,
                "provider_id": "eastmoney",
                "instrument_id": "159516.SZSE",
                "rows": rows,
                "row_bar_indices": list(range(30, 90)),
                "raw_bars": [
                    {
                        "timestamp": (
                            datetime(2026, 8, 3, 1, 30, tzinfo=UTC) + timedelta(minutes=bar_id)
                        ).isoformat(),
                        "open": 10.0 + bar_id / 100,
                        "high": 10.1 + bar_id / 100,
                        "low": 9.9 + bar_id / 100,
                        "close": 10.05 + bar_id / 100,
                        "volume": 100.0 + bar_id,
                        "vwap": 10.02 + bar_id / 100,
                    }
                    for bar_id in range(100)
                ],
            }
        ),
        encoding="utf-8",
    )
    return rows


def _native_report(path: Path, rows: list[dict[str, float | int]]) -> None:
    folds = expanding_walk_forward(rows, minimum_train_size=30, test_size=10, fold_count=2)
    report = run_baseline_matrix(
        rows,
        folds=folds,
        fee_rate=Decimal("0.001"),
        prediction_threshold=0.5,
        seed=7,
    )
    model = next(summary for summary in report.models if summary.model.value == "LIGHTGBM")
    path.write_text(
        json.dumps(
            {
                "schema_version": "astraquant.strategy-baseline-matrix/v1",
                "dataset_id": "s1-fixture",
                "source_snapshot_id": "1" * 64,
                "provider_id": "eastmoney",
                "seed": 7,
                "prediction_threshold": 0.5,
                "fee_rate": "0.001",
                "models": [
                    {
                        "model": "LIGHTGBM",
                        "auc": model.auc,
                        "gross_return": model.gross_return,
                        "net_return": model.net_return,
                        "trades": model.trades,
                        "positive_folds": model.positive_folds,
                        "folds": [
                            {
                                "fold_id": fold.fold_id,
                                "test_rows": fold.test_rows,
                                "auc": fold.auc,
                                "gross_return": fold.gross_return,
                                "net_return": fold.net_return,
                                "trades": fold.trades,
                            }
                            for fold in model.folds
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_alpha158_export_and_compare_share_rows_folds_and_costs(tmp_path: Path) -> None:
    training_path = tmp_path / "training.json"
    rows = _training_payload(training_path)
    export_root = tmp_path / "export"

    assert (
        export_main(
            [
                str(training_path),
                "--output-root",
                str(export_root),
                "--minimum-train-size",
                "30",
                "--test-size",
                "10",
                "--fold-count",
                "2",
                "--fee-rate",
                "0.001",
                "--prediction-threshold",
                "0.5",
                "--seed",
                "7",
            ]
        )
        == 0
    )
    request = json.loads((export_root / "request.json").read_text(encoding="utf-8"))
    response_path = tmp_path / "response.json"
    predictions = [
        {
            "fold_id": fold["fold_id"],
            "row_id": row_id,
            "probability": 0.9 if int(rows[row_id]["label"]) else 0.1,
        }
        for fold in request["folds"]
        for row_id in fold["test_indices"]
    ]
    response_path.write_text(
        json.dumps(
            {
                "schema_version": "astraquant.qlib-alpha158-response/v1",
                "request_content_digest": request["content_digest"],
                "upstream_commit": request["upstream_commit"],
                "alpha158_config_digest": request["alpha158_config_digest"],
                "alpha158_feature_count": 158,
                "feature_set": "QLIB_ALPHA158",
                "model": "qlib.contrib.model.gbdt.LGBModel",
                "predictions": predictions,
            }
        ),
        encoding="utf-8",
    )
    native_path = tmp_path / "native.json"
    _native_report(native_path, rows)
    output_path = tmp_path / "comparison.json"

    assert (
        compare_main(
            [
                str(export_root / "request.json"),
                str(response_path),
                str(native_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == "astraquant.alpha158-comparison/v1"
    assert result["shared_contract"]["test_rows"] == 20
    assert result["shared_contract"]["alpha158_feature_count"] == 158
    assert result["alpha158_lightgbm"]["auc"] == 1.0
    assert set(result["alpha158_minus_astra10"]) == {
        "auc",
        "gross_return",
        "net_return",
        "trades",
    }

    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["predictions"].pop()
    response_path.write_text(json.dumps(response), encoding="utf-8")
    assert (
        compare_main(
            [
                str(export_root / "request.json"),
                str(response_path),
                str(native_path),
                "--output",
                str(tmp_path / "invalid.json"),
            ]
        )
        == 1
    )

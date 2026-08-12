from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from astraquant_data.exports.qlib import export_qlib_request
from astraquant_domain import ScoreSemantics, TrainingTaskKind, TrainingTaskSpec
from astraquant_quant.baseline_matrix import (
    WalkForwardFold,
    expanding_walk_forward,
    run_baseline_matrix,
)
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS
from tools.research.compare_qlib_baseline import main


def _rows(count: int) -> list[dict[str, float | int]]:
    values = []
    for row_id in range(count):
        label = row_id % 2
        signal = 1.0 if label else -1.0
        values.append(
            {
                **{name: signal for name in MODEL_FEATURE_COLUMNS},
                "label": label,
                "future_return": signal * 0.01,
            }
        )
    return values


def _native_report(
    path: Path,
    rows: list[dict[str, float | int]],
    folds: tuple[WalkForwardFold, ...],
) -> None:
    report = run_baseline_matrix(
        rows,
        folds=folds,
        fee_rate=Decimal("0.001"),
        prediction_threshold=0.5,
        seed=7,
    )
    lightgbm = next(value for value in report.models if value.model.value == "LIGHTGBM")
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
                        "auc": lightgbm.auc,
                        "gross_return": lightgbm.gross_return,
                        "net_return": lightgbm.net_return,
                        "trades": lightgbm.trades,
                        "positive_folds": lightgbm.positive_folds,
                        "folds": [
                            {
                                "fold_id": fold.fold_id,
                                "test_rows": fold.test_rows,
                                "auc": fold.auc,
                                "gross_return": fold.gross_return,
                                "net_return": fold.net_return,
                                "trades": fold.trades,
                            }
                            for fold in lightgbm.folds
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_compare_cli_uses_shared_rows_folds_and_costs(tmp_path: Path) -> None:
    rows = _rows(40)
    folds = expanding_walk_forward(rows, minimum_train_size=20, test_size=5, fold_count=2)
    export = export_qlib_request(
        output_root=tmp_path / "export",
        dataset_id="s1-fixture",
        source_snapshot_id="1" * 64,
        provider_id="eastmoney",
        rows=rows,
        folds=folds,
        fee_rate=Decimal("0.001"),
        prediction_threshold=0.5,
        seed=7,
        training_task=TrainingTaskSpec(
            task_id="daily-base-target-v1",
            kind=TrainingTaskKind.BASE_TARGET,
            label_name="next_open_up_1d",
            horizon_bars=1,
            score_semantics=ScoreSemantics.PROBABILITY,
            universe_id="s1-fixture",
            execution_policy_id="a-share-next-open-v1",
            evaluation_metrics=("auc", "net_return"),
        ),
        model_kind="LIGHTGBM_BINARY",
        target_column="label",
    )
    response_path = tmp_path / "response.json"
    response_path.write_text(
        json.dumps(
            {
                "schema_version": "astraquant.qlib-response/v1",
                "request_content_digest": export.content_digest,
                "upstream_commit": "79633dd9506ea689e5400dea0197717b5b3d74b7",
                "model": "qlib.contrib.model.gbdt.LGBModel",
                "predictions": [
                    {
                        "fold_id": fold.fold_id,
                        "row_id": row_id,
                        "probability": 0.9 if int(rows[row_id]["label"]) else 0.1,
                    }
                    for fold in folds
                    for row_id in fold.test_indices
                ],
            }
        ),
        encoding="utf-8",
    )
    native_path = tmp_path / "native.json"
    _native_report(native_path, rows, folds)
    output_path = tmp_path / "comparison.json"

    assert (
        main(
            [
                str(export.request_path),
                str(response_path),
                str(native_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == "astraquant.qlib-comparison/v1"
    assert result["shared_contract"] == {
        "dataset_id": "s1-fixture",
        "fee_rate": "0.001",
        "fold_count": 2,
        "prediction_threshold": 0.5,
        "source_snapshot_id": "1" * 64,
        "test_rows": 10,
    }
    assert result["qlib_lightgbm"]["auc"] == 1.0
    assert set(result["delta_qlib_minus_native"]) == {
        "auc",
        "gross_return",
        "net_return",
        "trades",
    }

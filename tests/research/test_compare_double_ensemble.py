from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from astraquant_data.exports.qlib import QLIB_UPSTREAM_COMMIT, export_qlib_request
from astraquant_domain import ScoreSemantics, TrainingTaskKind, TrainingTaskSpec
from astraquant_quant.baseline_matrix import expanding_walk_forward
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS
from tools.research.compare_double_ensemble import main


def _rows(count: int = 80) -> list[dict[str, float | int]]:
    return [
        {
            **{
                name: (index + position) / 100
                for position, name in enumerate(MODEL_FEATURE_COLUMNS)
            },
            "label": index % 2,
            "future_return": 0.01 if index % 2 else -0.01,
        }
        for index in range(count)
    ]


def test_compare_double_ensemble_uses_one_expected_return_selection_policy(
    tmp_path: Path,
) -> None:
    rows = _rows()
    folds = expanding_walk_forward(rows, minimum_train_size=40, test_size=10, fold_count=3)
    task = TrainingTaskSpec(
        task_id="daily-expected-return-v1",
        kind=TrainingTaskKind.BASE_TARGET,
        label_name="next_open_return_1d",
        horizon_bars=1,
        score_semantics=ScoreSemantics.EXPECTED_RETURN,
        universe_id="shared-panel-v1",
        execution_policy_id="a-share-next-open-v1",
        evaluation_metrics=("rank_ic", "research_net_return"),
    )
    exported = export_qlib_request(
        output_root=tmp_path / "export",
        dataset_id="shared-panel-v1",
        source_snapshot_id="a" * 64,
        provider_id="eastmoney",
        rows=rows,
        folds=folds,
        fee_rate=Decimal("0.00025"),
        prediction_threshold=None,
        seed=7,
        training_task=task,
        model_kind="DOUBLE_ENSEMBLE",
        target_column="future_return",
    )
    response_path = tmp_path / "response.json"
    response_path.write_text(
        json.dumps(
            {
                "schema_version": "astraquant.qlib-response/v1",
                "request_content_digest": exported.content_digest,
                "upstream_commit": QLIB_UPSTREAM_COMMIT,
                "model": "qlib.contrib.model.double_ensemble.DEnsembleModel",
                "model_kind": "DOUBLE_ENSEMBLE",
                "score_semantics": "EXPECTED_RETURN",
                "training_task_digest": task.task_digest,
                "predictions": [
                    {
                        "fold_id": fold.fold_id,
                        "row_id": row_id,
                        "score": float(rows[row_id]["future_return"]),
                    }
                    for fold in folds
                    for row_id in fold.test_indices
                ],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "comparison.json"

    assert (
        main(
            [
                str(exported.request_path),
                str(response_path),
                "--minimum-edge",
                "0.0005",
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == "astraquant.double-ensemble-comparison/v1"
    assert result["shared_contract"]["training_task_digest"] == task.task_digest
    assert result["shared_contract"]["selection_policy"] == {
        "kind": "EXPECTED_RETURN_GTE_ROUND_TRIP_FEE_PLUS_EDGE",
        "minimum_edge": "0.0005",
        "selection_cutoff": "0.00100",
    }
    assert result["double_ensemble"]["auc"] == 1.0
    assert set(result["delta_double_ensemble_minus_ridge"]) == {
        "auc",
        "gross_return",
        "net_return",
        "trades",
    }

from __future__ import annotations

from decimal import Decimal

import pytest

from astraquant_quant.baseline_matrix import (
    BaselineModel,
    MatrixStatus,
    expanding_walk_forward,
    run_baseline_matrix,
    score_fold_predictions,
)
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS


def _rows(count: int) -> list[dict[str, float | int]]:
    return [
        {
            "close": float(index),
            "return_1": 0.0,
            "label": index % 2,
            "future_return": 0.01 if index % 2 else -0.01,
        }
        for index in range(count)
    ]


def test_expanding_walk_forward_uses_ordered_shared_test_windows() -> None:
    folds = expanding_walk_forward(
        _rows(75),
        minimum_train_size=40,
        test_size=10,
        fold_count=3,
    )

    assert [fold.fold_id for fold in folds] == ["fold-01", "fold-02", "fold-03"]
    assert [len(fold.train_indices) for fold in folds] == [45, 55, 65]
    assert [len(fold.test_indices) for fold in folds] == [10, 10, 10]
    for fold in folds:
        assert max(fold.train_indices) < min(fold.test_indices)


def test_expanding_walk_forward_rejects_insufficient_history() -> None:
    with pytest.raises(ValueError, match="insufficient rows"):
        expanding_walk_forward(
            _rows(69),
            minimum_train_size=40,
            test_size=10,
            fold_count=3,
        )


def _model_rows(count: int, *, force_loss: bool = False) -> list[dict[str, float | int]]:
    rows = []
    for index in range(count):
        label = 1 if index % 4 >= 2 else 0
        signal = 1.0 if label else -1.0
        row: dict[str, float | int] = {
            name: signal * (position + 1) / 10
            for position, name in enumerate(MODEL_FEATURE_COLUMNS)
        }
        row.update(
            {
                "label": label,
                "future_return": -0.01 if force_loss else (0.01 if label else -0.01),
            }
        )
        rows.append(row)
    return rows


def test_all_models_use_identical_folds_and_produce_deterministic_metrics() -> None:
    rows = _model_rows(120)
    folds = expanding_walk_forward(
        rows,
        minimum_train_size=60,
        test_size=20,
        fold_count=3,
    )

    first = run_baseline_matrix(
        rows,
        folds=folds,
        fee_rate=Decimal("0.00025"),
        prediction_threshold=0.5,
        seed=7,
    )
    second = run_baseline_matrix(
        rows,
        folds=folds,
        fee_rate=Decimal("0.00025"),
        prediction_threshold=0.5,
        seed=7,
    )

    assert first == second
    assert {summary.model for summary in first.models} == set(BaselineModel)
    expected_fold_ids = tuple(fold.fold_id for fold in folds)
    for summary in first.models:
        assert tuple(metric.fold_id for metric in summary.folds) == expected_fold_ids
        assert all(metric.test_rows == 20 for metric in summary.folds)
        assert 0.0 <= summary.auc <= 1.0
        assert summary.trades >= 0
    assert first.status is MatrixStatus.CHALLENGER
    assert first.challenger in set(BaselineModel)


def test_matrix_reports_no_edge_when_every_model_lacks_positive_net_return() -> None:
    rows = _model_rows(120, force_loss=True)
    folds = expanding_walk_forward(
        rows,
        minimum_train_size=60,
        test_size=20,
        fold_count=3,
    )

    report = run_baseline_matrix(
        rows,
        folds=folds,
        fee_rate=Decimal("0.00025"),
        prediction_threshold=0.5,
        seed=7,
    )

    assert report.status is MatrixStatus.NO_EDGE
    assert report.challenger is None
    assert all(summary.net_return <= 0 for summary in report.models)


def test_external_predictions_use_the_same_auc_fee_and_return_scorer() -> None:
    rows = _model_rows(12)
    folds = expanding_walk_forward(rows, minimum_train_size=4, test_size=4, fold_count=2)
    predictions = [
        {
            "fold_id": fold.fold_id,
            "row_id": row_id,
            "probability": 0.9 if int(rows[row_id]["label"]) else 0.1,
        }
        for fold in folds
        for row_id in fold.test_indices
    ]

    summary = score_fold_predictions(
        rows,
        folds=folds,
        predictions=predictions,
        fee_rate=Decimal("0.001"),
        prediction_threshold=0.5,
    )

    assert summary.auc == 1.0
    assert summary.trades == 4
    assert summary.gross_return == pytest.approx(0.04)
    assert summary.net_return == pytest.approx(0.032)

    with pytest.raises(ValueError, match="coverage"):
        score_fold_predictions(
            rows,
            folds=folds,
            predictions=predictions[:-1],
            fee_rate=Decimal("0.001"),
            prediction_threshold=0.5,
        )

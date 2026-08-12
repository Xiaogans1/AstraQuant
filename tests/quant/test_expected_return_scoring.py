from decimal import Decimal

import pytest

from astraquant_quant.baseline_matrix import (
    WalkForwardFold,
    score_expected_return_predictions,
)
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS


def _rows() -> list[dict[str, float | int]]:
    future_returns = (-0.02, 0.004, 0.03, -0.01)
    return [
        {
            **{name: float(index) for name in MODEL_FEATURE_COLUMNS},
            "label": int(future_return > 0),
            "future_return": future_return,
        }
        for index, future_return in enumerate(future_returns)
    ]


def test_expected_return_scores_use_a_declared_round_trip_cost_cutoff() -> None:
    summary = score_expected_return_predictions(
        _rows(),
        folds=(
            WalkForwardFold(
                fold_id="fold-01",
                train_indices=(0, 1),
                test_indices=(2, 3),
            ),
        ),
        predictions=(
            {"fold_id": "fold-01", "row_id": 2, "score": 0.02},
            {"fold_id": "fold-01", "row_id": 3, "score": 0.001},
        ),
        fee_rate=Decimal("0.001"),
        minimum_edge=Decimal("0.001"),
    )

    assert summary.trades == 1
    assert summary.gross_return == pytest.approx(0.03)
    assert summary.net_return == pytest.approx(0.028)
    assert summary.auc == pytest.approx(1.0)


def test_expected_return_scoring_rejects_probability_shaped_or_incomplete_output() -> None:
    fold = WalkForwardFold("fold-01", (0, 1), (2, 3))

    with pytest.raises(ValueError, match="expected-return prediction"):
        score_expected_return_predictions(
            _rows(),
            folds=(fold,),
            predictions=(
                {"fold_id": "fold-01", "row_id": 2, "probability": 0.9},
                {"fold_id": "fold-01", "row_id": 3, "probability": 0.1},
            ),
            fee_rate=Decimal("0.001"),
            minimum_edge=Decimal("0"),
        )

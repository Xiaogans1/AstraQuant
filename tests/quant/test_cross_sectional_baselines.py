from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from astraquant_quant.cross_sectional_baselines import (
    CrossSectionalBaselineRow,
    CrossSectionalModelKind,
    run_cross_sectional_baseline,
    score_cross_sectional_predictions,
)
from astraquant_quant.cross_sectional_splits import (
    assign_cross_sectional_fold_rows,
    build_cross_sectional_folds,
)


def _rows() -> tuple[CrossSectionalBaselineRow, ...]:
    start = datetime(2020, 1, 2, 7, tzinfo=UTC)
    sessions = tuple(start + timedelta(days=index) for index in range(65))
    rows: list[CrossSectionalBaselineRow] = []
    for session_index, session in enumerate(sessions):
        for instrument_index in range(10):
            rank = instrument_index / 9
            signal = rank + math.sin(session_index / 5) * 0.01
            rows.append(
                CrossSectionalBaselineRow(
                    row_id=len(rows),
                    decision_time=session,
                    instrument_id=f"S{instrument_index:03d}.SSE",
                    horizon_sessions=5,
                    features={
                        "ALPHA_SIGNAL": signal,
                        "MISSING_FEATURE": (
                            float("nan") if instrument_index % 4 == 0 else rank * 2
                        ),
                        "market_breadth": 0.4 + session_index / 1000,
                    },
                    cross_sectional_rank=rank,
                    market_excess_return=(rank - 0.5) * 0.02,
                    training_eligible=instrument_index not in (0, 9),
                )
            )
    return tuple(rows)


def _assignment(rows: tuple[CrossSectionalBaselineRow, ...]):  # type: ignore[no-untyped-def]
    sessions = tuple(sorted({row.decision_time for row in rows}))
    fold = build_cross_sectional_folds(
        sessions,
        horizons=(1, 5, 10),
        minimum_fit_sessions=20,
        inner_valid_sessions=5,
        outer_test_sessions=5,
        fold_count=3,
        purge_sessions=11,
    )[0]
    return assign_cross_sectional_fold_rows(rows, (fold,))[0]


@pytest.mark.parametrize(
    "model_kind",
    [CrossSectionalModelKind.RIDGE, CrossSectionalModelKind.LIGHTGBM],
)
def test_baselines_are_deterministic_and_learn_cross_sectional_rank(
    model_kind: CrossSectionalModelKind,
) -> None:
    rows = _rows()
    assignment = _assignment(rows)

    first = run_cross_sectional_baseline(
        rows,
        assignment=assignment,
        model_kind=model_kind,
        seed=7,
    )
    second = run_cross_sectional_baseline(
        rows,
        assignment=assignment,
        model_kind=model_kind,
        seed=7,
    )

    assert first == second
    assert first.prediction_digest == second.prediction_digest
    assert len(first.predictions) == len(assignment.outer_test_indices)
    assert first.mean_rank_ic > 0.9
    assert first.mean_ic > 0.9
    assert first.mean_top_bottom_spread > 0
    assert first.positive_rank_ic_sessions == first.evaluated_sessions
    assert first.calibration_policy_digest.startswith("sha256:")
    assert all(math.isfinite(item.calibrated_expected_return) for item in first.predictions)


def test_outer_labels_cannot_change_predictions_or_calibration() -> None:
    rows = _rows()
    assignment = _assignment(rows)
    first = run_cross_sectional_baseline(
        rows,
        assignment=assignment,
        model_kind=CrossSectionalModelKind.RIDGE,
        seed=7,
    )
    mutated = list(rows)
    for index in assignment.outer_test_indices:
        mutated[index] = replace(
            mutated[index],
            cross_sectional_rank=1 - mutated[index].cross_sectional_rank,
            market_excess_return=-1000 * mutated[index].market_excess_return,
        )

    second = run_cross_sectional_baseline(
        tuple(mutated),
        assignment=assignment,
        model_kind=CrossSectionalModelKind.RIDGE,
        seed=7,
    )

    assert first.prediction_digest == second.prediction_digest
    assert first.calibrator_digest == second.calibrator_digest
    assert first.mean_rank_ic != second.mean_rank_ic


def test_train_ineligible_tails_never_enter_model_fit() -> None:
    rows = _rows()
    assignment = _assignment(rows)
    first = run_cross_sectional_baseline(
        rows,
        assignment=assignment,
        model_kind=CrossSectionalModelKind.RIDGE,
        seed=7,
    )
    mutated = list(rows)
    for index in assignment.fit_indices:
        if not mutated[index].training_eligible:
            mutated[index] = replace(
                mutated[index],
                features={name: 999999.0 for name in mutated[index].features},
                cross_sectional_rank=0.5,
                market_excess_return=999999.0,
            )

    second = run_cross_sectional_baseline(
        tuple(mutated),
        assignment=assignment,
        model_kind=CrossSectionalModelKind.RIDGE,
        seed=7,
    )

    assert first.prediction_digest == second.prediction_digest
    assert first.processor_digest == second.processor_digest


def test_baseline_rejects_feature_schema_horizon_and_nonfinite_target() -> None:
    rows = list(_rows())
    assignment = _assignment(tuple(rows))
    rows[0] = replace(rows[0], features={"OTHER": 1.0})
    with pytest.raises(ValueError, match="feature schema"):
        run_cross_sectional_baseline(
            tuple(rows),
            assignment=assignment,
            model_kind=CrossSectionalModelKind.RIDGE,
            seed=7,
        )

    rows = list(_rows())
    rows[-1] = replace(rows[-1], horizon_sessions=10)
    with pytest.raises(ValueError, match="horizon"):
        run_cross_sectional_baseline(
            tuple(rows),
            assignment=_assignment(_rows()),
            model_kind=CrossSectionalModelKind.RIDGE,
            seed=7,
        )

    rows = list(_rows())
    rows[0] = replace(rows[0], market_excess_return=float("inf"))
    with pytest.raises(ValueError, match="target"):
        run_cross_sectional_baseline(
            tuple(rows),
            assignment=assignment,
            model_kind=CrossSectionalModelKind.RIDGE,
            seed=7,
        )


def test_external_double_ensemble_scores_use_inner_valid_for_calibration_only() -> None:
    rows = _rows()
    assignment = _assignment(rows)
    valid_scores = tuple(
        rows[index].features["ALPHA_SIGNAL"] for index in assignment.inner_valid_indices
    )
    test_scores = tuple(
        rows[index].features["ALPHA_SIGNAL"] for index in assignment.outer_test_indices
    )

    result = score_cross_sectional_predictions(
        rows,
        assignment=assignment,
        model_kind=CrossSectionalModelKind.DOUBLE_ENSEMBLE,
        seed=7,
        valid_scores=valid_scores,
        test_scores=test_scores,
        processor_digest="sha256:" + "1" * 64,
        model_digest="sha256:" + "2" * 64,
    )

    assert result.model_kind is CrossSectionalModelKind.DOUBLE_ENSEMBLE
    assert result.model_digest == "sha256:" + "2" * 64
    assert result.mean_rank_ic > 0.9
    assert result.predictions[0].row_id == rows[assignment.outer_test_indices[0]].row_id

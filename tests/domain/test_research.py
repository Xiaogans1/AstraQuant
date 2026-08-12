from dataclasses import replace
from typing import Any

import pytest

from astraquant_domain import ScoreSemantics, TrainingTaskKind, TrainingTaskSpec


def _task(**overrides: object) -> TrainingTaskSpec:
    values: dict[str, Any] = {
        "task_id": "daily-base-target-v1",
        "kind": TrainingTaskKind.BASE_TARGET,
        "label_name": "next_open_return_5d",
        "horizon_bars": 5,
        "score_semantics": ScoreSemantics.EXPECTED_RETURN,
        "universe_id": "csi-all-a-pit-v1",
        "execution_policy_id": "a-share-next-open-v1",
        "evaluation_metrics": ("net_return", "rank_ic", "max_drawdown"),
    }
    values.update(overrides)
    return TrainingTaskSpec(**values)


def test_training_contract_exposes_all_planned_task_and_score_kinds() -> None:
    assert {kind.value for kind in TrainingTaskKind} == {
        "BASE_TARGET",
        "CROSS_SECTIONAL_ROTATION",
        "TREND",
        "MEAN_REVERSION",
        "INTRADAY_T",
        "RISK",
    }
    assert {semantics.value for semantics in ScoreSemantics} == {
        "PROBABILITY",
        "EXPECTED_RETURN",
        "CROSS_SECTIONAL_RANK",
        "RISK_SCORE",
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("task_id", " ", "task_id"),
        ("label_name", "", "label_name"),
        ("horizon_bars", 0, "horizon_bars"),
        ("universe_id", "", "universe_id"),
        ("execution_policy_id", "", "execution_policy_id"),
        ("evaluation_metrics", (), "evaluation_metrics"),
    ],
)
def test_training_task_rejects_incomplete_semantics(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _task(**{field: value})


def test_task_digest_is_stable_and_metric_order_independent() -> None:
    first = _task(evaluation_metrics=("rank_ic", "net_return", "max_drawdown"))
    second = _task(evaluation_metrics=("max_drawdown", "rank_ic", "net_return"))

    assert first.evaluation_metrics == (
        "max_drawdown",
        "net_return",
        "rank_ic",
    )
    assert first.task_digest == second.task_digest
    assert first.task_digest.startswith("sha256:")
    assert len(first.task_digest) == len("sha256:") + 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", TrainingTaskKind.TREND),
        ("label_name", "next_open_return_10d"),
        ("horizon_bars", 10),
        ("score_semantics", ScoreSemantics.PROBABILITY),
        ("universe_id", "csi-300-pit-v1"),
        ("execution_policy_id", "a-share-next-close-v1"),
    ],
)
def test_comparison_rejects_any_training_semantics_mismatch(
    field: str,
    value: object,
) -> None:
    baseline = _task()
    changes: dict[str, Any] = {field: value}
    challenger = replace(baseline, **changes)

    with pytest.raises(ValueError, match=field):
        baseline.assert_comparable_with(challenger)


def test_models_can_compare_when_the_training_task_is_identical() -> None:
    baseline = _task()
    challenger = _task()

    baseline.assert_comparable_with(challenger)
    assert baseline.task_digest == challenger.task_digest

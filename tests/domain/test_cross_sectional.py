from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from astraquant_domain import (
    CrossSectionalTaskMatrix,
    RankPortfolioPolicy,
    ReturnCalibrationPolicy,
)


def test_stage_b_v2_contract_has_stable_identity() -> None:
    first = CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI")
    second = CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI")

    assert first.horizons == (1, 5, 10)
    assert first.entry_lag_sessions == 1
    assert first.extreme_tail_fraction == Decimal("0.025")
    assert first.task_digest == second.task_digest
    assert first.task_digest.startswith("sha256:")


def test_rank_policy_freezes_strategy_semantics() -> None:
    policy = RankPortfolioPolicy.stage_b_v2()

    assert policy.top_fraction == Decimal("0.10")
    assert policy.max_positions == 50
    assert policy.max_instrument_weight == Decimal("0.03")
    assert policy.max_one_way_turnover == Decimal("0.20")
    assert policy.policy_digest.startswith("sha256:")


@pytest.mark.parametrize("horizons", [(1, 1), (5, 1), ()])
def test_task_matrix_rejects_noncanonical_horizons(horizons: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="horizons"):
        CrossSectionalTaskMatrix(
            schema_version="astraquant.cross-sectional-task/v1",
            benchmark_instrument_id="000985.CSI",
            horizons=horizons,
            entry_lag_sessions=1,
            extreme_tail_fraction=Decimal("0.025"),
        )


def test_calibration_policy_only_accepts_inner_valid() -> None:
    policy = ReturnCalibrationPolicy.stage_b_v2()

    assert policy.fit_segment == "inner_valid"
    assert policy.calibration_digest.startswith("sha256:")
    with pytest.raises(ValueError, match="inner_valid"):
        replace(policy, fit_segment="outer_test")


def test_task_matrix_rejects_invalid_values() -> None:
    policy = CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI")
    with pytest.raises(ValueError):
        replace(policy, entry_lag_sessions=0)
    with pytest.raises(ValueError):
        replace(policy, extreme_tail_fraction=Decimal("0.5"))
    with pytest.raises(ValueError):
        replace(policy, extreme_tail_fraction=Decimal("NaN"))
    with pytest.raises(ValueError):
        replace(policy, benchmark_instrument_id="")


def test_rank_policy_rejects_invalid_values() -> None:
    policy = RankPortfolioPolicy.stage_b_v2()
    with pytest.raises(ValueError):
        replace(policy, top_fraction=Decimal("0"))
    with pytest.raises(ValueError):
        replace(policy, max_positions=0)
    with pytest.raises(ValueError):
        replace(policy, max_instrument_weight=Decimal("1.1"))
    with pytest.raises(ValueError):
        replace(policy, max_one_way_turnover=Decimal("Infinity"))

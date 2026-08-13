from __future__ import annotations

import math
from dataclasses import replace
from decimal import Decimal

import pytest

from astraquant_domain import RankPortfolioPolicy
from astraquant_quant.rank_portfolio import (
    RankedForecast,
    build_rank_portfolio_target,
)


def _forecast(
    index: int,
    *,
    expected_return: float = 0.01,
    volatility: float = 0.20,
    tradable: bool = True,
) -> RankedForecast:
    return RankedForecast(
        forecast_id=f"forecast-{index:03d}",
        instrument_id=f"S{index:03d}.SSE",
        rank_score=float(1000 - index),
        calibrated_expected_return=expected_return,
        trailing_volatility=volatility,
        tradable=tradable,
    )


def _forecasts(count: int) -> list[RankedForecast]:
    return [_forecast(index) for index in range(count)]


def test_stage_b_v2_selects_top_ten_percent_and_leaves_unallocatable_cash() -> None:
    target = build_rank_portfolio_target(
        forecasts=_forecasts(40),
        current_weights={},
        policy=RankPortfolioPolicy.stage_b_v2(),
    )

    assert len(target.selected_instruments) == 4
    assert all(weight <= Decimal("0.03") for weight in target.target_weights.values())
    assert target.cash_weight == Decimal("0.88")
    assert target.cash_weight + sum(target.target_weights.values()) == 1


def test_negative_forecast_in_top_quota_is_removed_without_backfill() -> None:
    forecasts = _forecasts(40)
    forecasts[0] = _forecast(0, expected_return=-0.01)

    target = build_rank_portfolio_target(
        forecasts=forecasts,
        current_weights={},
        policy=RankPortfolioPolicy.stage_b_v2(),
    )

    assert "S000.SSE" not in target.target_weights
    assert "S004.SSE" not in target.target_weights
    assert target.selected_instruments == ("S001.SSE", "S002.SSE", "S003.SSE")


def test_inverse_volatility_gives_lower_risk_a_larger_uncapped_weight() -> None:
    policy = replace(
        RankPortfolioPolicy.stage_b_v2(),
        top_fraction=Decimal("1"),
        max_instrument_weight=Decimal("1"),
        max_one_way_turnover=Decimal("1"),
    )
    forecasts = [
        _forecast(0, volatility=0.10),
        _forecast(1, volatility=0.20),
    ]

    target = build_rank_portfolio_target(
        forecasts=forecasts,
        current_weights={},
        policy=policy,
    )

    assert target.target_weights["S000.SSE"] > target.target_weights["S001.SSE"]
    assert target.cash_weight == 0


def test_input_permutation_has_the_same_target_identity() -> None:
    forecasts = _forecasts(40)

    first = build_rank_portfolio_target(
        forecasts=forecasts,
        current_weights={"OLD.SSE": Decimal("0.05")},
        policy=RankPortfolioPolicy.stage_b_v2(),
    )
    second = build_rank_portfolio_target(
        forecasts=list(reversed(forecasts)),
        current_weights={"OLD.SSE": Decimal("0.05")},
        policy=RankPortfolioPolicy.stage_b_v2(),
    )

    assert first.target_digest == second.target_digest
    assert first == second


def test_nontradable_forecast_never_enters_selection() -> None:
    forecasts = _forecasts(40)
    forecasts[0] = _forecast(0, tradable=False)

    target = build_rank_portfolio_target(
        forecasts=forecasts,
        current_weights={},
        policy=RankPortfolioPolicy.stage_b_v2(),
    )

    assert "S000.SSE" not in target.target_weights


def test_current_holding_outside_selection_targets_zero_when_turnover_allows() -> None:
    target = build_rank_portfolio_target(
        forecasts=_forecasts(40),
        current_weights={"OLD.SSE": Decimal("0.10")},
        policy=RankPortfolioPolicy.stage_b_v2(),
    )

    assert "OLD.SSE" not in target.target_weights
    assert target.one_way_turnover <= Decimal("0.20")


def test_target_interpolates_all_assets_when_turnover_exceeds_limit() -> None:
    target = build_rank_portfolio_target(
        forecasts=_forecasts(40),
        current_weights={"OLD.SSE": Decimal("1")},
        policy=RankPortfolioPolicy.stage_b_v2(),
    )

    assert target.one_way_turnover <= Decimal("0.20")
    assert target.target_weights["OLD.SSE"] > Decimal("0")
    assert target.cash_weight + sum(target.target_weights.values()) == 1


@pytest.mark.parametrize(
    "forecasts",
    [
        [],
        [_forecast(index, expected_return=-0.01) for index in range(10)],
    ],
)
def test_empty_or_negative_edge_input_returns_all_cash(
    forecasts: list[RankedForecast],
) -> None:
    target = build_rank_portfolio_target(
        forecasts=forecasts,
        current_weights={},
        policy=RankPortfolioPolicy.stage_b_v2(),
    )

    assert target.selected_instruments == ()
    assert dict(target.target_weights) == {}
    assert target.cash_weight == 1


def test_duplicate_instruments_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate instrument"):
        build_rank_portfolio_target(
            forecasts=[_forecast(0), replace(_forecast(1), instrument_id="S000.SSE")],
            current_weights={},
            policy=RankPortfolioPolicy.stage_b_v2(),
        )


@pytest.mark.parametrize("rank_score", [math.nan, math.inf, -math.inf])
def test_non_finite_rank_score_fails_closed(rank_score: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        build_rank_portfolio_target(
            forecasts=[replace(_forecast(0), rank_score=rank_score)],
            current_weights={},
            policy=RankPortfolioPolicy.stage_b_v2(),
        )


def test_zero_volatility_fails_closed() -> None:
    with pytest.raises(ValueError, match="volatility"):
        build_rank_portfolio_target(
            forecasts=[_forecast(0, volatility=0.0)],
            current_weights={},
            policy=RankPortfolioPolicy.stage_b_v2(),
        )


@pytest.mark.parametrize(
    "current_weights",
    [
        {"OLD.SSE": Decimal("1.01")},
        {"A.SSE": Decimal("0.60"), "B.SSE": Decimal("0.50")},
        {"OLD.SSE": Decimal("NaN")},
    ],
)
def test_invalid_current_weights_fail_closed(
    current_weights: dict[str, Decimal],
) -> None:
    with pytest.raises(ValueError, match="current weights"):
        build_rank_portfolio_target(
            forecasts=_forecasts(40),
            current_weights=current_weights,
            policy=RankPortfolioPolicy.stage_b_v2(),
        )

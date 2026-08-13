from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_domain import RankPortfolioPolicy
from astraquant_quant.cross_sectional_portfolio import (
    CrossSectionalPortfolioRow,
    evaluate_cross_sectional_portfolio,
)
from astraquant_quant.executable_backtest import ExecutionPolicy


def _rows() -> tuple[CrossSectionalPortfolioRow, ...]:
    start = datetime(2024, 1, 2, 7, tzinfo=UTC)
    rows: list[CrossSectionalPortfolioRow] = []
    for session_index in range(15):
        for instrument_index in range(10):
            strength = instrument_index / 9
            rows.append(
                CrossSectionalPortfolioRow(
                    row_id=len(rows),
                    decision_time=start + timedelta(days=session_index),
                    instrument_id=f"S{instrument_index:03d}.SSE",
                    horizon_sessions=5,
                    rank_score=strength,
                    calibrated_expected_return=(strength - 0.5) * 0.02,
                    raw_return=(strength - 0.5) * 0.03,
                    trailing_volatility=0.2,
                    median_daily_turnover=Decimal("100000000"),
                    tradable=True,
                )
            )
    return tuple(rows)


def test_portfolio_applies_rank_target_real_fees_capacity_and_nonoverlap() -> None:
    result = evaluate_cross_sectional_portfolio(
        _rows(),
        portfolio_policy=RankPortfolioPolicy.stage_b_v2(),
        execution_policy=ExecutionPolicy(initial_cash=Decimal("1000000")),
    )

    assert result.period_count == 3
    assert result.gross_return > result.net_return > 0
    assert result.one_way_turnover > 0
    assert result.commission > 0
    assert result.stamp_duty > 0
    assert result.transfer_fee > 0
    assert result.slippage_cost > 0
    assert 0 < result.max_drawdown < 0.001
    assert result.capacity_breaches == 0
    assert result.minimum_capacity_ratio > 1
    assert result.content_digest.startswith("sha256:")
    assert result == evaluate_cross_sectional_portfolio(
        _rows(),
        portfolio_policy=RankPortfolioPolicy.stage_b_v2(),
        execution_policy=ExecutionPolicy(initial_cash=Decimal("1000000")),
    )


def test_portfolio_reports_capacity_breach_and_rejects_overlapping_identity() -> None:
    rows = list(_rows())
    rows[9] = CrossSectionalPortfolioRow(
        row_id=rows[9].row_id,
        decision_time=rows[9].decision_time,
        instrument_id=rows[9].instrument_id,
        horizon_sessions=rows[9].horizon_sessions,
        rank_score=rows[9].rank_score,
        calibrated_expected_return=rows[9].calibrated_expected_return,
        raw_return=rows[9].raw_return,
        trailing_volatility=rows[9].trailing_volatility,
        median_daily_turnover=Decimal("100"),
        tradable=True,
    )

    result = evaluate_cross_sectional_portfolio(
        rows,
        portfolio_policy=RankPortfolioPolicy.stage_b_v2(),
        execution_policy=ExecutionPolicy(initial_cash=Decimal("1000000")),
    )
    assert result.capacity_breaches > 0
    assert 0 < result.minimum_capacity_ratio < 1

    rows.append(rows[0])
    try:
        evaluate_cross_sectional_portfolio(
            rows,
            portfolio_policy=RankPortfolioPolicy.stage_b_v2(),
            execution_policy=ExecutionPolicy(),
        )
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("duplicate portfolio identity was accepted")

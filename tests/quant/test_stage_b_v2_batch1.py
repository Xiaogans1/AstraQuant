from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_domain import (
    CrossSectionalTaskMatrix,
    RankPortfolioPolicy,
    ReturnCalibrationPolicy,
)
from astraquant_quant.cross_sectional_labels import (
    DailyCrossSectionalPanel,
    build_daily_cross_sectional_labels,
)
from astraquant_quant.rank_portfolio import (
    RankedForecast,
    build_rank_portfolio_target,
)
from astraquant_quant.return_calibration import (
    CalibrationSample,
    fit_huber_linear,
)


def _bar(timestamp: datetime, price: Decimal) -> MarketBar:
    return MarketBar(
        timestamp=timestamp,
        open=price,
        high=price * Decimal("1.02"),
        low=price * Decimal("0.98"),
        close=price * Decimal("1.005"),
        volume=Decimal("1000000"),
        turnover=price * Decimal("1000000"),
    )


def _panel() -> DailyCrossSectionalPanel:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    sessions = tuple(start + timedelta(days=index) for index in range(13))
    instruments = tuple(f"S{index:03d}.SSE" for index in range(50))
    instrument_bars = {
        instrument_id: {
            session: _bar(
                session,
                Decimal("100")
                + instrument_index
                + session_index * Decimal(instrument_index + 1),
            )
            for session_index, session in enumerate(sessions)
        }
        for instrument_index, instrument_id in enumerate(instruments)
    }
    return DailyCrossSectionalPanel(
        sessions=sessions,
        instrument_bars=instrument_bars,
        benchmark_bars={
            session: _bar(session, Decimal("1000") + session_index)
            for session_index, session in enumerate(sessions)
        },
        eligible_by_session={session: frozenset(instruments) for session in sessions},
    )


def test_stage_b_v2_batch1_label_calibration_and_target_flow() -> None:
    panel = _panel()
    labels = build_daily_cross_sectional_labels(
        panel,
        CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI"),
    )
    inner_valid = [
        row
        for row in labels
        if row.decision_time == panel.sessions[0]
        and row.horizon_sessions == 5
        and row.training_eligible
    ]
    samples = [
        CalibrationSample(
            score=float(row.cross_sectional_rank),
            realized_return=float(row.market_excess_return),
        )
        for row in inner_valid
    ]
    calibrator = fit_huber_linear(
        samples,
        policy=ReturnCalibrationPolicy.stage_b_v2(),
        segment="inner_valid",
    )
    forecasts = [
        RankedForecast(
            forecast_id=f"stage-b-v2:{row.instrument_id}",
            instrument_id=row.instrument_id,
            rank_score=float(row.cross_sectional_rank),
            calibrated_expected_return=calibrator.predict(
                float(row.cross_sectional_rank)
            ),
            trailing_volatility=0.10 + index / 1000,
            tradable=True,
        )
        for index, row in enumerate(inner_valid)
    ]
    target = build_rank_portfolio_target(
        forecasts=forecasts,
        current_weights={},
        policy=RankPortfolioPolicy.stage_b_v2(),
    )

    assert {row.horizon_sessions for row in labels} == {1, 5, 10}
    assert all(row.entry_time > row.decision_time for row in labels)
    assert target.selected_instruments == tuple(sorted(target.target_weights))
    assert target.cash_weight + sum(target.target_weights.values()) == Decimal("1")
    assert target.one_way_turnover <= Decimal("0.20")

    outer_test_returns = [
        row.market_excess_return
        for row in labels
        if row.decision_time == panel.sessions[0] and row.horizon_sessions == 10
    ]
    outer_test_returns[:] = [value * Decimal("-1000") for value in outer_test_returns]
    repeated_calibrator = fit_huber_linear(
        samples,
        policy=ReturnCalibrationPolicy.stage_b_v2(),
        segment="inner_valid",
    )
    repeated_forecasts = [
        RankedForecast(
            forecast_id=forecast.forecast_id,
            instrument_id=forecast.instrument_id,
            rank_score=forecast.rank_score,
            calibrated_expected_return=repeated_calibrator.predict(forecast.rank_score),
            trailing_volatility=forecast.trailing_volatility,
            tradable=forecast.tradable,
        )
        for forecast in forecasts
    ]
    repeated_target = build_rank_portfolio_target(
        forecasts=repeated_forecasts,
        current_weights={},
        policy=RankPortfolioPolicy.stage_b_v2(),
    )

    assert outer_test_returns
    assert repeated_calibrator == calibrator
    assert repeated_target.target_digest == target.target_digest

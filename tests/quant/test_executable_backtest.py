from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_data.market_bars import MarketBar
from astraquant_quant.baseline_matrix import WalkForwardFold
from astraquant_quant.executable_backtest import (
    ExecutionPolicy,
    InstrumentKind,
    run_executable_backtest,
)


def _bars(
    opens: list[str],
    *,
    volumes: list[str] | None = None,
) -> list[MarketBar]:
    start = datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    exact_volumes = volumes or ["100000"] * len(opens)
    return [
        MarketBar(
            timestamp=start + timedelta(minutes=index),
            open=Decimal(price),
            high=Decimal(price),
            low=Decimal(price),
            close=Decimal(price),
            volume=Decimal(exact_volumes[index]),
            turnover=Decimal(price) * Decimal(exact_volumes[index]),
        )
        for index, price in enumerate(opens)
    ]


def _fold(count: int) -> tuple[WalkForwardFold, ...]:
    return (
        WalkForwardFold(
            fold_id="fold-01",
            train_indices=(),
            test_indices=tuple(range(count)),
        ),
    )


def _predictions(count: int) -> list[dict[str, object]]:
    return [{"fold_id": "fold-01", "row_id": row_id, "probability": 0.9} for row_id in range(count)]


def _policy(kind: InstrumentKind = InstrumentKind.STOCK, **changes: object) -> ExecutionPolicy:
    values: dict[str, object] = {
        "initial_cash": Decimal("10000"),
        "commission_rate": Decimal("0.00025"),
        "minimum_commission": Decimal("5"),
        "stamp_duty_rate": Decimal("0.0005"),
        "transfer_fee_rate": Decimal("0.00001"),
        "slippage_bps": Decimal("0"),
        "participation_rate": Decimal("1"),
        "lot_size": 100,
        "instrument_kind": kind,
    }
    values.update(changes)
    return ExecutionPolicy(**values)  # type: ignore[arg-type]


def test_stock_trade_uses_next_open_and_exact_cash_fees() -> None:
    report = run_executable_backtest(
        rows=[{"label": 1, "future_return": 0.1}],
        raw_bars=_bars(["9", "10", "11"]),
        row_bar_indices=[0],
        folds=_fold(1),
        predictions=_predictions(1),
        prediction_threshold=0.5,
        holding_bars=1,
        policy=_policy(),
    )

    trade = report.trades[0]
    assert trade.entry_bar_index == 1
    assert trade.exit_bar_index == 2
    assert trade.quantity == 900
    assert trade.entry_price == Decimal("10")
    assert trade.exit_price == Decimal("11")
    assert report.total_commission == Decimal("10.00")
    assert report.total_stamp_duty == Decimal("4.95")
    assert report.total_transfer_fee == Decimal("0.19")
    assert report.ending_equity == Decimal("10884.86")
    assert report.net_return == pytest.approx(0.088486)


def test_etf_is_exempt_from_stock_stamp_and_transfer_fees() -> None:
    report = run_executable_backtest(
        rows=[{"label": 1, "future_return": 0.1}],
        raw_bars=_bars(["9", "10", "11"]),
        row_bar_indices=[0],
        folds=_fold(1),
        predictions=_predictions(1),
        prediction_threshold=0.5,
        holding_bars=1,
        policy=_policy(InstrumentKind.ETF),
    )

    assert report.total_commission == Decimal("10.00")
    assert report.total_stamp_duty == 0
    assert report.total_transfer_fee == 0
    assert report.ending_equity == Decimal("10890.00")


def test_slippage_lot_rounding_and_two_sided_capacity_are_conservative() -> None:
    report = run_executable_backtest(
        rows=[{"label": 1, "future_return": 0.1}],
        raw_bars=_bars(
            ["9", "10", "11"],
            volumes=["100000", "1550", "1200"],
        ),
        row_bar_indices=[0],
        folds=_fold(1),
        predictions=_predictions(1),
        prediction_threshold=0.5,
        holding_bars=1,
        policy=_policy(
            InstrumentKind.ETF,
            commission_rate=Decimal("0"),
            minimum_commission=Decimal("0"),
            slippage_bps=Decimal("10"),
            participation_rate=Decimal("0.10"),
        ),
    )

    trade = report.trades[0]
    assert trade.quantity == 100
    assert trade.entry_price == Decimal("10.010")
    assert trade.exit_price == Decimal("10.989")
    assert report.slippage_cost == Decimal("2.10")
    assert report.turnover == pytest.approx(0.20999)


def test_overlapping_signals_do_not_reuse_cash_and_metrics_follow_equity() -> None:
    report = run_executable_backtest(
        rows=[
            {"label": 1, "future_return": 0.1},
            {"label": 1, "future_return": 0.1},
            {"label": 0, "future_return": -0.1},
        ],
        raw_bars=_bars(["10", "10", "10", "11", "11", "11", "9"]),
        row_bar_indices=[0, 1, 3],
        folds=_fold(3),
        predictions=_predictions(3),
        prediction_threshold=0.5,
        holding_bars=2,
        policy=_policy(
            InstrumentKind.ETF,
            commission_rate=Decimal("0"),
            minimum_commission=Decimal("0"),
        ),
    )

    assert report.executed_trades == 2
    assert report.overlap_skips == 1
    assert report.capacity_skips == 0
    assert report.win_rate == 0.5
    assert report.max_drawdown > 0
    assert report.ending_equity < report.initial_equity


def test_capacity_below_one_lot_skips_trade() -> None:
    report = run_executable_backtest(
        rows=[{"label": 1, "future_return": 0.1}],
        raw_bars=_bars(["10", "10", "11"], volumes=["1000", "999", "999"]),
        row_bar_indices=[0],
        folds=_fold(1),
        predictions=_predictions(1),
        prediction_threshold=0.5,
        holding_bars=1,
        policy=_policy(InstrumentKind.ETF, participation_rate=Decimal("0.10")),
    )

    assert report.executed_trades == 0
    assert report.capacity_skips == 1
    assert report.ending_equity == report.initial_equity

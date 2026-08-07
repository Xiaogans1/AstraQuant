from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_domain import InstrumentId, OrderSide
from astraquant_quant.replay import OpeningPosition, replay_bars


def _bars(closes: list[str]) -> list[MarketBar]:
    start = datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    result: list[MarketBar] = []
    for index, close in enumerate(closes):
        result.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index),
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal("100"),
                turnover=Decimal(close) * 100,
                previous_close=Decimal("10"),
            )
        )
    return result


def test_replay_is_deterministic_and_tracks_round_trip() -> None:
    closes = ["10"] * 35 + ["10.05"] * 20 + ["9.95"] * 20 + ["10"] * 10
    bars = _bars(closes)
    instrument = InstrumentId.parse("159516.SZSE")

    def predict(_completed: list[MarketBar]) -> float:
        return 0.0

    first = replay_bars(
        bars,
        instrument_id=instrument,
        predict=predict,
        buy_threshold=0.5,
        sell_threshold=0.4,
        fee_rate=Decimal("0.00025"),
        initial_cash=Decimal("10000"),
    )
    second = replay_bars(
        bars,
        instrument_id=instrument,
        predict=predict,
        buy_threshold=0.5,
        sell_threshold=0.4,
        fee_rate=Decimal("0.00025"),
        initial_cash=Decimal("10000"),
    )

    assert first.trades == second.trades
    assert first.equity_points == second.equity_points
    assert first.buys == 0
    assert first.final_cash == Decimal("10000")


def test_replay_buys_on_high_probability_and_sells_on_low() -> None:
    # Day 1: flat then ramp (BUY). Day 2: drop (SELL, available after day roll).
    day_one = _bars(["10"] * 35 + ["10.05"] * 20)
    day_two = [
        MarketBar(
            timestamp=bar.timestamp + timedelta(days=1),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            turnover=bar.turnover,
            previous_close=bar.previous_close,
        )
        for bar in _bars(["9.95"] * 30)
    ]
    bars = [*day_one, *day_two]
    instrument = InstrumentId.parse("159516.SZSE")
    first_day_end = day_one[-1].timestamp

    def predict(completed: list[MarketBar]) -> float:
        return 0.9 if completed[-1].timestamp <= first_day_end else 0.1

    result = replay_bars(
        bars,
        instrument_id=instrument,
        predict=predict,
        buy_threshold=0.5,
        sell_threshold=0.4,
        fee_rate=Decimal("0.00025"),
        initial_cash=Decimal("10000"),
    )

    assert result.buys == 1
    assert result.sells == 1
    buy = result.trades[0]
    sell = result.trades[1]
    assert buy.side is OrderSide.BUY
    assert sell.side is OrderSide.SELL
    assert sell.pnl < 0  # bought at 10.05, sold at 9.95
    assert result.win_rate == 0.0
    assert result.realized_pnl < 0
    assert result.position_remaining == 0


def test_replay_never_sees_future_bars() -> None:
    bars = _bars(["10"] * 35 + ["10.05"] * 20)
    instrument = InstrumentId.parse("159516.SZSE")
    seen: list[int] = []

    def predict(completed: list[MarketBar]) -> float:
        seen.append(len(completed))
        return 0.0

    replay_bars(
        bars,
        instrument_id=instrument,
        predict=predict,
        buy_threshold=0.5,
        sell_threshold=0.4,
        fee_rate=Decimal("0.00025"),
        initial_cash=Decimal("10000"),
    )

    assert seen == list(range(31, len(bars) + 1))


def test_replay_with_opening_position_seeds_equity_and_limits_sell_to_available() -> None:
    closes = ["10"] * 35 + ["9.6"] * 30 + ["10"] * 20
    bars = _bars(closes)
    instrument = InstrumentId.parse("159516.SZSE")

    def predict(_completed: list[MarketBar]) -> float:
        return 0.1  # always sell

    result = replay_bars(
        bars,
        instrument_id=instrument,
        predict=predict,
        buy_threshold=0.5,
        sell_threshold=0.4,
        fee_rate=Decimal("0.00025"),
        initial_cash=Decimal("5000"),
        opening=OpeningPosition(
            quantity=1000,
            available_quantity=400,
            average_cost=Decimal("10"),
        ),
    )

    assert result.initial_equity == Decimal("5000") + Decimal("1000") * Decimal("10")
    sell_trades = [trade for trade in result.trades if trade.side is OrderSide.SELL]
    assert sum(trade.quantity for trade in sell_trades) == 400  # only available sold
    assert result.position_remaining == 600


def test_replay_top_up_buys_are_frozen_until_next_day() -> None:
    closes = ["10"] * 35 + ["9.6"] * 30
    day_two = [
        MarketBar(
            timestamp=bars2.timestamp + timedelta(days=1),
            open=bars2.open,
            high=bars2.high,
            low=bars2.low,
            close=bars2.close,
            volume=bars2.volume,
            turnover=bars2.turnover,
            previous_close=bars2.previous_close,
        )
        for bars2 in _bars(["9.4"] * 30)
    ]
    bars = [*_bars(closes), *day_two]
    instrument = InstrumentId.parse("159516.SZSE")

    def predict(_completed: list[MarketBar]) -> float:
        return 0.1  # sell signal; day boundary unlocks the frozen top-up

    result = replay_bars(
        bars,
        instrument_id=instrument,
        predict=predict,
        buy_threshold=0.5,
        sell_threshold=0.4,
        fee_rate=Decimal("0.00025"),
        initial_cash=Decimal("5000"),
        opening=OpeningPosition(
            quantity=1000,
            available_quantity=1000,
            average_cost=Decimal("10"),
        ),
    )

    sell_trades = [trade for trade in result.trades if trade.side is OrderSide.SELL]
    assert sum(trade.quantity for trade in sell_trades) == 1000


def test_replay_fully_invested_starts_with_position_and_buy_hold_benchmark() -> None:
    bars = _bars(["10"] * 35 + ["11"] * 30)
    instrument = InstrumentId.parse("159516.SZSE")

    def predict(_completed: list[MarketBar]) -> float:
        return 0.6  # neutral: neither buy nor sell, hold the invested position

    result = replay_bars(
        bars,
        instrument_id=instrument,
        predict=predict,
        buy_threshold=0.5,
        sell_threshold=0.4,
        fee_rate=Decimal("0.00025"),
        initial_cash=Decimal("100000"),
        fully_invested=True,
    )

    assert result.position_remaining > 0
    assert result.buy_hold_return_percent > 0
    assert result.buy_hold_equity_points
    assert abs(result.buy_hold_return_percent - result.net_return_percent) < 2.0
    assert (
        result.excess_return_percent == result.net_return_percent - result.buy_hold_return_percent
    )


def test_replay_default_starts_cash_only() -> None:
    bars = _bars(["10"] * 35 + ["11"] * 30)
    instrument = InstrumentId.parse("159516.SZSE")

    def predict(_completed: list[MarketBar]) -> float:
        return 0.9  # buy signal, but position opens on first signal

    result = replay_bars(
        bars,
        instrument_id=instrument,
        predict=predict,
        buy_threshold=0.5,
        sell_threshold=0.4,
        fee_rate=Decimal("0.00025"),
        initial_cash=Decimal("100000"),
    )

    assert result.position_remaining > 0
    assert result.initial_equity == result.initial_cash

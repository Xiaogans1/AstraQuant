from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_domain import InstrumentId, OrderSide
from astraquant_quant.replay import replay_bars


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
    closes = ["10"] * 35 + ["10.05"] * 20 + ["9.95"] * 20 + ["10"] * 10
    bars = _bars(closes)
    instrument = InstrumentId.parse("159516.SZSE")
    # First half of the series predicts up, second half predicts down.
    split_index = 55

    def predict(completed: list[MarketBar]) -> float:
        return 0.9 if len(completed) <= split_index else 0.1

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

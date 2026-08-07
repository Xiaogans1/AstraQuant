"""Deterministic historical replay of a model or rule signal over minute bars.

The replay advances one completed bar at a time: at each bar the predictor sees
only bars[0..i] (never the future), a trade decision is made, and the paper
ledger moves with configurable fees. The same bars + predictor + parameters
always produce the same trades and equity curve.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_domain import InstrumentId, OrderSide

_WINDOW = 30


@dataclass(frozen=True, slots=True)
class ReplayTrade:
    index: int
    timestamp: datetime
    side: OrderSide
    price: Decimal
    quantity: int
    pnl: Decimal


@dataclass(frozen=True, slots=True)
class ReplayResult:
    instrument_id: str
    start: datetime
    end: datetime
    bars_count: int
    initial_cash: Decimal
    final_cash: Decimal
    trades: tuple[ReplayTrade, ...]
    equity_points: tuple[tuple[datetime, Decimal], ...]
    realized_pnl: Decimal

    @property
    def buys(self) -> int:
        return sum(1 for trade in self.trades if trade.side is OrderSide.BUY)

    @property
    def sells(self) -> int:
        return sum(1 for trade in self.trades if trade.side is OrderSide.SELL)

    @property
    def win_rate(self) -> float:
        closed = [trade for trade in self.trades if trade.side is OrderSide.SELL]
        if not closed:
            return 0.0
        return sum(1 for trade in closed if trade.pnl > 0) / len(closed)

    @property
    def net_return_percent(self) -> float:
        if self.initial_cash <= 0:
            return 0.0
        return float((self.final_cash - self.initial_cash) / self.initial_cash * 100)


Predictor = Callable[[list[MarketBar]], float]


def replay_bars(
    bars: list[MarketBar],
    *,
    instrument_id: InstrumentId,
    predict: Predictor,
    buy_threshold: float,
    sell_threshold: float,
    fee_rate: Decimal,
    initial_cash: Decimal,
    lot_size: int = 100,
) -> ReplayResult:
    """Replay the signal over completed bars with a single-position paper book."""
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if not 0 < buy_threshold <= 1 or not 0 <= sell_threshold < 1:
        raise ValueError("thresholds must be probabilities in [0, 1]")
    cash = initial_cash
    position_qty = 0
    entry_price: Decimal | None = None
    trades: list[ReplayTrade] = []
    equity_points: list[tuple[datetime, Decimal]] = []
    for index in range(_WINDOW, len(bars)):
        completed = bars[: index + 1]
        price = bars[index].close
        proba = predict(completed)
        if position_qty == 0 and proba >= buy_threshold:
            quantity = max(
                lot_size,
                int(cash / price / lot_size) * lot_size,
            )
            if quantity >= lot_size and cash >= quantity * price:
                cash -= quantity * price * (Decimal("1") + fee_rate)
                position_qty = quantity
                entry_price = price
                trades.append(
                    ReplayTrade(
                        index=index,
                        timestamp=bars[index].timestamp,
                        side=OrderSide.BUY,
                        price=price,
                        quantity=quantity,
                        pnl=Decimal("0"),
                    )
                )
        elif position_qty > 0 and proba <= sell_threshold:
            assert entry_price is not None
            sell_qty = position_qty
            gross = (price - entry_price) * sell_qty
            fees = gross * fee_rate * 2
            pnl = gross - fees
            cash += price * sell_qty * (Decimal("1") - fee_rate)
            position_qty = 0
            entry_price = None
            trades.append(
                ReplayTrade(
                    index=index,
                    timestamp=bars[index].timestamp,
                    side=OrderSide.SELL,
                    price=price,
                    quantity=sell_qty,
                    pnl=pnl,
                )
            )
        market_value = price * position_qty
        equity_points.append((bars[index].timestamp, cash + market_value))
    # close the book at the last price (unrealized pnl folded into final cash)
    final_cash = cash
    if position_qty > 0:
        assert entry_price is not None
        last_price = bars[-1].close
        gross = (last_price - entry_price) * position_qty
        final_cash += last_price * position_qty * (Decimal("1") - fee_rate)
    return ReplayResult(
        instrument_id=str(instrument_id),
        start=bars[0].timestamp,
        end=bars[-1].timestamp,
        bars_count=len(bars),
        initial_cash=initial_cash,
        final_cash=final_cash,
        trades=tuple(trades),
        equity_points=tuple(equity_points),
        realized_pnl=sum((trade.pnl for trade in trades), start=Decimal("0")),
    )

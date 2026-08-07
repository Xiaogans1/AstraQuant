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
    proba: float = 0.0


@dataclass(frozen=True, slots=True)
class ReplayResult:
    instrument_id: str
    start: datetime
    end: datetime
    bars_count: int
    initial_cash: Decimal
    initial_equity: Decimal
    final_cash: Decimal
    trades: tuple[ReplayTrade, ...]
    equity_points: tuple[tuple[datetime, Decimal], ...]
    realized_pnl: Decimal
    position_remaining: int = 0

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
        if self.initial_equity <= 0:
            return 0.0
        return float((self.final_cash - self.initial_equity) / self.initial_equity * 100)

    @property
    def max_drawdown_percent(self) -> float:
        peak = self.initial_equity
        drawdown = Decimal("0")
        for _, equity in self.equity_points:
            if equity > peak:
                peak = equity
            if peak > 0:
                current = (peak - equity) / peak * 100
                if current > drawdown:
                    drawdown = current
        return float(drawdown)

    @property
    def sharpe(self) -> float:
        if len(self.equity_points) < 2:
            return 0.0
        points = self.equity_points
        returns = [
            float((points[index + 1][1] - points[index][1]) / points[index][1])
            for index in range(len(points) - 1)
            if points[index][1] > 0
        ]
        if not returns:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((value - mean) ** 2 for value in returns) / len(returns)
        if variance <= 0:
            return 0.0
        return float(mean / (variance**0.5) * 240**0.5)

    @property
    def profit_factor(self) -> float:
        wins = Decimal("0")
        losses = Decimal("0")
        for trade in self.trades:
            if trade.side is not OrderSide.SELL:
                continue
            if trade.pnl > 0:
                wins += trade.pnl
            else:
                losses += -trade.pnl
        if losses <= 0:
            return 0.0 if wins <= 0 else 99.0
        return float(wins / losses)


Predictor = Callable[[list[MarketBar]], float]


@dataclass(frozen=True, slots=True)
class OpeningPosition:
    quantity: int
    available_quantity: int
    average_cost: Decimal


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
    opening: OpeningPosition | None = None,
) -> ReplayResult:
    """Replay the signal over completed bars with a single-position paper book.

    ``opening`` seeds the replay with an existing holding (mirroring the paper
    account): equity starts at cash + opening market value, SELL is limited to
    the available quantity (T+1, unlocked at each new trading day), and BUY
    signals add to the position when cash allows (no artificial cash
    injections).
    """
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if not 0 < buy_threshold <= 1 or not 0 <= sell_threshold < 1:
        raise ValueError("thresholds must be probabilities in [0, 1]")
    cash = initial_cash
    position_qty = 0 if opening is None else opening.quantity
    available_qty = 0 if opening is None else opening.available_quantity
    entry_price: Decimal | None = None if opening is None else opening.average_cost
    trades: list[ReplayTrade] = []
    equity_points: list[tuple[datetime, Decimal]] = []
    prev_date = None
    for index in range(_WINDOW, len(bars)):
        bar = bars[index]
        if prev_date is not None and bar.timestamp.date() != prev_date:
            available_qty = position_qty
        prev_date = bar.timestamp.date()
        completed = bars[: index + 1]
        price = bar.close
        proba = predict(completed)
        if proba >= buy_threshold:
            if position_qty == 0:
                quantity = max(
                    lot_size,
                    int(cash / price / lot_size) * lot_size,
                )
                if quantity >= lot_size and cash >= quantity * price:
                    cash -= quantity * price * (Decimal("1") + fee_rate)
                    position_qty = quantity
                    available_qty = 0
                    entry_price = price
                    trades.append(
                        ReplayTrade(
                            index=index,
                            timestamp=bar.timestamp,
                            side=OrderSide.BUY,
                            price=price,
                            quantity=quantity,
                            pnl=Decimal("0"),
                            proba=proba,
                        )
                    )
            elif cash >= lot_size * price:
                # top-up: buy one lot, frozen until the next trading day
                cost = lot_size * price * (Decimal("1") + fee_rate)
                cash -= cost
                assert entry_price is not None
                entry_price = (
                    entry_price * position_qty + lot_size * price * (Decimal("1") + fee_rate)
                ) / (position_qty + lot_size)
                position_qty += lot_size
                trades.append(
                    ReplayTrade(
                        index=index,
                        timestamp=bar.timestamp,
                        side=OrderSide.BUY,
                        price=price,
                        quantity=lot_size,
                        pnl=Decimal("0"),
                        proba=proba,
                    )
                )
        elif proba <= sell_threshold and position_qty > 0 and available_qty >= lot_size:
            assert entry_price is not None
            sell_qty = min(available_qty, position_qty)
            gross = (price - entry_price) * sell_qty
            fees = gross * fee_rate * 2
            pnl = gross - fees
            cash += price * sell_qty * (Decimal("1") - fee_rate)
            position_qty -= sell_qty
            available_qty -= sell_qty
            trades.append(
                ReplayTrade(
                    index=index,
                    timestamp=bar.timestamp,
                    side=OrderSide.SELL,
                    price=price,
                    quantity=sell_qty,
                    pnl=pnl,
                    proba=proba,
                )
            )
            if position_qty == 0:
                entry_price = None
        market_value = price * position_qty
        equity_points.append((bar.timestamp, cash + market_value))
    opening_value = (
        Decimal("0")
        if opening is None or not bars
        else opening.quantity * bars[min(_WINDOW, len(bars) - 1)].close
    )
    initial_equity = initial_cash + opening_value
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
        initial_equity=initial_equity,
        final_cash=final_cash,
        trades=tuple(trades),
        equity_points=tuple(equity_points),
        realized_pnl=sum((trade.pnl for trade in trades), start=Decimal("0")),
        position_remaining=position_qty,
    )

"""LEAN-style strategy layers: alpha -> target position -> risk -> execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from astraquant_domain import OrderSide, SignalAction


@dataclass(frozen=True, slots=True)
class PortfolioConstructor:
    max_position_percent: Decimal


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    max_position_percent: Decimal


def build_target_position(
    constructor: PortfolioConstructor,
    risk: RiskPolicy,
    *,
    signal_strength: Decimal,
    equity: Decimal,
    price: Decimal,
) -> int:
    """Convert signal strength into a share target, capped by risk and rounded to 100-share lots."""
    budget = equity * min(constructor.max_position_percent, risk.max_position_percent)
    budget = budget * signal_strength / Decimal("100")
    if budget <= 0 or price <= 0:
        return 0
    return int(budget / price / 100) * 100


def side_of(action: SignalAction) -> OrderSide | None:
    if action is SignalAction.BUY:
        return OrderSide.BUY
    if action is SignalAction.SELL:
        return OrderSide.SELL
    return None

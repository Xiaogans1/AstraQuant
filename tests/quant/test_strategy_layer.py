from __future__ import annotations

from decimal import Decimal

from astraquant_domain import OrderSide, SignalAction
from astraquant_quant.strategy_layer import (
    PortfolioConstructor,
    RiskPolicy,
    build_target_position,
    side_of,
)


def test_target_position_is_capped_by_risk_budget() -> None:
    target = build_target_position(
        PortfolioConstructor(max_position_percent=Decimal("20")),
        RiskPolicy(max_position_percent=Decimal("10")),
        signal_strength=Decimal("1"),
        equity=Decimal("100000"),
        price=Decimal("10"),
    )
    assert target == 1000


def test_target_position_scales_with_signal_strength() -> None:
    target = build_target_position(
        PortfolioConstructor(max_position_percent=Decimal("20")),
        RiskPolicy(max_position_percent=Decimal("20")),
        signal_strength=Decimal("0.5"),
        equity=Decimal("100000"),
        price=Decimal("10"),
    )
    assert target == 1000


def test_target_position_returns_zero_without_budget() -> None:
    target = build_target_position(
        PortfolioConstructor(max_position_percent=Decimal("20")),
        RiskPolicy(max_position_percent=Decimal("20")),
        signal_strength=Decimal("0.01"),
        equity=Decimal("100000"),
        price=Decimal("10"),
    )
    assert target == 0


def test_side_of_maps_signal_actions() -> None:
    assert side_of(SignalAction.BUY) is OrderSide.BUY
    assert side_of(SignalAction.SELL) is OrderSide.SELL
    assert side_of(SignalAction.HOLD) is None

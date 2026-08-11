from __future__ import annotations

from decimal import Decimal

from astraquant_domain import OrderSide
from astraquant_quant.targets import (
    ForecastEvidenceStatus,
    ForecastInput,
    ForecastTargetPolicy,
    PositionProjection,
    TargetIntentKind,
    TargetReason,
    build_base_target,
    reconcile_target,
)


def _policy() -> ForecastTargetPolicy:
    return ForecastTargetPolicy(
        enter_probability=Decimal("0.55"),
        exit_probability=Decimal("0.45"),
        max_position_percent=Decimal("20"),
        round_trip_cost_rate=Decimal("0.0005"),
        lot_size=100,
    )


def _forecast(
    *,
    probability: str,
    expected_return: str,
    evidence: ForecastEvidenceStatus = ForecastEvidenceStatus.VALIDATED,
) -> ForecastInput:
    return ForecastInput(
        forecast_id="forecast-1",
        probability_up=Decimal(probability),
        expected_return=Decimal(expected_return),
        evidence_status=evidence,
    )


def test_validated_forecast_scales_target_by_probability_and_risk_budget() -> None:
    target = build_base_target(
        _forecast(probability="0.75", expected_return="0.01"),
        _policy(),
        current_target_quantity=0,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )

    assert target.target_quantity == 1000
    assert target.signal_strength == Decimal("0.5")
    assert target.reason is TargetReason.FORECAST_TARGET


def test_insufficient_evidence_keeps_current_base_target() -> None:
    target = build_base_target(
        _forecast(
            probability="0.90",
            expected_return="0.02",
            evidence=ForecastEvidenceStatus.INSUFFICIENT_EVIDENCE,
        ),
        _policy(),
        current_target_quantity=1200,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )

    assert target.target_quantity == 1200
    assert target.reason is TargetReason.INSUFFICIENT_EVIDENCE


def test_forecast_without_net_edge_keeps_current_base_target() -> None:
    target = build_base_target(
        _forecast(probability="0.80", expected_return="0.0004"),
        _policy(),
        current_target_quantity=800,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )

    assert target.target_quantity == 800
    assert target.reason is TargetReason.NO_NET_EDGE


def test_probability_inside_no_trade_band_keeps_current_base_target() -> None:
    target = build_base_target(
        _forecast(probability="0.52", expected_return="0.01"),
        _policy(),
        current_target_quantity=600,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )

    assert target.target_quantity == 600
    assert target.reason is TargetReason.NO_TRADE_BAND


def test_validated_bearish_forecast_targets_zero() -> None:
    target = build_base_target(
        _forecast(probability="0.40", expected_return="-0.01"),
        _policy(),
        current_target_quantity=1000,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )

    assert target.target_quantity == 0
    assert target.reason is TargetReason.FORECAST_TARGET


def test_t1_target_zero_only_sells_opening_quantity() -> None:
    result = reconcile_target(
        target_quantity=0,
        position=PositionProjection(
            actual_quantity=2000,
            rule_sellable_quantity=1000,
            reserved_sell_quantity=0,
            working_buy_quantity=0,
            working_sell_quantity=0,
        ),
        cash_available=Decimal("0"),
        price=Decimal("10"),
        buy_cost_buffer_rate=Decimal("0.001"),
        lot_size=100,
    )

    assert result.proposed_side is OrderSide.SELL
    assert result.proposed_quantity == 1000
    assert result.reachable_quantity == 1000
    assert result.unreachable_quantity == 1000
    assert TargetReason.T1_FROZEN in result.reasons


def test_working_sell_that_reaches_target_does_not_duplicate_order() -> None:
    result = reconcile_target(
        target_quantity=500,
        position=PositionProjection(
            actual_quantity=1000,
            rule_sellable_quantity=1000,
            reserved_sell_quantity=500,
            working_buy_quantity=0,
            working_sell_quantity=500,
        ),
        cash_available=Decimal("0"),
        price=Decimal("10"),
        buy_cost_buffer_rate=Decimal("0.001"),
        lot_size=100,
    )

    assert result.projected_quantity == 500
    assert result.proposed_side is None
    assert result.proposed_quantity == 0
    assert TargetReason.WORKING_ORDER_COVERS_DELTA in result.reasons


def test_buy_target_reports_cash_limited_reachable_quantity() -> None:
    result = reconcile_target(
        target_quantity=1000,
        position=PositionProjection(
            actual_quantity=0,
            rule_sellable_quantity=0,
            reserved_sell_quantity=0,
            working_buy_quantity=0,
            working_sell_quantity=0,
        ),
        cash_available=Decimal("10000"),
        price=Decimal("10"),
        buy_cost_buffer_rate=Decimal("0.001"),
        lot_size=100,
    )

    assert result.proposed_side is OrderSide.BUY
    assert result.proposed_quantity == 900
    assert result.reachable_quantity == 900
    assert result.unreachable_quantity == 100
    assert TargetReason.CASH_LIMIT in result.reasons


def test_active_reservation_reduces_new_sell_and_explains_shortfall() -> None:
    result = reconcile_target(
        target_quantity=0,
        position=PositionProjection(
            actual_quantity=2000,
            rule_sellable_quantity=1500,
            reserved_sell_quantity=1000,
            working_buy_quantity=0,
            working_sell_quantity=0,
        ),
        cash_available=Decimal("0"),
        price=Decimal("10"),
        buy_cost_buffer_rate=Decimal("0.001"),
        lot_size=100,
    )

    assert result.proposed_quantity == 500
    assert result.reachable_quantity == 1500
    assert TargetReason.SELL_RESERVED in result.reasons
    assert TargetReason.T1_FROZEN in result.reasons


def test_risk_reduction_never_claims_frozen_quantity_was_removed() -> None:
    result = reconcile_target(
        target_quantity=0,
        position=PositionProjection(
            actual_quantity=2000,
            rule_sellable_quantity=1000,
            reserved_sell_quantity=0,
            working_buy_quantity=0,
            working_sell_quantity=0,
        ),
        cash_available=Decimal("0"),
        price=Decimal("10"),
        buy_cost_buffer_rate=Decimal("0.001"),
        lot_size=100,
        intent_kind=TargetIntentKind.RISK_REDUCTION,
    )

    assert result.reachable_quantity == 1000
    assert TargetReason.RISK_REDUCTION_PARTIAL in result.reasons

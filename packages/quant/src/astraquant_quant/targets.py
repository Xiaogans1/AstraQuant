"""Deterministic forecast targets and pre-order reachability projections."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

from astraquant_domain import OrderSide


class ForecastEvidenceStatus(StrEnum):
    VALIDATED = "VALIDATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"


class TargetReason(StrEnum):
    FORECAST_TARGET = "FORECAST_TARGET"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_NET_EDGE = "NO_NET_EDGE"
    NO_TRADE_BAND = "NO_TRADE_BAND"
    TARGET_REACHED = "TARGET_REACHED"
    WORKING_ORDER_COVERS_DELTA = "WORKING_ORDER_COVERS_DELTA"
    CASH_LIMIT = "CASH_LIMIT"
    LOT_ROUNDING = "LOT_ROUNDING"
    T1_FROZEN = "T1_FROZEN"
    SELL_RESERVED = "SELL_RESERVED"
    RISK_REDUCTION_PARTIAL = "RISK_REDUCTION_PARTIAL"


class TargetIntentKind(StrEnum):
    BASE = "BASE"
    RISK_REDUCTION = "RISK_REDUCTION"


@dataclass(frozen=True, slots=True)
class ForecastInput:
    forecast_id: str
    probability_up: Decimal
    expected_return: Decimal
    evidence_status: ForecastEvidenceStatus

    def __post_init__(self) -> None:
        if not self.forecast_id:
            raise ValueError("forecast_id must not be empty")
        if not self.probability_up.is_finite() or not 0 <= self.probability_up <= 1:
            raise ValueError("probability_up must be in [0, 1]")
        if not self.expected_return.is_finite():
            raise ValueError("expected_return must be finite")


@dataclass(frozen=True, slots=True)
class ForecastTargetPolicy:
    enter_probability: Decimal
    exit_probability: Decimal
    max_position_percent: Decimal
    round_trip_cost_rate: Decimal
    lot_size: int = 100

    def __post_init__(self) -> None:
        if not 0 <= self.exit_probability < Decimal("0.5"):
            raise ValueError("exit_probability must be below 0.5")
        if not Decimal("0.5") < self.enter_probability <= 1:
            raise ValueError("enter_probability must be above 0.5")
        if not 0 < self.max_position_percent <= 100:
            raise ValueError("max_position_percent must be in (0, 100]")
        if self.round_trip_cost_rate < 0:
            raise ValueError("round_trip_cost_rate must not be negative")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")


@dataclass(frozen=True, slots=True)
class BaseTarget:
    forecast_id: str
    previous_target_quantity: int
    target_quantity: int
    signal_strength: Decimal
    reason: TargetReason


@dataclass(frozen=True, slots=True)
class PositionProjection:
    actual_quantity: int
    rule_sellable_quantity: int
    reserved_sell_quantity: int
    working_buy_quantity: int
    working_sell_quantity: int

    def __post_init__(self) -> None:
        values = (
            self.actual_quantity,
            self.rule_sellable_quantity,
            self.reserved_sell_quantity,
            self.working_buy_quantity,
            self.working_sell_quantity,
        )
        if any(value < 0 for value in values):
            raise ValueError("position projection quantities must not be negative")
        if self.rule_sellable_quantity > self.actual_quantity:
            raise ValueError("rule_sellable_quantity must not exceed actual_quantity")
        if self.reserved_sell_quantity > self.rule_sellable_quantity:
            raise ValueError("reserved_sell_quantity must not exceed sellable quantity")
        if self.working_sell_quantity > self.reserved_sell_quantity:
            raise ValueError("working sells must be covered by sell reservations")
        if self.working_sell_quantity > self.actual_quantity:
            raise ValueError("working sells must not exceed actual quantity")

    @property
    def projected_quantity(self) -> int:
        return self.actual_quantity + self.working_buy_quantity - self.working_sell_quantity

    @property
    def available_to_new_sell(self) -> int:
        return self.rule_sellable_quantity - self.reserved_sell_quantity


@dataclass(frozen=True, slots=True)
class TargetReconciliation:
    target_quantity: int
    projected_quantity: int
    proposed_side: OrderSide | None
    proposed_quantity: int
    reachable_quantity: int
    unreachable_quantity: int
    reasons: tuple[TargetReason, ...]


def build_base_target(
    forecast: ForecastInput,
    policy: ForecastTargetPolicy,
    *,
    current_target_quantity: int,
    equity: Decimal,
    price: Decimal,
) -> BaseTarget:
    if current_target_quantity < 0:
        raise ValueError("current_target_quantity must not be negative")
    if equity <= 0 or price <= 0:
        raise ValueError("equity and price must be positive")
    if forecast.evidence_status is not ForecastEvidenceStatus.VALIDATED:
        return _held_target(forecast, current_target_quantity, TargetReason.INSUFFICIENT_EVIDENCE)
    if abs(forecast.expected_return) <= policy.round_trip_cost_rate:
        return _held_target(forecast, current_target_quantity, TargetReason.NO_NET_EDGE)
    if policy.exit_probability < forecast.probability_up < policy.enter_probability:
        return _held_target(forecast, current_target_quantity, TargetReason.NO_TRADE_BAND)
    if forecast.probability_up <= policy.exit_probability:
        return BaseTarget(
            forecast_id=forecast.forecast_id,
            previous_target_quantity=current_target_quantity,
            target_quantity=0,
            signal_strength=Decimal("0"),
            reason=TargetReason.FORECAST_TARGET,
        )
    strength = min(
        (forecast.probability_up - Decimal("0.5")) / Decimal("0.5"),
        Decimal("1"),
    )
    budget = equity * policy.max_position_percent / Decimal("100") * strength
    return BaseTarget(
        forecast_id=forecast.forecast_id,
        previous_target_quantity=current_target_quantity,
        target_quantity=quantity_for_budget(budget, price=price, lot_size=policy.lot_size),
        signal_strength=strength,
        reason=TargetReason.FORECAST_TARGET,
    )


def quantity_for_budget(budget: Decimal, *, price: Decimal, lot_size: int) -> int:
    if budget <= 0 or price <= 0 or lot_size <= 0:
        return 0
    lots = (budget / price / lot_size).to_integral_value(rounding=ROUND_FLOOR)
    return int(lots) * lot_size


def reconcile_target(
    *,
    target_quantity: int,
    position: PositionProjection,
    cash_available: Decimal,
    price: Decimal,
    buy_cost_buffer_rate: Decimal,
    lot_size: int,
    intent_kind: TargetIntentKind = TargetIntentKind.BASE,
) -> TargetReconciliation:
    if target_quantity < 0:
        raise ValueError("target_quantity must not be negative")
    if cash_available < 0:
        raise ValueError("cash_available must not be negative")
    if price <= 0 or buy_cost_buffer_rate < 0 or lot_size <= 0:
        raise ValueError("price, cost buffer and lot size are invalid")
    projected = position.projected_quantity
    if projected < 0:
        raise ValueError("working sells produce a negative projected quantity")
    if projected == target_quantity:
        reason = (
            TargetReason.WORKING_ORDER_COVERS_DELTA
            if position.working_buy_quantity or position.working_sell_quantity
            else TargetReason.TARGET_REACHED
        )
        return TargetReconciliation(
            target_quantity=target_quantity,
            projected_quantity=projected,
            proposed_side=None,
            proposed_quantity=0,
            reachable_quantity=projected,
            unreachable_quantity=0,
            reasons=(reason,),
        )
    if target_quantity > projected:
        return _reconcile_buy(
            target_quantity=target_quantity,
            projected=projected,
            cash_available=cash_available,
            price=price,
            buy_cost_buffer_rate=buy_cost_buffer_rate,
            lot_size=lot_size,
        )
    return _reconcile_sell(
        target_quantity=target_quantity,
        projected=projected,
        position=position,
        lot_size=lot_size,
        intent_kind=intent_kind,
    )


def _reconcile_buy(
    *,
    target_quantity: int,
    projected: int,
    cash_available: Decimal,
    price: Decimal,
    buy_cost_buffer_rate: Decimal,
    lot_size: int,
) -> TargetReconciliation:
    desired = target_quantity - projected
    rounded_desired = desired // lot_size * lot_size
    affordable = quantity_for_budget(
        cash_available / (Decimal("1") + buy_cost_buffer_rate),
        price=price,
        lot_size=lot_size,
    )
    proposed = min(rounded_desired, affordable)
    reachable = projected + proposed
    reasons: list[TargetReason] = []
    if proposed < rounded_desired:
        reasons.append(TargetReason.CASH_LIMIT)
    if rounded_desired < desired:
        reasons.append(TargetReason.LOT_ROUNDING)
    if not reasons:
        reasons.append(TargetReason.TARGET_REACHED)
    return TargetReconciliation(
        target_quantity=target_quantity,
        projected_quantity=projected,
        proposed_side=OrderSide.BUY if proposed else None,
        proposed_quantity=proposed,
        reachable_quantity=reachable,
        unreachable_quantity=target_quantity - reachable,
        reasons=tuple(reasons),
    )


def _reconcile_sell(
    *,
    target_quantity: int,
    projected: int,
    position: PositionProjection,
    lot_size: int,
    intent_kind: TargetIntentKind,
) -> TargetReconciliation:
    desired = projected - target_quantity
    rounded_desired = desired // lot_size * lot_size
    available = position.available_to_new_sell // lot_size * lot_size
    proposed = min(rounded_desired, available)
    reachable = projected - proposed
    unreachable = reachable - target_quantity
    reasons: list[TargetReason] = []
    if position.reserved_sell_quantity > position.working_sell_quantity and unreachable > 0:
        reasons.append(TargetReason.SELL_RESERVED)
    if projected - position.rule_sellable_quantity > 0 and unreachable > 0:
        reasons.append(TargetReason.T1_FROZEN)
    if rounded_desired < desired:
        reasons.append(TargetReason.LOT_ROUNDING)
    if intent_kind is TargetIntentKind.RISK_REDUCTION and unreachable > 0:
        reasons.append(TargetReason.RISK_REDUCTION_PARTIAL)
    if not reasons:
        reasons.append(TargetReason.TARGET_REACHED)
    return TargetReconciliation(
        target_quantity=target_quantity,
        projected_quantity=projected,
        proposed_side=OrderSide.SELL if proposed else None,
        proposed_quantity=proposed,
        reachable_quantity=reachable,
        unreachable_quantity=unreachable,
        reasons=tuple(reasons),
    )


def _held_target(
    forecast: ForecastInput,
    current_target_quantity: int,
    reason: TargetReason,
) -> BaseTarget:
    return BaseTarget(
        forecast_id=forecast.forecast_id,
        previous_target_quantity=current_target_quantity,
        target_quantity=current_target_quantity,
        signal_strength=Decimal("0"),
        reason=reason,
    )

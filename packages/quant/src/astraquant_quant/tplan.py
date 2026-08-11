"""Two-leg intraday T-plan drafts over an immutable base target."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from astraquant_domain import OrderSide
from astraquant_quant.targets import ForecastEvidenceStatus, quantity_for_budget


class TPlanType(StrEnum):
    SELL_THEN_BUYBACK = "SELL_THEN_BUYBACK"
    BUY_THEN_SELL_BASE = "BUY_THEN_SELL_BASE"


class TPlanStatus(StrEnum):
    READY = "READY"
    HOLD = "HOLD"


class TPlanReason(StrEnum):
    READY = "READY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_NET_EDGE = "NO_NET_EDGE"
    NO_OPENING_SELLABLE = "NO_OPENING_SELLABLE"
    OPENING_SELLABLE_LIMIT = "OPENING_SELLABLE_LIMIT"
    CASH_LIMIT = "CASH_LIMIT"
    LOT_ROUNDING = "LOT_ROUNDING"


@dataclass(frozen=True, slots=True)
class TPlanRequest:
    plan_id: str
    plan_type: TPlanType
    base_target_quantity: int
    actual_quantity: int
    opening_sellable_quantity: int
    reserved_opening_quantity: int
    requested_quantity: int
    cash_available: Decimal
    price: Decimal
    expected_incremental_return: Decimal
    round_trip_cost_rate: Decimal
    evidence_status: ForecastEvidenceStatus
    lot_size: int = 100

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("plan_id must not be empty")
        quantities = (
            self.base_target_quantity,
            self.actual_quantity,
            self.opening_sellable_quantity,
            self.reserved_opening_quantity,
        )
        if any(value < 0 for value in quantities) or self.requested_quantity <= 0:
            raise ValueError("TPlan quantities are invalid")
        if self.opening_sellable_quantity > self.actual_quantity:
            raise ValueError("opening sellable quantity must not exceed actual quantity")
        if self.reserved_opening_quantity > self.opening_sellable_quantity:
            raise ValueError("opening reservation must not exceed opening sellable quantity")
        if self.cash_available < 0 or self.price <= 0:
            raise ValueError("cash and price are invalid")
        if (
            not self.expected_incremental_return.is_finite()
            or not self.round_trip_cost_rate.is_finite()
            or self.round_trip_cost_rate < 0
        ):
            raise ValueError("TPlan return and cost values are invalid")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")


@dataclass(frozen=True, slots=True)
class TPlanDraft:
    plan_id: str
    plan_type: TPlanType
    status: TPlanStatus
    base_target_quantity: int
    planned_quantity: int
    opening_quantity_to_reserve: int
    first_side: OrderSide | None
    second_side: OrderSide | None
    reasons: tuple[TPlanReason, ...]


def build_tplan(request: TPlanRequest) -> TPlanDraft:
    if request.evidence_status is not ForecastEvidenceStatus.VALIDATED:
        return _hold(request, TPlanReason.INSUFFICIENT_EVIDENCE)
    if request.expected_incremental_return <= request.round_trip_cost_rate:
        return _hold(request, TPlanReason.NO_NET_EDGE)
    available = request.opening_sellable_quantity - request.reserved_opening_quantity
    available = available // request.lot_size * request.lot_size
    if available < request.lot_size:
        return _hold(request, TPlanReason.NO_OPENING_SELLABLE)
    requested = request.requested_quantity // request.lot_size * request.lot_size
    if requested < request.lot_size:
        return _hold(request, TPlanReason.LOT_ROUNDING)

    reasons: list[TPlanReason] = []
    planned = min(requested, available)
    if planned < requested:
        reasons.append(TPlanReason.OPENING_SELLABLE_LIMIT)
    if request.plan_type is TPlanType.BUY_THEN_SELL_BASE:
        affordable = quantity_for_budget(
            request.cash_available / (Decimal("1") + request.round_trip_cost_rate),
            price=request.price,
            lot_size=request.lot_size,
        )
        if affordable < planned:
            planned = affordable
            reasons.append(TPlanReason.CASH_LIMIT)
        if planned < request.lot_size:
            return _hold(request, TPlanReason.CASH_LIMIT)
        first_side = OrderSide.BUY
        second_side = OrderSide.SELL
    else:
        first_side = OrderSide.SELL
        second_side = OrderSide.BUY
    if not reasons:
        reasons.append(TPlanReason.READY)
    return TPlanDraft(
        plan_id=request.plan_id,
        plan_type=request.plan_type,
        status=TPlanStatus.READY,
        base_target_quantity=request.base_target_quantity,
        planned_quantity=planned,
        opening_quantity_to_reserve=planned,
        first_side=first_side,
        second_side=second_side,
        reasons=tuple(reasons),
    )


def _hold(request: TPlanRequest, reason: TPlanReason) -> TPlanDraft:
    return TPlanDraft(
        plan_id=request.plan_id,
        plan_type=request.plan_type,
        status=TPlanStatus.HOLD,
        base_target_quantity=request.base_target_quantity,
        planned_quantity=0,
        opening_quantity_to_reserve=0,
        first_side=None,
        second_side=None,
        reasons=(reason,),
    )

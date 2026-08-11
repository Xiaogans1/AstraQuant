"""Deterministic forecast targets and pre-order reachability projections."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum


class ForecastEvidenceStatus(StrEnum):
    VALIDATED = "VALIDATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"


class TargetReason(StrEnum):
    FORECAST_TARGET = "FORECAST_TARGET"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_NET_EDGE = "NO_NET_EDGE"
    NO_TRADE_BAND = "NO_TRADE_BAND"


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

"""Rank-aware long-only target construction for Stage B v2."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from types import MappingProxyType

from astraquant_domain import RankPortfolioPolicy

_ONE = Decimal("1")
_ZERO = Decimal("0")
_WEIGHT_QUANTUM = Decimal("0.000000000001")


@dataclass(frozen=True, slots=True)
class RankedForecast:
    forecast_id: str
    instrument_id: str
    rank_score: float
    calibrated_expected_return: float
    trailing_volatility: float
    tradable: bool


@dataclass(frozen=True, slots=True)
class RankPortfolioTarget:
    selected_instruments: tuple[str, ...]
    target_weights: Mapping[str, Decimal]
    cash_weight: Decimal
    one_way_turnover: Decimal
    policy_digest: str
    target_digest: str


def build_rank_portfolio_target(
    *,
    forecasts: Sequence[RankedForecast],
    current_weights: Mapping[str, Decimal],
    policy: RankPortfolioPolicy,
) -> RankPortfolioTarget:
    """Convert comparable forecasts into one capped, turnover-aware target."""

    canonical_forecasts = _validate_forecasts(forecasts)
    current = _validate_current_weights(current_weights)
    tradable = sorted(
        (forecast for forecast in canonical_forecasts if forecast.tradable),
        key=lambda forecast: (-forecast.rank_score, forecast.instrument_id),
    )
    quota = min(
        policy.max_positions,
        int(
            (Decimal(len(tradable)) * policy.top_fraction).to_integral_value(
                rounding=ROUND_CEILING
            )
        ),
    )
    selected = [
        forecast
        for forecast in tradable[:quota]
        if forecast.calibrated_expected_return >= 0
    ]
    desired = _inverse_volatility_weights(selected, policy.max_instrument_weight)
    desired_turnover = _one_way_turnover(current, desired)
    if desired_turnover > policy.max_one_way_turnover:
        union_size = len(set(current) | set(desired)) + 1
        rounding_margin = _WEIGHT_QUANTUM * union_size
        safe_limit = max(_ZERO, policy.max_one_way_turnover - rounding_margin)
        fraction = safe_limit / desired_turnover
        desired = _interpolate(current, desired, fraction)

    final_weights = _quantize_weights(desired)
    cash_weight = _ONE - sum(final_weights.values(), start=_ZERO)
    one_way_turnover = _one_way_turnover(current, final_weights)
    if one_way_turnover > policy.max_one_way_turnover:
        raise RuntimeError("quantized target exceeds one-way turnover limit")
    selected_instruments = tuple(sorted(final_weights))
    target_digest = _target_digest(
        selected_instruments=selected_instruments,
        target_weights=final_weights,
        cash_weight=cash_weight,
        one_way_turnover=one_way_turnover,
        policy_digest=policy.policy_digest,
    )
    return RankPortfolioTarget(
        selected_instruments=selected_instruments,
        target_weights=MappingProxyType(final_weights),
        cash_weight=cash_weight,
        one_way_turnover=one_way_turnover,
        policy_digest=policy.policy_digest,
        target_digest=target_digest,
    )


def _validate_forecasts(
    forecasts: Sequence[RankedForecast],
) -> tuple[RankedForecast, ...]:
    values = tuple(forecasts)
    instrument_ids: set[str] = set()
    forecast_ids: set[str] = set()
    for forecast in values:
        if not forecast.forecast_id.strip() or not forecast.instrument_id.strip():
            raise ValueError("forecast and instrument identifiers must not be empty")
        if forecast.instrument_id in instrument_ids:
            raise ValueError("duplicate instrument forecast")
        if forecast.forecast_id in forecast_ids:
            raise ValueError("duplicate forecast identifier")
        instrument_ids.add(forecast.instrument_id)
        forecast_ids.add(forecast.forecast_id)
        numeric = (
            forecast.rank_score,
            forecast.calibrated_expected_return,
            forecast.trailing_volatility,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("forecast values must be finite")
        if forecast.trailing_volatility <= 0:
            raise ValueError("trailing volatility must be positive")
        if not isinstance(forecast.tradable, bool):
            raise ValueError("tradable must be boolean")
    return values


def _validate_current_weights(
    current_weights: Mapping[str, Decimal],
) -> dict[str, Decimal]:
    parsed: dict[str, Decimal] = {}
    try:
        for instrument_id, value in current_weights.items():
            if not instrument_id.strip():
                raise ValueError
            weight = value if isinstance(value, Decimal) else Decimal(str(value))
            if not weight.is_finite() or weight < 0 or weight > 1:
                raise ValueError
            if weight:
                parsed[instrument_id] = weight
    except (ArithmeticError, TypeError, ValueError) as error:
        raise ValueError("current weights must be finite and in [0, 1]") from error
    if sum(parsed.values(), start=_ZERO) > 1:
        raise ValueError("current weights must sum to at most one")
    return parsed


def _inverse_volatility_weights(
    selected: Sequence[RankedForecast],
    cap: Decimal,
) -> dict[str, Decimal]:
    strengths = {
        forecast.instrument_id: _ONE / Decimal(str(forecast.trailing_volatility))
        for forecast in selected
    }
    weights: dict[str, Decimal] = {}
    remaining = _ONE
    active = dict(strengths)
    while active and remaining > 0:
        total_strength = sum(active.values(), start=_ZERO)
        proposed = {
            instrument_id: remaining * strength / total_strength
            for instrument_id, strength in active.items()
        }
        capped = [
            instrument_id
            for instrument_id, weight in proposed.items()
            if weight > cap
        ]
        if not capped:
            weights.update(proposed)
            break
        for instrument_id in sorted(capped):
            weights[instrument_id] = cap
            remaining -= cap
            del active[instrument_id]
    return weights


def _interpolate(
    current: Mapping[str, Decimal],
    desired: Mapping[str, Decimal],
    fraction: Decimal,
) -> dict[str, Decimal]:
    return {
        instrument_id: current.get(instrument_id, _ZERO)
        + fraction
        * (desired.get(instrument_id, _ZERO) - current.get(instrument_id, _ZERO))
        for instrument_id in sorted(set(current) | set(desired))
    }


def _quantize_weights(weights: Mapping[str, Decimal]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for instrument_id in sorted(weights):
        weight = weights[instrument_id].quantize(_WEIGHT_QUANTUM)
        if weight > 0:
            result[instrument_id] = weight
    if sum(result.values(), start=_ZERO) > 1:
        raise RuntimeError("quantized asset weights exceed one")
    return result


def _one_way_turnover(
    current: Mapping[str, Decimal],
    target: Mapping[str, Decimal],
) -> Decimal:
    current_cash = _ONE - sum(current.values(), start=_ZERO)
    target_cash = _ONE - sum(target.values(), start=_ZERO)
    asset_change = sum(
        (
            abs(target.get(instrument_id, _ZERO) - current.get(instrument_id, _ZERO))
            for instrument_id in set(current) | set(target)
        ),
        start=_ZERO,
    )
    return (asset_change + abs(target_cash - current_cash)) / 2


def _target_digest(
    *,
    selected_instruments: tuple[str, ...],
    target_weights: Mapping[str, Decimal],
    cash_weight: Decimal,
    one_way_turnover: Decimal,
    policy_digest: str,
) -> str:
    payload = {
        "cash_weight": str(cash_weight),
        "one_way_turnover": str(one_way_turnover),
        "policy_digest": policy_digest,
        "selected_instruments": list(selected_instruments),
        "target_weights": {
            instrument_id: str(target_weights[instrument_id])
            for instrument_id in sorted(target_weights)
        },
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

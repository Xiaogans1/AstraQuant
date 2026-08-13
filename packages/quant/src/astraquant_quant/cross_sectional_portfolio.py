"""Non-overlapping portfolio evaluation for Stage B v2 cross-sectional scores."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from astraquant_domain import RankPortfolioPolicy
from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.executable_backtest import ExecutionPolicy
from astraquant_quant.rank_portfolio import RankedForecast, build_rank_portfolio_target

_ZERO = Decimal("0")
_ONE = Decimal("1")
_BPS = Decimal("10000")


@dataclass(frozen=True, slots=True)
class CrossSectionalPortfolioRow:
    row_id: int
    decision_time: datetime
    instrument_id: str
    horizon_sessions: int
    rank_score: float
    calibrated_expected_return: float
    raw_return: float
    trailing_volatility: float
    median_daily_turnover: Decimal
    tradable: bool


@dataclass(frozen=True, slots=True)
class CrossSectionalPortfolioMetrics:
    horizon_sessions: int
    period_count: int
    initial_equity: Decimal
    ending_equity: Decimal
    gross_return: float
    net_return: float
    one_way_turnover: float
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    slippage_cost: Decimal
    max_drawdown: float
    capacity_breaches: int
    minimum_capacity_ratio: float
    portfolio_policy_digest: str
    content_digest: str


@dataclass(frozen=True, slots=True)
class _Costs:
    commission: Decimal = _ZERO
    stamp_duty: Decimal = _ZERO
    transfer_fee: Decimal = _ZERO
    slippage: Decimal = _ZERO

    @property
    def total(self) -> Decimal:
        return self.commission + self.stamp_duty + self.transfer_fee + self.slippage

    def add(self, other: _Costs) -> _Costs:
        return _Costs(
            commission=self.commission + other.commission,
            stamp_duty=self.stamp_duty + other.stamp_duty,
            transfer_fee=self.transfer_fee + other.transfer_fee,
            slippage=self.slippage + other.slippage,
        )


def evaluate_cross_sectional_portfolio(
    rows: Sequence[CrossSectionalPortfolioRow],
    *,
    portfolio_policy: RankPortfolioPolicy,
    execution_policy: ExecutionPolicy,
) -> CrossSectionalPortfolioMetrics:
    """Evaluate horizon-spaced targets with realistic proportional A-share costs."""

    exact = _validate_rows(rows)
    horizon = exact[0].horizon_sessions
    grouped: dict[datetime, tuple[CrossSectionalPortfolioRow, ...]] = {}
    for decision_time in sorted({row.decision_time for row in exact}):
        grouped[decision_time] = tuple(row for row in exact if row.decision_time == decision_time)
    decision_times = tuple(grouped)[::horizon]
    if not decision_times:
        raise ValueError("portfolio has no non-overlapping decision periods")

    initial = execution_policy.initial_cash
    net_equity = initial
    gross_equity = initial
    current_weights: dict[str, Decimal] = {}
    total_turnover = _ZERO
    total_costs = _Costs()
    capacity_breaches = 0
    capacity_ratios: list[Decimal] = []
    equity_curve = [net_equity]

    for decision_time in decision_times:
        cohort = grouped[decision_time]
        target = build_rank_portfolio_target(
            forecasts=tuple(
                RankedForecast(
                    forecast_id=f"{row.row_id}:{decision_time.isoformat()}",
                    instrument_id=row.instrument_id,
                    rank_score=row.rank_score,
                    calibrated_expected_return=row.calibrated_expected_return,
                    trailing_volatility=row.trailing_volatility,
                    tradable=row.tradable,
                )
                for row in cohort
            ),
            current_weights=current_weights,
            policy=portfolio_policy,
        )
        target_weights = dict(target.target_weights)
        costs = _rebalance_costs(
            current_weights=current_weights,
            target_weights=target_weights,
            equity=net_equity,
            policy=execution_policy,
        )
        total_costs = total_costs.add(costs)
        net_equity -= costs.total
        if net_equity <= 0:
            raise ValueError("portfolio costs exhausted equity")
        total_turnover += target.one_way_turnover
        by_instrument = {row.instrument_id: row for row in cohort}
        for instrument_id, weight in target_weights.items():
            buy_weight = max(_ZERO, weight - current_weights.get(instrument_id, _ZERO))
            if buy_weight <= 0:
                continue
            buy_notional = net_equity * buy_weight
            capacity = (
                by_instrument[instrument_id].median_daily_turnover
                * execution_policy.participation_rate
            )
            ratio = capacity / buy_notional
            capacity_ratios.append(ratio)
            capacity_breaches += ratio < 1

        returns = {row.instrument_id: Decimal(str(row.raw_return)) for row in cohort}
        portfolio_return = sum(
            (weight * returns[instrument_id] for instrument_id, weight in target_weights.items()),
            start=_ZERO,
        )
        gross_equity *= _ONE + portfolio_return
        net_equity *= _ONE + portfolio_return
        equity_curve.append(net_equity)
        growth = target.cash_weight + sum(
            (
                weight * (_ONE + returns[instrument_id])
                for instrument_id, weight in target_weights.items()
            ),
            start=_ZERO,
        )
        current_weights = {
            instrument_id: weight * (_ONE + returns[instrument_id]) / growth
            for instrument_id, weight in target_weights.items()
            if weight > 0
        }

    closing_costs = _rebalance_costs(
        current_weights=current_weights,
        target_weights={},
        equity=net_equity,
        policy=execution_policy,
    )
    total_costs = total_costs.add(closing_costs)
    net_equity -= closing_costs.total
    total_turnover += sum(current_weights.values(), start=_ZERO)
    equity_curve.append(net_equity)
    if net_equity <= 0:
        raise ValueError("portfolio closing costs exhausted equity")
    minimum_capacity_ratio = min(capacity_ratios) if capacity_ratios else Decimal("1000000000")
    body = {
        "horizon_sessions": horizon,
        "period_count": len(decision_times),
        "initial_equity": str(initial),
        "ending_equity": str(net_equity),
        "gross_return": float(gross_equity / initial - 1).hex(),
        "net_return": float(net_equity / initial - 1).hex(),
        "one_way_turnover": float(total_turnover).hex(),
        "commission": str(total_costs.commission),
        "stamp_duty": str(total_costs.stamp_duty),
        "transfer_fee": str(total_costs.transfer_fee),
        "slippage_cost": str(total_costs.slippage),
        "max_drawdown": _max_drawdown(equity_curve).hex(),
        "capacity_breaches": capacity_breaches,
        "minimum_capacity_ratio": float(minimum_capacity_ratio).hex(),
        "portfolio_policy_digest": portfolio_policy.policy_digest,
        "execution_policy": _execution_policy_value(execution_policy),
        "schema_version": "astraquant.cross-sectional-portfolio-metrics/v1",
    }
    return CrossSectionalPortfolioMetrics(
        horizon_sessions=horizon,
        period_count=len(decision_times),
        initial_equity=initial,
        ending_equity=net_equity,
        gross_return=float(gross_equity / initial - 1),
        net_return=float(net_equity / initial - 1),
        one_way_turnover=float(total_turnover),
        commission=total_costs.commission,
        stamp_duty=total_costs.stamp_duty,
        transfer_fee=total_costs.transfer_fee,
        slippage_cost=total_costs.slippage,
        max_drawdown=_max_drawdown(equity_curve),
        capacity_breaches=capacity_breaches,
        minimum_capacity_ratio=float(minimum_capacity_ratio),
        portfolio_policy_digest=portfolio_policy.policy_digest,
        content_digest=_digest(body),
    )


def _validate_rows(
    rows: Sequence[CrossSectionalPortfolioRow],
) -> tuple[CrossSectionalPortfolioRow, ...]:
    exact = tuple(rows)
    if not exact:
        raise ValueError("portfolio rows must not be empty")
    horizons = {row.horizon_sessions for row in exact}
    if len(horizons) != 1 or next(iter(horizons)) <= 0:
        raise ValueError("portfolio rows must have one positive horizon")
    identities: set[tuple[datetime, str]] = set()
    for row in exact:
        identity = (row.decision_time, row.instrument_id)
        numeric = (
            row.rank_score,
            row.calibrated_expected_return,
            row.raw_return,
            row.trailing_volatility,
        )
        if (
            row.decision_time.tzinfo is None
            or row.decision_time.utcoffset() is None
            or not row.instrument_id
            or identity in identities
        ):
            raise ValueError("portfolio row identities must be unique and canonical")
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("portfolio row numeric values must be finite")
        if row.trailing_volatility <= 0 or row.median_daily_turnover <= 0:
            raise ValueError("portfolio risk and liquidity values must be positive")
        if not isinstance(row.tradable, bool):
            raise ValueError("portfolio tradable flag must be boolean")
        identities.add(identity)
    return exact


def _rebalance_costs(
    *,
    current_weights: Mapping[str, Decimal],
    target_weights: Mapping[str, Decimal],
    equity: Decimal,
    policy: ExecutionPolicy,
) -> _Costs:
    costs = _Costs()
    for instrument_id in sorted(set(current_weights) | set(target_weights)):
        delta = target_weights.get(instrument_id, _ZERO) - current_weights.get(instrument_id, _ZERO)
        gross = equity * abs(delta)
        if gross <= 0:
            continue
        commission = max(gross * policy.commission_rate, policy.minimum_commission)
        stamp = gross * policy.stamp_duty_rate if delta < 0 else _ZERO
        transfer = gross * policy.transfer_fee_rate
        slippage = gross * policy.slippage_bps / _BPS
        costs = costs.add(
            _Costs(
                commission=commission,
                stamp_duty=stamp,
                transfer_fee=transfer,
                slippage=slippage,
            )
        )
    return costs


def _max_drawdown(equity_curve: Sequence[Decimal]) -> float:
    peak = equity_curve[0]
    maximum = _ZERO
    for equity in equity_curve:
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak)
    return float(maximum)


def _execution_policy_value(policy: ExecutionPolicy) -> dict[str, object]:
    return {
        "initial_cash": str(policy.initial_cash),
        "commission_rate": str(policy.commission_rate),
        "minimum_commission": str(policy.minimum_commission),
        "stamp_duty_rate": str(policy.stamp_duty_rate),
        "transfer_fee_rate": str(policy.transfer_fee_rate),
        "slippage_bps": str(policy.slippage_bps),
        "participation_rate": str(policy.participation_rate),
        "lot_size": policy.lot_size,
        "instrument_kind": policy.instrument_kind.value,
    }


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

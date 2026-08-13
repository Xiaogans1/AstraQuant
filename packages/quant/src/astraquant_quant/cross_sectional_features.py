"""Leakage-safe market-context features alongside official Qlib Alpha158."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from statistics import median, pstdev
from types import MappingProxyType
from typing import Protocol

from astraquant_data.market_bars import MarketBar
from astraquant_domain.run_manifest import canonical_json_bytes

CONTEXT_FEATURE_COLUMNS = (
    "return_1",
    "return_5",
    "return_20",
    "relative_return_1",
    "relative_return_5",
    "relative_return_20",
    "intraday_return",
    "amplitude",
    "volume_ratio_20",
    "turnover_median_20_log",
    "volatility_20",
    "price_position_20",
    "market_return_1",
    "market_volatility_20",
    "market_breadth",
)


class DailyPanelLike(Protocol):
    @property
    def sessions(self) -> Sequence[datetime]: ...

    @property
    def instrument_bars(self) -> Mapping[str, Mapping[datetime, MarketBar]]: ...

    @property
    def benchmark_bars(self) -> Mapping[datetime, MarketBar]: ...

    @property
    def eligible_by_session(self) -> Mapping[datetime, frozenset[str]]: ...


@dataclass(frozen=True, slots=True)
class CrossSectionalFeatureRow:
    decision_time: datetime
    instrument_id: str
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        if self.decision_time.tzinfo is None or self.decision_time.utcoffset() is None:
            raise ValueError("feature decision_time must be timezone-aware")
        instrument_id = self.instrument_id.strip()
        if not instrument_id:
            raise ValueError("feature instrument_id must not be empty")
        if tuple(self.values) != CONTEXT_FEATURE_COLUMNS:
            raise ValueError("context feature columns must be canonical")
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class RobustFeatureProcessor:
    medians: Mapping[str, float]
    scales: Mapping[str, float]
    clip_lower: float
    clip_upper: float
    fit_count: int
    fit_digest: str

    def transform(
        self,
        rows: Sequence[CrossSectionalFeatureRow],
    ) -> tuple[CrossSectionalFeatureRow, ...]:
        transformed: list[CrossSectionalFeatureRow] = []
        for row in rows:
            values: dict[str, float] = {}
            for name in CONTEXT_FEATURE_COLUMNS:
                value = row.values[name]
                if not math.isfinite(value):
                    raise ValueError("feature transform values must be finite")
                normalized = (value - self.medians[name]) / self.scales[name]
                values[name] = min(self.clip_upper, max(self.clip_lower, normalized))
            transformed.append(
                CrossSectionalFeatureRow(
                    decision_time=row.decision_time,
                    instrument_id=row.instrument_id,
                    values=values,
                )
            )
        return tuple(transformed)


def build_cross_sectional_context_features(
    panel: DailyPanelLike,
) -> tuple[CrossSectionalFeatureRow, ...]:
    """Build relative price, liquidity, risk and market-state features at close."""

    sessions = tuple(panel.sessions)
    if len(sessions) < 21:
        raise ValueError("context features require at least 21 sessions")
    rows: list[CrossSectionalFeatureRow] = []
    for decision_index in range(20, len(sessions)):
        decision_time = sessions[decision_index]
        eligible_instruments = panel.eligible_by_session[decision_time]
        if not eligible_instruments:
            continue
        window_times = sessions[decision_index - 20 : decision_index + 1]
        benchmark_window = [panel.benchmark_bars[session] for session in window_times]
        market_return_1 = _return(benchmark_window, 1)
        market_volatility = pstdev(_one_day_returns(benchmark_window))
        breadth = _market_breadth(panel, sessions[decision_index - 1], decision_time)
        for instrument_id in sorted(eligible_instruments):
            instrument = panel.instrument_bars[instrument_id]
            if any(session not in instrument for session in window_times):
                continue
            bars = [instrument[session] for session in window_times]
            recent = bars[1:]
            daily_returns = _one_day_returns(bars)
            current = bars[-1]
            low = min(bar.low for bar in recent)
            high = max(bar.high for bar in recent)
            price_range = high - low
            values = {
                "return_1": _return(bars, 1),
                "return_5": _return(bars, 5),
                "return_20": _return(bars, 20),
                "relative_return_1": _return(bars, 1) - market_return_1,
                "relative_return_5": _return(bars, 5) - _return(benchmark_window, 5),
                "relative_return_20": _return(bars, 20)
                - _return(benchmark_window, 20),
                "intraday_return": float(current.close / current.open - 1),
                "amplitude": float(current.high / current.low - 1),
                "volume_ratio_20": float(
                    current.volume / median(bar.volume for bar in recent)
                ),
                "turnover_median_20_log": math.log1p(
                    float(median(bar.turnover for bar in recent))
                ),
                "volatility_20": pstdev(daily_returns),
                "price_position_20": (
                    0.5 if price_range == 0 else float((current.close - low) / price_range)
                ),
                "market_return_1": market_return_1,
                "market_volatility_20": market_volatility,
                "market_breadth": breadth,
            }
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError("context features must be finite")
            rows.append(
                CrossSectionalFeatureRow(
                    decision_time=decision_time,
                    instrument_id=instrument_id,
                    values=values,
                )
            )
    return tuple(rows)


def fit_robust_feature_processor(
    fit_rows: Sequence[CrossSectionalFeatureRow],
) -> RobustFeatureProcessor:
    """Fit median/MAD scaling on an explicitly supplied training segment."""

    rows = tuple(fit_rows)
    if not rows:
        raise ValueError("feature processor fit rows must not be empty")
    medians: dict[str, float] = {}
    scales: dict[str, float] = {}
    for name in CONTEXT_FEATURE_COLUMNS:
        values = [row.values[name] for row in rows]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("feature processor fit values must be finite")
        center = float(median(values))
        mad = float(median(abs(value - center) for value in values))
        medians[name] = center
        scales[name] = max(1.4826 * mad, 1e-12)
    fit_digest = _digest(
        {
            "clip_lower": -3.0,
            "clip_upper": 3.0,
            "fit_count": len(rows),
            "medians": medians,
            "scales": scales,
            "schema_version": "astraquant.robust-feature-processor/v1",
        }
    )
    return RobustFeatureProcessor(
        medians=MappingProxyType(medians),
        scales=MappingProxyType(scales),
        clip_lower=-3.0,
        clip_upper=3.0,
        fit_count=len(rows),
        fit_digest=fit_digest,
    )


def _return(bars: Sequence[MarketBar], horizon: int) -> float:
    return float(bars[-1].close / bars[-1 - horizon].close - 1)


def _one_day_returns(bars: Sequence[MarketBar]) -> list[float]:
    return [
        float(current.close / previous.close - 1)
        for previous, current in pairwise(bars)
    ]


def _market_breadth(
    panel: DailyPanelLike,
    previous_time: datetime,
    decision_time: datetime,
) -> float:
    returns = []
    for instrument_id in sorted(panel.eligible_by_session[decision_time]):
        bars = panel.instrument_bars[instrument_id]
        if previous_time in bars and decision_time in bars:
            returns.append(bars[decision_time].close / bars[previous_time].close - 1)
    if not returns:
        raise ValueError("market breadth has no eligible observations")
    return sum(value > 0 for value in returns) / len(returns)


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

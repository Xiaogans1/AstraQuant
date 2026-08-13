"""Stable contracts for Stage B v2 cross-sectional research and portfolios."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

_TASK_SCHEMA = "astraquant.cross-sectional-task/v1"
_CALIBRATION_SCHEMA = "astraquant.return-calibration/v1"
_PORTFOLIO_SCHEMA = "astraquant.rank-portfolio/v1"


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _text(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _fraction(name: str, value: Decimal, *, allow_zero: bool = False) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    lower_ok = value >= 0 if allow_zero else value > 0
    if not lower_ok or value > 1:
        boundary = "[0, 1]" if allow_zero else "(0, 1]"
        raise ValueError(f"{name} must be finite and in {boundary}")
    return value


@dataclass(frozen=True, slots=True)
class CrossSectionalTaskMatrix:
    """Identity of one execution-aligned multi-horizon daily label matrix."""

    schema_version: str
    benchmark_instrument_id: str
    horizons: tuple[int, ...]
    entry_lag_sessions: int
    extreme_tail_fraction: Decimal

    def __post_init__(self) -> None:
        if self.schema_version != _TASK_SCHEMA:
            raise ValueError("cross-sectional task schema_version mismatch")
        object.__setattr__(
            self,
            "benchmark_instrument_id",
            _text("benchmark_instrument_id", self.benchmark_instrument_id),
        )
        if (
            not self.horizons
            or any(isinstance(value, bool) or value <= 0 for value in self.horizons)
            or self.horizons != tuple(sorted(set(self.horizons)))
        ):
            raise ValueError("horizons must be positive, unique and canonical")
        if self.entry_lag_sessions != 1:
            raise ValueError("entry_lag_sessions must be exactly one")
        tail = _fraction(
            "extreme_tail_fraction",
            self.extreme_tail_fraction,
            allow_zero=True,
        )
        if tail >= Decimal("0.5"):
            raise ValueError("extreme_tail_fraction must be below 0.5")

    @classmethod
    def stage_b_v2_daily(cls, benchmark_instrument_id: str) -> CrossSectionalTaskMatrix:
        return cls(
            schema_version=_TASK_SCHEMA,
            benchmark_instrument_id=benchmark_instrument_id,
            horizons=(1, 5, 10),
            entry_lag_sessions=1,
            extreme_tail_fraction=Decimal("0.025"),
        )

    @property
    def task_digest(self) -> str:
        return _digest(
            {
                "benchmark_instrument_id": self.benchmark_instrument_id,
                "entry_lag_sessions": self.entry_lag_sessions,
                "extreme_tail_fraction": str(self.extreme_tail_fraction),
                "horizons": list(self.horizons),
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class ReturnCalibrationPolicy:
    """Identity and leakage gate for score-to-return calibration."""

    schema_version: str
    method: str
    fit_segment: str
    huber_delta: Decimal
    max_iterations: int

    def __post_init__(self) -> None:
        if self.schema_version != _CALIBRATION_SCHEMA:
            raise ValueError("return calibration schema_version mismatch")
        if self.method != "HUBER_LINEAR":
            raise ValueError("return calibration method must be HUBER_LINEAR")
        if self.fit_segment != "inner_valid":
            raise ValueError("return calibration may only fit inner_valid")
        if not self.huber_delta.is_finite() or self.huber_delta <= 0:
            raise ValueError("huber_delta must be finite and positive")
        if isinstance(self.max_iterations, bool) or self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive")

    @classmethod
    def stage_b_v2(cls) -> ReturnCalibrationPolicy:
        return cls(
            schema_version=_CALIBRATION_SCHEMA,
            method="HUBER_LINEAR",
            fit_segment="inner_valid",
            huber_delta=Decimal("1.345"),
            max_iterations=20,
        )

    @property
    def calibration_digest(self) -> str:
        return _digest(
            {
                "fit_segment": self.fit_segment,
                "huber_delta": str(self.huber_delta),
                "max_iterations": self.max_iterations,
                "method": self.method,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class RankPortfolioPolicy:
    """Frozen selection and risk semantics shared by every Stage B v2 model."""

    schema_version: str
    top_fraction: Decimal
    max_positions: int
    max_instrument_weight: Decimal
    max_one_way_turnover: Decimal

    def __post_init__(self) -> None:
        if self.schema_version != _PORTFOLIO_SCHEMA:
            raise ValueError("rank portfolio schema_version mismatch")
        _fraction("top_fraction", self.top_fraction)
        if isinstance(self.max_positions, bool) or self.max_positions <= 0:
            raise ValueError("max_positions must be positive")
        _fraction("max_instrument_weight", self.max_instrument_weight)
        _fraction("max_one_way_turnover", self.max_one_way_turnover)

    @classmethod
    def stage_b_v2(cls) -> RankPortfolioPolicy:
        return cls(
            schema_version=_PORTFOLIO_SCHEMA,
            top_fraction=Decimal("0.10"),
            max_positions=50,
            max_instrument_weight=Decimal("0.03"),
            max_one_way_turnover=Decimal("0.20"),
        )

    @property
    def policy_digest(self) -> str:
        return _digest(
            {
                "max_instrument_weight": str(self.max_instrument_weight),
                "max_one_way_turnover": str(self.max_one_way_turnover),
                "max_positions": self.max_positions,
                "schema_version": self.schema_version,
                "top_fraction": str(self.top_fraction),
            }
        )

"""Leakage-safe score-to-return calibration for Stage B v2."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from astraquant_domain import ReturnCalibrationPolicy


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    score: float
    realized_return: float


@dataclass(frozen=True, slots=True)
class HuberLinearCalibrator:
    slope: float
    intercept: float
    sample_count: int
    policy_digest: str

    def predict(self, score: float) -> float:
        if not math.isfinite(score):
            raise ValueError("score must be finite")
        return self.intercept + self.slope * score


def fit_huber_linear(
    samples: Sequence[CalibrationSample],
    *,
    policy: ReturnCalibrationPolicy,
    segment: str,
) -> HuberLinearCalibrator:
    """Fit deterministic Huber IRLS using inner validation observations only."""

    if segment != policy.fit_segment:
        raise ValueError("calibrator may only fit inner_valid")
    values = tuple(samples)
    if len(values) < 3:
        raise ValueError("calibration requires at least three samples")
    x = np.asarray([item.score for item in values], dtype=np.float64)
    y = np.asarray([item.realized_return for item in values], dtype=np.float64)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("calibration samples must be finite")
    if np.ptp(x) <= 1e-12:
        return HuberLinearCalibrator(
            slope=0.0,
            intercept=float(np.median(y)),
            sample_count=len(values),
            policy_digest=policy.calibration_digest,
        )

    design = np.column_stack((x, np.ones_like(x)))
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    for _ in range(policy.max_iterations):
        residual = y - design @ beta
        median = float(np.median(residual))
        mad = float(np.median(np.abs(residual - median)))
        threshold = float(policy.huber_delta) * max(1.4826 * mad, 1e-12)
        weights = _huber_weights(residual, threshold)
        root_weights = np.sqrt(weights)
        weighted_design = design * root_weights[:, None]
        weighted_target = y * root_weights
        beta = np.linalg.lstsq(weighted_design, weighted_target, rcond=None)[0]

    return HuberLinearCalibrator(
        slope=float(beta[0]),
        intercept=float(beta[1]),
        sample_count=len(values),
        policy_digest=policy.calibration_digest,
    )


def _huber_weights(
    residual: NDArray[np.float64],
    threshold: float,
) -> NDArray[np.float64]:
    absolute = np.abs(residual)
    weights = np.ones_like(absolute)
    outside = absolute > threshold
    weights[outside] = threshold / absolute[outside]
    return weights

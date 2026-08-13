from __future__ import annotations

import math

import pytest

from astraquant_domain import ReturnCalibrationPolicy
from astraquant_quant.return_calibration import (
    CalibrationSample,
    fit_huber_linear,
)


def _policy() -> ReturnCalibrationPolicy:
    return ReturnCalibrationPolicy.stage_b_v2()


def _samples() -> list[CalibrationSample]:
    return [
        CalibrationSample(score=float(value), realized_return=2.0 * value + 1.0)
        for value in range(20)
    ]


def test_huber_calibration_is_robust_and_deterministic() -> None:
    samples = _samples()
    samples.append(CalibrationSample(score=10.0, realized_return=-10000.0))

    first = fit_huber_linear(samples, policy=_policy(), segment="inner_valid")
    second = fit_huber_linear(samples, policy=_policy(), segment="inner_valid")

    assert first == second
    assert 1.5 < first.slope < 2.5
    assert 0.5 < first.intercept < 1.5
    assert first.sample_count == 21
    assert first.policy_digest == _policy().calibration_digest


def test_outer_test_cannot_fit_calibrator() -> None:
    with pytest.raises(ValueError, match="inner_valid"):
        fit_huber_linear(_samples(), policy=_policy(), segment="outer_test")


def test_outer_test_mutation_cannot_change_inner_valid_fit() -> None:
    inner_valid = _samples()
    outer_test = [CalibrationSample(score=1.0, realized_return=3.0)]
    first = fit_huber_linear(inner_valid, policy=_policy(), segment="inner_valid")
    outer_test[0] = CalibrationSample(score=1.0, realized_return=-100000.0)

    second = fit_huber_linear(inner_valid, policy=_policy(), segment="inner_valid")

    assert outer_test[0].realized_return == -100000.0
    assert first == second


def test_constant_scores_use_median_return() -> None:
    samples = [
        CalibrationSample(score=4.0, realized_return=value)
        for value in (1.0, 3.0, 100.0)
    ]

    calibrator = fit_huber_linear(samples, policy=_policy(), segment="inner_valid")

    assert calibrator.slope == 0.0
    assert calibrator.intercept == 3.0
    assert calibrator.predict(999.0) == 3.0


@pytest.mark.parametrize("count", [0, 1, 2])
def test_calibration_requires_at_least_three_samples(count: int) -> None:
    with pytest.raises(ValueError, match="at least three"):
        fit_huber_linear(_samples()[:count], policy=_policy(), segment="inner_valid")


@pytest.mark.parametrize(
    ("score", "realized_return"),
    [
        (math.nan, 1.0),
        (math.inf, 1.0),
        (1.0, math.nan),
        (1.0, -math.inf),
    ],
)
def test_calibration_rejects_non_finite_samples(
    score: float,
    realized_return: float,
) -> None:
    samples = _samples()
    samples[0] = CalibrationSample(score=score, realized_return=realized_return)
    with pytest.raises(ValueError, match="finite"):
        fit_huber_linear(samples, policy=_policy(), segment="inner_valid")


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf])
def test_predict_rejects_non_finite_scores(score: float) -> None:
    calibrator = fit_huber_linear(_samples(), policy=_policy(), segment="inner_valid")
    with pytest.raises(ValueError, match="finite"):
        calibrator.predict(score)

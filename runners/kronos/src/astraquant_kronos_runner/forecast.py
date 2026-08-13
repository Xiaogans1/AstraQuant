"""Convert sampled Kronos close paths into declared forecast semantics."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence


def summarize_paths(
    *,
    last_close: float,
    paths: Sequence[Sequence[float]],
    sample_count: int,
    prediction_length: int,
) -> dict[str, float]:
    if not math.isfinite(last_close) or last_close <= 0:
        raise ValueError("last close must be positive and finite")
    exact = tuple(tuple(path) for path in paths)
    if len(exact) != sample_count or any(len(path) != prediction_length for path in exact):
        raise ValueError("Kronos path count or length mismatch")
    values = [value for path in exact for value in path]
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("Kronos paths must contain positive finite closes")
    terminal_returns = sorted(path[-1] / last_close - 1 for path in exact)
    step_returns = []
    for path in exact:
        previous = last_close
        for value in path:
            step_returns.append(value / previous - 1)
            previous = value
    p10 = _quantile(terminal_returns, 0.1)
    p50 = _quantile(terminal_returns, 0.5)
    p90 = _quantile(terminal_returns, 0.9)
    return {
        "expected_return": p50,
        "up_path_fraction": sum(value > 0 for value in terminal_returns) / len(exact),
        "terminal_return_p10": p10,
        "terminal_return_p50": p50,
        "terminal_return_p90": p90,
        "predicted_volatility": statistics.pstdev(step_returns),
        "uncertainty_width": p90 - p10,
    }


def _quantile(ordered: Sequence[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight

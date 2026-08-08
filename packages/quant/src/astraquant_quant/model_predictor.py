"""Shared point-in-time model predictor for replay tools and the API.

The predictor is deliberately identical across training-adjacent surfaces:
rolling features are computed per trading day (matching ``build_training_rows``)
so overnight gaps never pollute intraday statistics, and ``None`` is returned
when the current day does not yet provide enough completed bars — the replay
engine treats ``None`` as HOLD (no information, no action).
"""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb

from astraquant_data.market_bars import MarketBar
from astraquant_quant.replay import Predictor
from astraquant_quant.research_features import build_feature_rows
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS

_MIN_BARS_PER_DAY = 30
_INFERENCE_WINDOW = 60


def make_model_predictor(artifact: str | Path) -> Predictor:
    """Build a LightGBM up-probability predictor with day-reset features."""
    booster = lgb.Booster(model_file=str(artifact))

    def predict(completed: list[MarketBar]) -> float | None:
        latest = completed[-1]
        day = latest.timestamp.date()
        # Collect the current trading day's bars from the tail (≤ _INFERENCE_WINDOW).
        window: list[MarketBar] = []
        for bar in reversed(completed):
            if bar.timestamp.date() != day:
                break
            window.append(bar)
            if len(window) >= _INFERENCE_WINDOW:
                break
        window.reverse()
        if len(window) < _MIN_BARS_PER_DAY:
            return None
        features = build_feature_rows(window)
        if not features:
            return None
        latest_row = features[-1]
        proba = booster.predict([[float(latest_row[key]) for key in MODEL_FEATURE_COLUMNS]])
        return float(proba[0])

    return predict

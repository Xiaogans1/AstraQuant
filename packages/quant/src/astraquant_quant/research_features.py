"""Look-ahead-safe minute features and forward labels for model research."""

from __future__ import annotations

from decimal import Decimal

from astraquant_data.market_bars import MarketBar

_WINDOW = 30


def label_future_return(
    bars: list[MarketBar],
    *,
    index: int,
    horizon: int,
    threshold: Decimal,
) -> int:
    end = index + horizon
    if end >= len(bars):
        return -1
    entry = bars[index].close
    exit_price = bars[end].close
    change = (exit_price - entry) / entry
    if change >= threshold:
        return 1
    return 0


def build_feature_rows(bars: list[MarketBar]) -> list[dict[str, float | int]]:
    closes = [item.close for item in bars]
    volumes = [item.volume for item in bars]
    rows: list[dict[str, float | int]] = []
    for index in range(_WINDOW, len(bars)):
        window_close = closes[index - _WINDOW : index + 1]
        window_volume = volumes[index - _WINDOW : index + 1]
        base = window_close[-1]
        vwap = sum(c * v for c, v in zip(window_close, window_volume, strict=True)) / max(
            sum(window_volume), Decimal("1")
        )
        avg_volume = sum(window_volume[:-1]) / Decimal(max(len(window_volume) - 1, 1))
        rows.append(
            {
                "close": float(base),
                "return_1": float((base - window_close[-2]) / window_close[-2]),
                "return_3": float((base - window_close[-4]) / window_close[-4]),
                "return_5": float((base - window_close[-6]) / window_close[-6]),
                "return_10": float((base - window_close[-11]) / window_close[-11]),
                "volatility_5": float((max(window_close[-6:]) - min(window_close[-6:])) / base),
                "vwap_deviation": float((base - vwap) / vwap),
                "volume_ratio": float(volumes[index] / avg_volume),
                "day_high_position": float(
                    (base - min(window_close))
                    / max(max(window_close) - min(window_close), Decimal("1e-9"))
                ),
                "ma5_gap": float((base - sum(window_close[-5:]) / 5) / base),
                "ma20_gap": float((base - sum(window_close[-20:]) / 20) / base),
            }
        )
    return rows

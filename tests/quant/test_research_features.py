from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_quant.research_features import build_feature_rows, label_future_return


def _bars(closes: list[str], volumes: list[str] | None = None) -> list[MarketBar]:
    start = datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    result: list[MarketBar] = []
    for index, close in enumerate(closes):
        volume = Decimal("100") if volumes is None else Decimal(volumes[index])
        result.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index),
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=volume,
                turnover=Decimal(close) * volume,
                previous_close=Decimal("10"),
            )
        )
    return result


def test_label_uses_only_future_completed_bars() -> None:
    closes = ["10"] * 10 + ["10.2", "10.25", "10.3", "10.4"]
    rows = _bars(closes)
    label = label_future_return(rows, index=9, horizon=3, threshold=Decimal("0.01"))
    assert label == 1
    label_down = label_future_return(rows, index=0, horizon=3, threshold=Decimal("0.01"))
    assert label_down == 0


def test_features_never_see_future_bars() -> None:
    rows = _bars([str(10 + i / 100) for i in range(40)])
    features = build_feature_rows(rows)
    assert len(features) == 10
    for index, row in enumerate(features):
        assert row["close"] == float(rows[index + 30].close)
        assert "future" not in row


def test_label_returns_minus_one_without_enough_future_bars() -> None:
    rows = _bars(["10"] * 5)
    label = label_future_return(rows, index=len(rows) - 1, horizon=1, threshold=Decimal("0.01"))
    assert label == -1


def test_zero_volume_windows_produce_safe_values() -> None:
    rows = _bars(["10"] * 35, volumes=["0"] * 35)
    features = build_feature_rows(rows)
    assert len(features) == 5
    for row in features:
        assert row["volume_ratio"] == 0.0
        assert row["vwap_deviation"] == 0.0


def test_label_rejects_invalid_horizon_and_index() -> None:
    rows = _bars(["10"] * 5)
    assert label_future_return(rows, index=2, horizon=0, threshold=Decimal("0.01")) == -1
    assert label_future_return(rows, index=-1, horizon=1, threshold=Decimal("0.01")) == -1

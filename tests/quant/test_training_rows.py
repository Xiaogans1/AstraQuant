from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_quant.research_features import build_training_rows


def _bars(closes: list[str], *, day: int = 7) -> list[MarketBar]:
    start = datetime(2026, 8, day, 1, 30, tzinfo=UTC)
    result: list[MarketBar] = []
    for index, close in enumerate(closes):
        result.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index),
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal("100"),
                turnover=Decimal(close) * 100,
                previous_close=Decimal("10"),
            )
        )
    return result


def test_training_rows_include_label_and_future_return() -> None:
    closes = ["10"] * 35 + ["10.05"] * 5 + ["10"] * 20
    rows = build_training_rows(_bars(closes), horizon=5, threshold=Decimal("0.005"))

    assert len(rows) > 0
    for row in rows:
        assert "label" in row
        assert row["label"] in (0, 1)
        assert "future_return" in row
        assert "return_1" in row
        assert "close" in row

    labeled = [row for row in rows if row["close"] == 10.0 and row["label"] == 1]
    assert labeled, "bars entering a +0.5% window should be labeled 1"
    rising_future = [row for row in labeled if row["future_return"] > 0]
    assert rising_future, "first bar of the rising window should have a positive next-bar return"


def test_training_rows_do_not_span_across_days() -> None:
    first_day = _bars(["10"] * 40, day=6)
    second_day = _bars(["10"] * 40, day=7)
    rows = build_training_rows(
        [*first_day, *second_day],
        horizon=5,
        threshold=Decimal("0.005"),
    )

    assert len(rows) == 2 * (40 - 30 - 5)
    for row in rows:
        assert "label" in row
        assert "future_return" in row


def test_label_and_future_return_use_the_same_holding_interval() -> None:
    closes = ["10"] * 31 + ["11"] + ["10"] * 3 + ["9"] + ["9"] * 5

    rows = build_training_rows(
        _bars(closes),
        horizon=5,
        threshold=Decimal("0.005"),
    )

    first = rows[0]
    assert first["close"] == 10.0
    assert first["label"] == 0
    assert first["future_return"] == -0.1

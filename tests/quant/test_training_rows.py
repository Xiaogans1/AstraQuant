from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_data.market_bars import MarketBar
from astraquant_quant.research_features import build_training_bundle, build_training_rows


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

    assert len(rows) == 2 * (40 - 30 - 5 - 1)
    for row in rows:
        assert "label" in row
        assert "future_return" in row


def test_training_bundle_maps_each_row_to_its_ordered_decision_bar() -> None:
    first_day = _bars(["10"] * 40, day=6)
    second_day = _bars(["11"] * 40, day=7)

    bundle = build_training_bundle(
        [*second_day, *first_day],
        horizon=5,
        threshold=Decimal("0.005"),
    )

    assert bundle.ordered_bars == [*first_day, *second_day]
    assert bundle.row_bar_indices == [30, 31, 32, 33, 70, 71, 72, 73]
    assert [bundle.ordered_bars[index].close for index in bundle.row_bar_indices] == [
        Decimal(str(row["close"])) for row in bundle.rows
    ]


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
    assert first["future_return"] == pytest.approx(-2 / 11)


def test_training_return_uses_next_open_entry_and_exit() -> None:
    bars = _bars(["10"] * 34)
    exit_bar = bars[33]
    bars[33] = MarketBar(
        timestamp=exit_bar.timestamp,
        open=Decimal("11"),
        high=Decimal("11"),
        low=Decimal("10"),
        close=Decimal("10"),
        volume=exit_bar.volume,
        turnover=Decimal("1050"),
        previous_close=exit_bar.previous_close,
    )

    rows = build_training_rows(bars, horizon=2, threshold=Decimal("0.05"))

    assert len(rows) == 1
    assert rows[0]["future_return"] == pytest.approx(0.10)
    assert rows[0]["label"] == 1

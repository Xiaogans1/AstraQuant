from datetime import datetime
from decimal import Decimal

import pytest

from astraquant_data.market_bars import (
    MarketBar,
    MarketPeriod,
    aggregate_daily_bars,
    normalize_market_bars,
)


def bar(
    timestamp: str,
    *,
    open: str,
    high: str,
    low: str,
    close: str,
    volume: str,
    turnover: str,
    previous_close: str | None = None,
) -> MarketBar:
    return MarketBar(
        timestamp=datetime.fromisoformat(timestamp),
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        turnover=Decimal(turnover),
        previous_close=None if previous_close is None else Decimal(previous_close),
    )


def test_market_bar_rejects_naive_time_and_invalid_ohlc() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        bar(
            "2026-08-06T10:00:00",
            open="10",
            high="11",
            low="9",
            close="10",
            volume="1",
            turnover="10",
        )
    with pytest.raises(ValueError, match="high"):
        bar(
            "2026-08-06T10:00:00+08:00",
            open="10",
            high="9",
            low="8",
            close="10",
            volume="1",
            turnover="10",
        )


def test_normalization_sorts_and_keeps_the_latest_duplicate() -> None:
    rows = [
        {
            "bob": "2026-08-06T10:01:00+08:00",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10.5,
            "volume": 2,
            "amount": 20,
        },
        {
            "bob": "2026-08-06T10:00:00+08:00",
            "open": 9,
            "high": 10,
            "low": 8,
            "close": 9.5,
            "volume": 1,
            "amount": 9,
        },
        {
            "bob": "2026-08-06T10:01:00+08:00",
            "open": 10,
            "high": 12,
            "low": 9,
            "close": 11,
            "volume": 3,
            "amount": 30,
        },
    ]

    result = normalize_market_bars(rows)

    assert [item.timestamp.minute for item in result] == [0, 1]
    assert result[-1].close == 11
    assert result[-1].turnover == 30


@pytest.mark.parametrize(
    ("period", "expected_count", "expected_first_open", "expected_last_close"),
    [
        (MarketPeriod.WEEK, 3, Decimal("10"), Decimal("17")),
        (MarketPeriod.MONTH, 3, Decimal("10"), Decimal("17")),
        (MarketPeriod.YEAR, 2, Decimal("10"), Decimal("17")),
    ],
)
def test_aggregates_daily_ohlcv_by_calendar_period(
    period: MarketPeriod,
    expected_count: int,
    expected_first_open: Decimal,
    expected_last_close: Decimal,
) -> None:
    daily = [
        bar(
            "2025-12-30T00:00:00+08:00",
            open="10",
            high="12",
            low="9",
            close="11",
            volume="100",
            turnover="1000",
            previous_close="9.5",
        ),
        bar(
            "2025-12-31T00:00:00+08:00",
            open="11",
            high="13",
            low="10",
            close="12",
            volume="200",
            turnover="2200",
            previous_close="11",
        ),
        bar(
            "2026-01-02T00:00:00+08:00",
            open="12",
            high="14",
            low="11",
            close="13",
            volume="300",
            turnover="3600",
            previous_close="12",
        ),
        bar(
            "2026-02-02T00:00:00+08:00",
            open="14",
            high="16",
            low="13",
            close="15",
            volume="400",
            turnover="5600",
            previous_close="13",
        ),
        bar(
            "2026-02-09T00:00:00+08:00",
            open="15",
            high="18",
            low="14",
            close="17",
            volume="500",
            turnover="7500",
            previous_close="15",
        ),
    ]

    result = aggregate_daily_bars(daily, period)

    assert len(result) == expected_count
    assert result[0].open == expected_first_open
    assert result[-1].close == expected_last_close
    assert result[0].previous_close == Decimal("9.5")
    assert max(item.high for item in result) == Decimal("18")
    assert sum(item.volume for item in result) == Decimal("1500")
    assert sum(item.turnover for item in result) == Decimal("19900")

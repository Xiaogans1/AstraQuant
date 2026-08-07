from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_domain import Adjustment, BarFrequency, InstrumentId
from tools.research.fetch_minutes import bars_to_domain_bars


def test_market_bars_convert_to_domain_bars_without_lookahead() -> None:
    rows = [
        MarketBar(
            timestamp=datetime(2026, 8, 7, 1, 30, tzinfo=UTC),
            open=Decimal("10"),
            high=Decimal("10.1"),
            low=Decimal("9.9"),
            close=Decimal("10.05"),
            volume=Decimal("100"),
            turnover=Decimal("1000"),
            previous_close=Decimal("9.9"),
        )
    ]
    result = bars_to_domain_bars(InstrumentId.parse("159516.SZSE"), rows)
    assert len(result) == 1
    bar = result[0]
    assert bar.frequency is BarFrequency.MINUTE
    assert bar.adjustment is Adjustment.NONE
    assert bar.event_time == datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    assert bar.available_time == datetime(2026, 8, 7, 1, 31, tzinfo=UTC)
    assert bar.close == Decimal("10.05")
    assert bar.trading_date == date(2026, 8, 7)


def test_market_bars_spanning_multiple_dates_keep_their_own_trading_dates() -> None:
    rows = [
        MarketBar(
            timestamp=datetime(2026, 8, 6, 1, 30, tzinfo=UTC),
            open=Decimal("10"),
            high=Decimal("10.1"),
            low=Decimal("9.9"),
            close=Decimal("10.05"),
            volume=Decimal("100"),
            turnover=Decimal("1000"),
            previous_close=Decimal("9.9"),
        ),
        MarketBar(
            timestamp=datetime(2026, 8, 7, 1, 30, tzinfo=UTC),
            open=Decimal("10.2"),
            high=Decimal("10.3"),
            low=Decimal("10.1"),
            close=Decimal("10.25"),
            volume=Decimal("120"),
            turnover=Decimal("1230"),
            previous_close=Decimal("10.05"),
        ),
    ]
    result = bars_to_domain_bars(InstrumentId.parse("159516.SZSE"), rows)
    assert len(result) == 2
    assert [bar.trading_date for bar in result] == [date(2026, 8, 6), date(2026, 8, 7)]

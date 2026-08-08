from datetime import date
from pathlib import Path

import pytest

from astraquant_data.calendars import CsvTradingCalendar
from astraquant_domain import Venue

FIXTURES = Path("tests/fixtures/market_data")


def test_futures_trading_date_can_start_on_previous_natural_date() -> None:
    calendar = CsvTradingCalendar.load(
        FIXTURES / "cn_futures_sessions.csv",
        expected_venue=Venue.SHFE,
        source_version="fixture-v1",
    )

    session = calendar.session(date(2026, 7, 24))

    assert session.session_open.date() == date(2026, 7, 23)
    assert session.session_close.date() == date(2026, 7, 24)
    assert calendar.is_session(date(2026, 7, 24))


def test_calendar_version_is_reproducible() -> None:
    first = CsvTradingCalendar.load(
        FIXTURES / "cn_equity_sessions.csv",
        expected_venue=Venue.SSE,
        source_version="fixture-v1",
    )
    second = CsvTradingCalendar.load(
        FIXTURES / "cn_equity_sessions.csv",
        expected_venue=Venue.SSE,
        source_version="fixture-v1",
    )

    assert first.calendar_version == second.calendar_version
    assert len(first.calendar_version) == 64


def test_calendar_rejects_a_mismatched_venue() -> None:
    with pytest.raises(ValueError, match="venue"):
        CsvTradingCalendar.load(
            FIXTURES / "cn_equity_sessions.csv",
            expected_venue=Venue.SHFE,
            source_version="fixture-v1",
        )

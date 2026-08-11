from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from astraquant_data.calendars import (
    CsvTradingCalendar,
    SessionSegment,
    expected_bar_intervals,
)
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


def _segment(segment_id: str, start_hour: int, end_hour: int) -> SessionSegment:
    return SessionSegment(
        venue=Venue.SSE,
        trading_date=date(2026, 8, 10),
        segment_id=segment_id,
        segment_open=datetime(2026, 8, 10, start_hour, tzinfo=UTC),
        segment_close=datetime(2026, 8, 10, end_hour, tzinfo=UTC),
    )


def test_equity_minute_expectations_do_not_cross_lunch_break() -> None:
    intervals = expected_bar_intervals(
        segments=(_segment("AM", 1, 3), _segment("PM", 5, 7)),
        interval=timedelta(minutes=1),
        calendar_snapshot_id=f"sha256:{'1' * 64}",
    )

    assert len(intervals) == 240
    assert intervals[119].interval_end == datetime(2026, 8, 10, 3, tzinfo=UTC)
    assert intervals[120].interval_start == datetime(2026, 8, 10, 5, tzinfo=UTC)
    assert all(item.event_time == item.interval_end for item in intervals)


def test_half_day_expectation_contains_only_declared_segment() -> None:
    intervals = expected_bar_intervals(
        segments=(_segment("AM", 1, 3),),
        interval=timedelta(minutes=1),
        calendar_snapshot_id=f"sha256:{'2' * 64}",
    )

    assert len(intervals) == 120


def test_segments_reject_naive_overlap_and_non_divisible_intervals() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SessionSegment(
            venue=Venue.SSE,
            trading_date=date(2026, 8, 10),
            segment_id="AM",
            segment_open=datetime(2026, 8, 10, 1),
            segment_close=datetime(2026, 8, 10, 3),
        )

    with pytest.raises(ValueError, match="overlap"):
        expected_bar_intervals(
            segments=(_segment("FIRST", 1, 3), _segment("OVERLAP", 2, 4)),
            interval=timedelta(minutes=1),
            calendar_snapshot_id=f"sha256:{'3' * 64}",
        )

    with pytest.raises(ValueError, match="divide"):
        expected_bar_intervals(
            segments=(_segment("ODD", 1, 3),),
            interval=timedelta(minutes=7),
            calendar_snapshot_id=f"sha256:{'4' * 64}",
        )

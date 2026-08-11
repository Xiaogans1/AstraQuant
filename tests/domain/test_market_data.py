from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from astraquant_domain import (
    Adjustment,
    AvailabilityBasis,
    Bar,
    BarFrequency,
    InstrumentId,
    ObservationInterval,
    Tick,
    VintageKind,
)


def make_bar(**changes: object) -> Bar:
    values: dict[str, object] = {
        "instrument_id": InstrumentId.parse("600000.SSE"),
        "frequency": BarFrequency.DAY,
        "trading_date": date(2026, 7, 24),
        "event_time": datetime(2026, 7, 24, 7, 0, tzinfo=UTC),
        "available_time": datetime(2026, 7, 24, 7, 1, tzinfo=UTC),
        "open": Decimal("10.00"),
        "high": Decimal("10.80"),
        "low": Decimal("9.90"),
        "close": Decimal("10.50"),
        "volume": Decimal("120000"),
        "turnover": Decimal("1250000"),
        "open_interest": None,
        "settlement": None,
        "adjustment": Adjustment.NONE,
        "availability_estimated": True,
    }
    values.update(changes)
    return Bar(**values)  # type: ignore[arg-type]


def test_bar_accepts_valid_ohlc_and_point_in_time_order() -> None:
    assert make_bar().close == Decimal("10.50")


def test_bar_keeps_trading_date_separate_from_event_natural_date() -> None:
    bar = make_bar(
        trading_date=date(2026, 7, 25),
        event_time=datetime(2026, 7, 24, 13, 0, tzinfo=UTC),
        available_time=datetime(2026, 7, 24, 13, 0, 1, tzinfo=UTC),
    )

    assert bar.trading_date == date(2026, 7, 25)
    assert bar.event_time.date() == date(2026, 7, 24)


@pytest.mark.parametrize(
    ("field", "value"),
    [("high", Decimal("9.99")), ("low", Decimal("10.01"))],
)
def test_bar_rejects_impossible_ohlc(field: str, value: Decimal) -> None:
    with pytest.raises(ValueError, match="OHLC"):
        make_bar(**{field: value})


def test_bar_rejects_information_available_before_market_event() -> None:
    with pytest.raises(ValueError, match="available_time"):
        make_bar(available_time=datetime(2026, 7, 24, 6, 59, tzinfo=UTC))


def test_bar_rejects_naive_market_time() -> None:
    with pytest.raises(ValueError, match="event_time"):
        make_bar(event_time=datetime(2026, 7, 24, 7, 0))


def test_tick_requires_positive_price_and_non_negative_volume() -> None:
    with pytest.raises(ValueError, match="price"):
        Tick(
            instrument_id=InstrumentId.parse("RB2610.SHFE"),
            event_time=datetime(2026, 7, 24, 1, 0, tzinfo=UTC),
            available_time=datetime(2026, 7, 24, 1, 0, 1, tzinfo=UTC),
            last_price=Decimal("0"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        )


def test_observation_interval_binds_exact_calendar_close() -> None:
    interval = ObservationInterval(
        interval_start=datetime(2026, 7, 24, 1, 30, tzinfo=UTC),
        interval_end=datetime(2026, 7, 24, 7, 0, tzinfo=UTC),
        event_time=datetime(2026, 7, 24, 7, 0, tzinfo=UTC),
        calendar_snapshot_id="sha256:" + "1" * 64,
    )

    assert interval.event_time == interval.interval_end
    assert VintageKind.SOURCE_VERSIONED.value == "SOURCE_VERSIONED"
    assert AvailabilityBasis.SESSION_CLOSE.value == "SESSION_CLOSE"


@pytest.mark.parametrize(
    "changes",
    [
        {"interval_start": datetime(2026, 7, 24, 7, 0)},
        {"interval_start": datetime(2026, 7, 24, 7, 0, tzinfo=UTC)},
        {"event_time": datetime(2026, 7, 24, 6, 59, tzinfo=UTC)},
        {"calendar_snapshot_id": "sha256:" + "0" * 64},
    ],
)
def test_observation_interval_rejects_guessed_or_invalid_boundaries(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "interval_start": datetime(2026, 7, 24, 1, 30, tzinfo=UTC),
        "interval_end": datetime(2026, 7, 24, 7, 0, tzinfo=UTC),
        "event_time": datetime(2026, 7, 24, 7, 0, tzinfo=UTC),
        "calendar_snapshot_id": "sha256:" + "1" * 64,
    }
    values.update(changes)

    with pytest.raises(ValueError):
        ObservationInterval(**values)  # type: ignore[arg-type]

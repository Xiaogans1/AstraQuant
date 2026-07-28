from datetime import UTC, datetime
from decimal import Decimal

import pytest

from astraquant_domain import (
    Adjustment,
    Bar,
    BarFrequency,
    InstrumentId,
    Tick,
)


def make_bar(**changes: object) -> Bar:
    values: dict[str, object] = {
        "instrument_id": InstrumentId.parse("600000.SSE"),
        "frequency": BarFrequency.DAY,
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

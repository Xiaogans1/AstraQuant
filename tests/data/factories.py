from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId


def make_bar(
    *,
    symbol: str = "600000.SSE",
    day: int = 24,
    close: str = "10.50",
    available_time: datetime | None = None,
    availability_estimated: bool = True,
    trading_date: date | None = None,
) -> Bar:
    event_time = datetime(2026, 7, day, 7, 0, tzinfo=UTC)
    parsed_close = Decimal(close)
    return Bar(
        instrument_id=InstrumentId.parse(symbol),
        frequency=BarFrequency.DAY,
        trading_date=trading_date or date(2026, 7, day),
        event_time=event_time,
        available_time=available_time or event_time + timedelta(minutes=1),
        open=Decimal("10.00"),
        high=max(Decimal("10.80"), parsed_close),
        low=Decimal("9.90"),
        close=parsed_close,
        volume=Decimal("120000"),
        turnover=Decimal("1250000"),
        open_interest=None,
        settlement=None,
        adjustment=Adjustment.NONE,
        availability_estimated=availability_estimated,
    )

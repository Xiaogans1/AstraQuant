from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from astraquant_domain import LiveQuote, MarketEventQuality, QuoteLevel
from astraquant_domain.identifiers import InstrumentId


def test_live_quote_preserves_real_source_and_previous_close() -> None:
    now = datetime(2026, 8, 5, 2, 30, tzinfo=UTC)
    quote = LiveQuote(
        instrument_id=InstrumentId.parse("000001.SSE"),
        trading_date=date(2026, 8, 5),
        event_time=now,
        received_time=now,
        last_price=Decimal("3560.12"),
        previous_close=Decimal("3540.00"),
        open=Decimal("3544.20"),
        high=Decimal("3565.10"),
        low=Decimal("3538.40"),
        cumulative_volume=Decimal("1200"),
        cumulative_turnover=Decimal("4300000"),
        open_interest=None,
        bid=(),
        ask=(),
        source_id="eastmoney",
        quality=frozenset({MarketEventQuality.NORMAL}),
    )

    assert quote.change == Decimal("20.12")
    assert quote.change_percent == Decimal("0.5684")
    assert quote.source_id == "eastmoney"


def test_quote_rejects_naive_source_times() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        LiveQuote.minimum(
            InstrumentId.parse("000001.SSE"),
            event_time=datetime(2026, 8, 5, 10, 30),
            last_price=Decimal("3560"),
            previous_close=Decimal("3540"),
        )


def test_depth_allows_an_empty_valid_level() -> None:
    level = QuoteLevel(price=Decimal("1"), volume=Decimal("0"))
    assert level.volume == 0


def test_depth_rejects_invalid_price_and_volume() -> None:
    with pytest.raises(ValueError, match="price"):
        QuoteLevel(price=Decimal("0"), volume=Decimal("1"))
    with pytest.raises(ValueError, match="volume"):
        QuoteLevel(price=Decimal("1"), volume=Decimal("-1"))


def test_quote_rejects_inconsistent_prices_and_excess_depth() -> None:
    now = datetime(2026, 8, 5, 2, 30, tzinfo=UTC)
    with pytest.raises(ValueError, match="high"):
        LiveQuote(
            instrument_id=InstrumentId.parse("000001.SSE"),
            trading_date=date(2026, 8, 5),
            event_time=now,
            received_time=now,
            last_price=Decimal("10"),
            previous_close=Decimal("9"),
            open=Decimal("10"),
            high=Decimal("9"),
            low=Decimal("8"),
            cumulative_volume=Decimal("0"),
            cumulative_turnover=None,
            open_interest=None,
            bid=(),
            ask=(),
            source_id="eastmoney",
            quality=frozenset({MarketEventQuality.NORMAL}),
        )

    levels = tuple(QuoteLevel(Decimal(index + 1), Decimal("1")) for index in range(11))
    with pytest.raises(ValueError, match="ten"):
        LiveQuote.minimum(
            InstrumentId.parse("000001.SSE"),
            event_time=now,
            last_price=Decimal("10"),
            previous_close=Decimal("9"),
            bid=levels,
        )


def test_quote_handles_a_missing_previous_close_without_inventing_a_move() -> None:
    quote = LiveQuote.minimum(
        InstrumentId.parse("000001.SSE"),
        event_time=datetime(2026, 8, 5, 2, 30, tzinfo=UTC),
        last_price=Decimal("10"),
        previous_close=None,
    )

    assert quote.change is None
    assert quote.change_percent is None

import asyncio
import inspect
from datetime import UTC, date, datetime
from decimal import Decimal

from astraquant_data.adapters.replay import ReplayStreamingProvider
from astraquant_data.providers import HistoricalDataProvider, StreamingDataProvider
from astraquant_domain import BarFrequency, InstrumentId, Tick


def test_provider_contracts_have_no_trading_operations() -> None:
    methods = {
        name
        for protocol in (HistoricalDataProvider, StreamingDataProvider)
        for name, value in inspect.getmembers(protocol, inspect.isfunction)
    }
    forbidden = {
        "order",
        "submit_order",
        "cancel_order",
        "account",
        "position",
        "balance",
    }
    assert methods.isdisjoint(forbidden)
    assert {"provider_id", "fetch_bars"}.issubset(methods)
    assert {"provider_id", "subscribe"}.issubset(methods)


def test_history_request_rejects_an_inverted_range() -> None:
    from astraquant_data.providers import HistoryRequest

    try:
        HistoryRequest(
            instrument_id=InstrumentId.parse("600000.SSE"),
            frequency=BarFrequency.DAY,
            start=date(2026, 7, 25),
            end=date(2026, 7, 24),
        )
    except ValueError as error:
        assert "end" in str(error)
    else:
        raise AssertionError("inverted range was accepted")


def test_replay_stream_filters_instruments_and_orders_events() -> None:
    selected = InstrumentId.parse("600000.SSE")
    ignored = InstrumentId.parse("000001.SZSE")
    later = Tick(
        selected,
        datetime(2026, 7, 24, 7, 1, tzinfo=UTC),
        datetime(2026, 7, 24, 7, 1, 1, tzinfo=UTC),
        Decimal("10.2"),
        Decimal("2"),
        None,
        None,
    )
    earlier = Tick(
        selected,
        datetime(2026, 7, 24, 7, 0, tzinfo=UTC),
        datetime(2026, 7, 24, 7, 0, 1, tzinfo=UTC),
        Decimal("10.1"),
        Decimal("1"),
        None,
        None,
    )
    other = Tick(
        ignored,
        datetime(2026, 7, 24, 6, 59, tzinfo=UTC),
        datetime(2026, 7, 24, 6, 59, 1, tzinfo=UTC),
        Decimal("9.9"),
        Decimal("1"),
        None,
        None,
    )
    provider = ReplayStreamingProvider((later, other, earlier))

    async def collect() -> list[Tick]:
        return [event async for event in provider.subscribe((selected,)) if isinstance(event, Tick)]

    assert asyncio.run(collect()) == [earlier, later]

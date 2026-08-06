import inspect
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from astraquant_data.adapters.eastmoney import EastmoneyProvider
from astraquant_data.live_providers import ConnectionState
from astraquant_data.market_bars import MarketPeriod
from astraquant_domain import FixedClock, InstrumentId


class FakeBridgeClient:
    def __init__(self) -> None:
        self.started = 0
        self.configured: list[str] = []
        self.current_symbols: list[list[str]] = []
        self.history_requests: list[dict[str, Any]] = []
        self.search_queries: list[str] = []
        self.fail_current = False
        self.omit_previous_close = False

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        return None

    def configure(self, token: str) -> None:
        self.configured.append(token)

    def current(self, symbols: list[str]) -> list[dict[str, Any]]:
        self.current_symbols.append(symbols)
        if self.fail_current:
            raise RuntimeError("child failed with private details")
        valid = {
            "symbol": "SHSE.000001",
            "price": 3560.12,
            "pre_close": 3540,
            "open": 3544.2,
            "high": 3565.1,
            "low": 3538.4,
            "cum_volume": 1200,
            "cum_amount": 4300000,
            "cum_position": 0,
            "created_at": "2026-08-05T10:30:03+08:00",
            "quotes": [],
        }
        if self.omit_previous_close:
            valid.pop("pre_close")
        return [valid, {"symbol": "invalid"}]

    def history_n(self, **request: Any) -> list[dict[str, Any]]:
        self.history_requests.append(request)
        if request["frequency"] == "1d":
            return [
                {
                    "symbol": request["symbol"],
                    "bob": "2026-08-04T00:00:00+08:00",
                    "eob": "2026-08-04T23:59:59+08:00",
                    "open": 3520,
                    "high": 3550,
                    "low": 3510,
                    "close": 3540,
                    "volume": 100,
                    "amount": 354000,
                }
            ]
        return []

    def search_symbols(self, query: str) -> list[dict[str, Any]]:
        self.search_queries.append(query)
        return [{"symbol": "SHSE.600000", "sec_name": "浦发银行"}]

    def trading_dates(self, **_: str) -> list[str]:
        return ["2026-08-05"]


def provider() -> tuple[EastmoneyProvider, FakeBridgeClient]:
    client = FakeBridgeClient()
    clock = FixedClock(datetime(2026, 8, 5, 2, 30, 4, tzinfo=UTC))
    return EastmoneyProvider(client=client, clock=clock), client


def test_connect_configures_bridge_once() -> None:
    market, client = provider()
    market.connect("valid-token")
    market.connect("valid-token")
    assert client.started == 1
    assert client.configured == ["valid-token"]


def test_poll_batches_quotes_and_counts_invalid_rows() -> None:
    market, client = provider()
    market.connect("valid-token")
    quote = market.poll((InstrumentId.parse("000001.SSE"),))[0]
    assert str(quote.instrument_id) == "000001.SSE"
    assert client.current_symbols == [["SHSE.000001"]]
    assert market.health().parse_error_count == 1
    assert market.health().state is ConnectionState.LIVE


def test_poll_enriches_and_caches_missing_previous_close_from_daily_history() -> None:
    market, client = provider()
    client.omit_previous_close = True
    market.connect("valid-token")

    first = market.poll((InstrumentId.parse("000001.SSE"),))[0]
    second = market.poll((InstrumentId.parse("000001.SSE"),))[0]

    assert first.previous_close == 3540
    assert first.change_percent == Decimal("0.5684")
    assert second.previous_close == 3540
    assert [request for request in client.history_requests if request["frequency"] == "1d"] == [
        {"symbol": "SHSE.000001", "frequency": "1d", "count": 1}
    ]


def test_poll_rejects_more_than_fifty_instruments() -> None:
    market, _ = provider()
    instruments = tuple(InstrumentId.parse(f"{600000 + index}.SSE") for index in range(51))
    with pytest.raises(ValueError, match="50"):
        market.poll(instruments)


def test_history_requests_sixty_second_bars_with_a_bounded_count() -> None:
    market, client = provider()
    market.history_n(InstrumentId.parse("000001.SSE"), count=40000)
    assert client.history_requests == [
        {"symbol": "SHSE.000001", "frequency": "60s", "count": 33000}
    ]


@pytest.mark.parametrize(
    ("period", "frequency"),
    [
        (MarketPeriod.INTRADAY, "60s"),
        (MarketPeriod.MINUTE_1, "60s"),
        (MarketPeriod.MINUTE_5, "300s"),
        (MarketPeriod.MINUTE_15, "900s"),
        (MarketPeriod.MINUTE_30, "1800s"),
        (MarketPeriod.MINUTE_60, "3600s"),
        (MarketPeriod.DAY, "1d"),
    ],
)
def test_bars_maps_direct_periods_to_eastmoney(
    period: MarketPeriod,
    frequency: str,
) -> None:
    market, client = provider()

    market.bars(InstrumentId.parse("000001.SSE"), period=period, count=20)

    assert client.history_requests[-1] == {
        "symbol": "SHSE.000001",
        "frequency": frequency,
        "count": 20,
        "adjust": 1,
    }


@pytest.mark.parametrize(
    ("period", "daily_count"),
    [
        (MarketPeriod.WEEK, 35),
        (MarketPeriod.MONTH, 115),
        (MarketPeriod.YEAR, 1250),
    ],
)
def test_bars_aggregates_higher_periods_from_daily_data(
    period: MarketPeriod,
    daily_count: int,
) -> None:
    market, client = provider()

    result = market.bars(InstrumentId.parse("000001.SSE"), period=period, count=5)

    assert result[-1].close == 3540
    assert client.history_requests[-1] == {
        "symbol": "SHSE.000001",
        "frequency": "1d",
        "count": daily_count,
        "adjust": 1,
    }


def test_search_delegates_a_trimmed_query_to_the_catalog_bridge() -> None:
    market, client = provider()

    result = market.search("  浦发  ")

    assert result[0]["symbol"] == "SHSE.600000"
    assert client.search_queries == ["浦发"]


def test_child_failure_moves_health_to_error_without_private_message() -> None:
    market, client = provider()
    market.connect("valid-token")
    client.fail_current = True
    with pytest.raises(RuntimeError):
        market.poll((InstrumentId.parse("000001.SSE"),))
    assert market.health().state is ConnectionState.ERROR
    assert market.health().error_code == "provider_call_failed"


def test_provider_surface_has_no_trading_or_account_operations() -> None:
    methods = {name for name, value in inspect.getmembers(EastmoneyProvider, inspect.isfunction)}
    assert methods.isdisjoint(
        {"order", "submit_order", "cancel_order", "account", "position", "balance"}
    )


def test_trading_dates_are_parsed() -> None:
    market, _ = provider()
    assert market.trading_dates(date(2026, 8, 5), date(2026, 8, 5)) == [date(2026, 8, 5)]

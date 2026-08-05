import inspect
from datetime import UTC, date, datetime
from typing import Any

import pytest

from astraquant_data.adapters.eastmoney import EastmoneyProvider
from astraquant_data.live_providers import ConnectionState
from astraquant_domain import FixedClock, InstrumentId


class FakeBridgeClient:
    def __init__(self) -> None:
        self.started = 0
        self.configured: list[str] = []
        self.current_symbols: list[list[str]] = []
        self.history_requests: list[dict[str, Any]] = []
        self.fail_current = False

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
        return [
            {
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
            },
            {"symbol": "invalid"},
        ]

    def history_n(self, **request: Any) -> list[dict[str, Any]]:
        self.history_requests.append(request)
        return []

    def symbol_infos(self, symbols: list[str]) -> list[dict[str, Any]]:
        return [{"symbol": symbol, "sec_name": symbol} for symbol in symbols]

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

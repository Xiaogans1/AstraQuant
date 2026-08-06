"""Read-only polling provider backed by the isolated Eastmoney bridge."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from astraquant_data.eastmoney_protocol import map_current_quote, to_eastmoney_symbol
from astraquant_data.live_providers import ConnectionState, ProviderHealth
from astraquant_domain import Clock, InstrumentId, LiveQuote


class EastmoneyClient(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def configure(self, token: str) -> None: ...

    def current(self, symbols: list[str]) -> list[dict[str, Any]]: ...

    def history_n(
        self,
        *,
        symbol: str,
        frequency: str,
        count: int,
    ) -> list[dict[str, Any]]: ...

    def search_symbols(self, query: str) -> list[dict[str, Any]]: ...

    def trading_dates(
        self,
        *,
        exchange: str,
        start_date: str,
        end_date: str,
    ) -> list[Any]: ...


class EastmoneyProvider:
    provider_id = "eastmoney"

    def __init__(self, *, client: EastmoneyClient, clock: Clock) -> None:
        self._client = client
        self._clock = clock
        self._connected = False
        self._health = ProviderHealth(provider_id=self.provider_id)
        self._reference_closes: dict[tuple[str, date], Decimal] = {}
        self._reference_trading_date: date | None = None

    def connect(self, token: str) -> None:
        if self._connected:
            return
        self._health = replace(self._health, state=ConnectionState.CONNECTING, error_code=None)
        try:
            self._client.start()
            self._client.configure(token)
        except Exception as error:
            self._health = replace(
                self._health,
                state=ConnectionState.ERROR,
                error_code="provider_connect_failed",
            )
            raise RuntimeError("Eastmoney provider connection failed") from error
        self._connected = True
        self._health = replace(
            self._health,
            state=ConnectionState.CONNECTING,
            connected_at=self._clock.now(),
        )

    def disconnect(self) -> None:
        if self._connected:
            self._client.stop()
        self._connected = False
        self._health = replace(self._health, state=ConnectionState.DISCONNECTED)

    def poll(self, instruments: Sequence[InstrumentId]) -> list[LiveQuote]:
        if len(instruments) > 50:
            raise ValueError("Eastmoney poll accepts at most 50 instruments")
        symbols = [to_eastmoney_symbol(item) for item in instruments]
        try:
            rows = self._client.current(symbols)
        except Exception as error:
            self._health = replace(
                self._health,
                state=ConnectionState.ERROR,
                error_code="provider_call_failed",
            )
            raise RuntimeError("Eastmoney provider call failed") from error
        quotes: list[LiveQuote] = []
        parse_errors = 0
        received_at = self._clock.now()
        for row in rows:
            try:
                quote = map_current_quote(row, received_at=received_at)
                quotes.append(self._with_previous_close(quote))
            except (ArithmeticError, TypeError, ValueError):
                parse_errors += 1
        last_event = max((quote.event_time for quote in quotes), default=None)
        self._health = replace(
            self._health,
            state=ConnectionState.LIVE if quotes else self._health.state,
            last_event_at=last_event or self._health.last_event_at,
            instrument_count=len(instruments),
            parse_error_count=self._health.parse_error_count + parse_errors,
            error_code=None,
        )
        return quotes

    def health(self) -> ProviderHealth:
        return self._health

    def history_n(self, instrument_id: InstrumentId, *, count: int) -> list[dict[str, Any]]:
        bounded_count = max(1, min(count, 33_000))
        return self._client.history_n(
            symbol=to_eastmoney_symbol(instrument_id),
            frequency="60s",
            count=bounded_count,
        )

    def search(self, query: str) -> list[dict[str, Any]]:
        return self._client.search_symbols(query.strip())

    def trading_dates(self, start: date, end: date) -> list[date]:
        values = self._client.trading_dates(
            exchange="SHSE",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        return [
            value if isinstance(value, date) else date.fromisoformat(str(value)) for value in values
        ]

    def _with_previous_close(self, quote: LiveQuote) -> LiveQuote:
        if quote.previous_close is not None:
            return quote
        if self._reference_trading_date != quote.trading_date:
            self._reference_closes.clear()
            self._reference_trading_date = quote.trading_date
        key = (str(quote.instrument_id), quote.trading_date)
        previous_close = self._reference_closes.get(key)
        if previous_close is None:
            try:
                rows = self._client.history_n(
                    symbol=to_eastmoney_symbol(quote.instrument_id),
                    frequency="1d",
                    count=1,
                )
                value = Decimal(str(rows[-1].get("close"))) if rows else Decimal("0")
            except (ArithmeticError, IndexError, KeyError, TypeError, ValueError):
                return quote
            if value <= 0:
                return quote
            previous_close = value
            self._reference_closes[key] = previous_close
        return replace(quote, previous_close=previous_close)

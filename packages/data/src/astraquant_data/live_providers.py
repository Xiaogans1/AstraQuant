"""Read-only health and capability contracts for live market providers."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Protocol

from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_domain import InstrumentId, LiveQuote


class ConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    LIVE = "LIVE"
    STALE = "STALE"
    CLOSED = "CLOSED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider_id: str
    state: ConnectionState = ConnectionState.DISCONNECTED
    connected_at: datetime | None = None
    last_event_at: datetime | None = None
    error_code: str | None = None
    instrument_count: int = 0
    parse_error_count: int = 0
    reconnect_count: int = 0


class LiveMarketProvider(Protocol):
    provider_id: str
    requires_token: bool

    def connect(self, token: str) -> None: ...

    def disconnect(self) -> None: ...

    def poll(self, instruments: Sequence[InstrumentId]) -> list[LiveQuote]: ...

    def health(self) -> ProviderHealth: ...

    def history_n(self, instrument_id: InstrumentId, *, count: int) -> list[dict[str, Any]]: ...

    def bars(
        self,
        instrument_id: InstrumentId,
        *,
        period: MarketPeriod,
        count: int,
    ) -> list[MarketBar]: ...

    def search(self, query: str) -> list[dict[str, Any]]: ...

    def trading_dates(self, start: date, end: date) -> list[date]: ...

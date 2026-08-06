"""Lifecycle and bounded cache for the local realtime market workspace."""

from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from astraquant_api.market_config import SettingsStore
from astraquant_api.market_watchlist import WatchlistEntry, load_watchlist, save_watchlist
from astraquant_api.secret_store import SecretStore
from astraquant_data.eastmoney_protocol import from_eastmoney_symbol
from astraquant_data.live_providers import ConnectionState, LiveMarketProvider, ProviderHealth
from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_data.subscriptions import CORE_INDICES, SubscriptionBudget
from astraquant_domain import Clock, InstrumentId, LiveQuote, SystemClock

_CHINA_ZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class MarketItemSnapshot:
    instrument_id: str
    name: str | None
    kind: str | None
    quote: LiveQuote | None


@dataclass(frozen=True, slots=True)
class MarketHomeSnapshot:
    connection: ProviderHealth
    core_indices: tuple[MarketItemSnapshot, ...]
    watchlist: tuple[MarketItemSnapshot, ...]
    selected_instrument: MarketItemSnapshot | None
    as_of: datetime | None


class MarketDataService:
    def __init__(
        self,
        *,
        provider: LiveMarketProvider | None,
        budget: SubscriptionBudget,
        secret_store: SecretStore,
        watchlist_store: SettingsStore | None = None,
        clock: Clock | None = None,
        poll_interval_seconds: float = 3,
        stale_after_seconds: float = 10,
    ) -> None:
        self._provider = provider
        self._budget = budget
        self._secret_store = secret_store
        self._watchlist_store = watchlist_store
        self._clock = clock or SystemClock()
        self._poll_interval_seconds = poll_interval_seconds
        self._stale_after_seconds = stale_after_seconds
        self._task: asyncio.Task[None] | None = None
        self._quotes: dict[str, LiveQuote] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._bar_history: OrderedDict[tuple[str, MarketPeriod], list[MarketBar]] = OrderedDict()
        self._instrument_names: dict[str, str] = {}
        self._selected: str | None = None
        self._connection = ProviderHealth(provider_id="eastmoney")
        self._restore_watchlist()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if self._provider is None:
            self._connection = replace(
                self._connection,
                state=ConnectionState.UNAVAILABLE,
                error_code="missing_sdk",
            )
            return
        token = self._secret_store.get_eastmoney_token()
        if token is None:
            self._connection = replace(
                self._connection,
                state=ConnectionState.UNAVAILABLE,
                error_code="missing_token",
            )
            return
        self._connection = replace(
            self._connection,
            state=ConnectionState.CONNECTING,
            error_code=None,
        )
        try:
            await asyncio.to_thread(self._provider.connect, token)
        except Exception:
            self._connection = replace(
                self._connection,
                state=ConnectionState.ERROR,
                error_code="provider_connect_failed",
                reconnect_count=self._connection.reconnect_count + 1,
            )
            return
        self._connection = replace(
            self._connection,
            state=ConnectionState.CONNECTING,
            connected_at=self._clock.now(),
        )
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._task = None
        if self._provider is not None:
            await asyncio.to_thread(self._provider.disconnect)
        self._connection = replace(self._connection, state=ConnectionState.DISCONNECTED)

    def connection(self) -> ProviderHealth:
        return self._connection

    def configure_provider(self, provider: LiveMarketProvider) -> None:
        if self._task is not None and not self._task.done():
            raise RuntimeError("market service must be stopped before reconfiguration")
        self._provider = provider
        self._connection = ProviderHealth(provider_id="eastmoney")

    def add_watchlist(self, instrument_id: str) -> None:
        before = self._budget.persistent_instruments
        self._budget.add_persistent(instrument_id)
        if self._selected is None:
            self._selected = str(InstrumentId.parse(instrument_id))
        if self._budget.persistent_instruments != before:
            self._persist_watchlist()

    def remove_watchlist(self, instrument_id: str) -> None:
        canonical = str(InstrumentId.parse(instrument_id))
        before = self._budget.persistent_instruments
        self._budget.remove(canonical)
        self._quotes.pop(canonical, None)
        self._history.pop(canonical, None)
        for key in tuple(self._bar_history):
            if key[0] == canonical:
                self._bar_history.pop(key)
        if self._selected == canonical:
            self._selected = None
        if self._budget.persistent_instruments != before:
            self._persist_watchlist()

    def home_snapshot(self) -> MarketHomeSnapshot:
        core = tuple(
            MarketItemSnapshot(
                instrument_id=definition.instrument_id,
                name=definition.name,
                kind=definition.kind,
                quote=self._quotes.get(definition.instrument_id),
            )
            for definition in CORE_INDICES
        )
        watchlist = tuple(
            MarketItemSnapshot(
                instrument_id=instrument_id,
                name=self._instrument_names.get(instrument_id),
                kind=None,
                quote=self._quotes.get(instrument_id),
            )
            for instrument_id in self._budget.persistent_instruments
        )
        selected = next(
            (item for item in (*core, *watchlist) if item.instrument_id == self._selected),
            None,
        )
        as_of = max((quote.event_time for quote in self._quotes.values()), default=None)
        return MarketHomeSnapshot(self._connection, core, watchlist, selected, as_of)

    def record_quotes(self, quotes: list[LiveQuote]) -> None:
        active = frozenset(self._budget.active_instruments())
        for quote in quotes:
            key = str(quote.instrument_id)
            if key in active:
                self._quotes[key] = quote
        if quotes:
            last_event = max(quote.event_time for quote in quotes)
            self._connection = replace(
                self._connection,
                state=ConnectionState.LIVE,
                last_event_at=last_event,
                instrument_count=len(active),
                error_code=None,
            )

    def refresh_connection_state(self, *, is_trading_date: bool, is_session_open: bool) -> None:
        if not is_trading_date or not is_session_open:
            self._connection = replace(self._connection, state=ConnectionState.CLOSED)
            return
        last_event = self._connection.last_event_at
        if last_event is None:
            self._connection = replace(self._connection, state=ConnectionState.CONNECTING)
            return
        age = (self._clock.now() - last_event).total_seconds()
        state = ConnectionState.STALE if age > self._stale_after_seconds else ConnectionState.LIVE
        self._connection = replace(self._connection, state=state)

    async def wait_for_quotes(self, count: int, *, timeout_seconds: float) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while len(self._quotes) < count:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"Timed out waiting for {count} quotes")
            await asyncio.sleep(min(self._poll_interval_seconds, 0.01))

    async def intraday(self, instrument_id: str, *, count: int = 240) -> list[dict[str, Any]]:
        canonical = str(InstrumentId.parse(instrument_id))
        bounded_count = max(1, min(count, 240))
        if self._provider is None:
            return []
        rows = await asyncio.to_thread(
            self._provider.history_n,
            InstrumentId.parse(canonical),
            count=bounded_count,
        )
        self._history[canonical] = _latest_intraday_session(list(rows[-240:]))
        return self._history[canonical]

    async def bars(
        self,
        instrument_id: str,
        *,
        period: MarketPeriod,
        count: int = 300,
    ) -> list[MarketBar]:
        canonical = str(InstrumentId.parse(instrument_id))
        bounded_count = max(1, min(count, 5_000))
        if self._provider is None:
            return []
        rows = await asyncio.to_thread(
            self._provider.bars,
            InstrumentId.parse(canonical),
            period=period,
            count=bounded_count,
        )
        normalized_rows = (
            _latest_market_bar_session(list(rows))
            if period is MarketPeriod.INTRADAY
            else list(rows)
        )
        key = (canonical, period)
        self._bar_history[key] = normalized_rows[-bounded_count:]
        self._bar_history.move_to_end(key)
        while len(self._bar_history) > 5:
            self._bar_history.popitem(last=False)
        return self._bar_history[key]

    async def search(self, query: str) -> list[dict[str, Any]]:
        if self._provider is None:
            return []
        rows = await asyncio.to_thread(self._provider.search, query)
        for row in rows:
            try:
                instrument_id = str(from_eastmoney_symbol(str(row.get("symbol", ""))))
            except ValueError:
                continue
            name = str(row.get("sec_name", "")).strip()
            if name:
                self._instrument_names[instrument_id] = name
        return rows

    @staticmethod
    def reconnect_delay_seconds(attempt: int) -> int:
        return int(min(2 ** min(max(attempt - 1, 0), 5), 30))

    def _restore_watchlist(self) -> None:
        if self._watchlist_store is None:
            return
        for entry in load_watchlist(self._watchlist_store):
            self._budget.add_persistent(entry.instrument_id)
            if entry.name is not None:
                self._instrument_names[entry.instrument_id] = entry.name
        if self._budget.persistent_instruments:
            self._selected = self._budget.persistent_instruments[0]

    def _persist_watchlist(self) -> None:
        if self._watchlist_store is None:
            return
        entries = tuple(
            WatchlistEntry(instrument_id, self._instrument_names.get(instrument_id))
            for instrument_id in self._budget.persistent_instruments
        )
        save_watchlist(self._watchlist_store, entries)

    async def _poll_loop(self) -> None:
        reconnect_count = 0
        while True:
            try:
                assert self._provider is not None
                active = tuple(
                    InstrumentId.parse(item) for item in self._budget.active_instruments()
                )
                quotes = await asyncio.to_thread(self._provider.poll, active)
                self.record_quotes(quotes)
                local_now = self._clock.now().astimezone(_CHINA_ZONE)
                trading_dates = await asyncio.to_thread(
                    self._provider.trading_dates,
                    local_now.date(),
                    local_now.date(),
                )
                self.refresh_connection_state(
                    is_trading_date=local_now.date() in trading_dates,
                    is_session_open=self._is_session_open(local_now.time()),
                )
                reconnect_count = 0
                await asyncio.sleep(self._poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                reconnect_count += 1
                self._connection = replace(
                    self._connection,
                    state=ConnectionState.ERROR,
                    error_code="provider_call_failed",
                    reconnect_count=reconnect_count,
                )
                assert self._provider is not None
                await asyncio.to_thread(self._provider.disconnect)
                await asyncio.sleep(self.reconnect_delay_seconds(reconnect_count))
                token = self._secret_store.get_eastmoney_token()
                if token is None:
                    self._connection = replace(
                        self._connection,
                        state=ConnectionState.UNAVAILABLE,
                        error_code="missing_token",
                    )
                    return
                await asyncio.to_thread(self._provider.connect, token)
                self._connection = replace(
                    self._connection,
                    state=ConnectionState.CONNECTING,
                    connected_at=self._clock.now(),
                    error_code=None,
                )

    @staticmethod
    def _is_session_open(local_time: time) -> bool:
        return time(9, 15) <= local_time <= time(11, 30) or time(13) <= local_time <= time(15, 5)


def _latest_intraday_session(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated_rows: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        raw_time = row.get("bob") or row.get("eob")
        try:
            event_time = (
                raw_time
                if isinstance(raw_time, datetime)
                else datetime.fromisoformat(str(raw_time))
            )
        except (TypeError, ValueError):
            continue
        dated_rows.append((event_time, row))
    if not dated_rows:
        return rows
    latest_date = max(event_time.date() for event_time, _ in dated_rows)
    return [row for event_time, row in dated_rows if event_time.date() == latest_date]


def _latest_market_bar_session(rows: list[MarketBar]) -> list[MarketBar]:
    if not rows:
        return []
    latest_date = max(item.timestamp.date() for item in rows)
    return [item for item in rows if item.timestamp.date() == latest_date]

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from astraquant_api.market_service import MarketDataService
from astraquant_api.secret_store import MemorySecretStore
from astraquant_data.live_providers import ConnectionState, ProviderHealth
from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_data.subscriptions import CORE_INDICES, SubscriptionBudget
from astraquant_domain import InstrumentId, LiveQuote, MarketEventQuality


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class MemorySettings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key: str) -> object | None:
        return self.values.get(key)

    def set_setting(self, key: str, value: object) -> None:
        self.values[key] = value


class FakeProvider:
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.connect_count = 0
        self.disconnect_count = 0
        self.polls: list[tuple[str, ...]] = []
        self.return_quotes = True
        self.fail_polls = 0
        self.fail_connects = 0
        self.history_rows: list[dict[str, Any]] | None = None
        self.bar_rows: list[MarketBar] | None = None
        self.bar_requests: list[tuple[str, MarketPeriod, int]] = []
        self._health = ProviderHealth(provider_id="eastmoney")

    def connect(self, token: str) -> None:
        assert token == "token-value"
        self.connect_count += 1
        if self.fail_connects:
            self.fail_connects -= 1
            raise RuntimeError("terminal unavailable")

    def disconnect(self) -> None:
        self.disconnect_count += 1

    def poll(self, instruments: Sequence[InstrumentId]) -> list[LiveQuote]:
        self.polls.append(tuple(str(item) for item in instruments))
        if self.fail_polls:
            self.fail_polls -= 1
            raise RuntimeError("temporary child failure")
        if not self.return_quotes:
            return []
        return [
            LiveQuote.minimum(
                instrument,
                event_time=self.clock.now(),
                received_time=self.clock.now(),
                last_price=Decimal("10"),
                previous_close=Decimal("9"),
                quality=frozenset({MarketEventQuality.NORMAL}),
            )
            for instrument in instruments
        ]

    def health(self) -> ProviderHealth:
        return self._health

    def history_n(self, instrument_id: InstrumentId, *, count: int) -> list[dict[str, Any]]:
        if self.history_rows is not None:
            return self.history_rows
        return [{"instrument_id": str(instrument_id), "index": index} for index in range(count)]

    def bars(
        self,
        instrument_id: InstrumentId,
        *,
        period: MarketPeriod,
        count: int,
    ) -> list[MarketBar]:
        self.bar_requests.append((str(instrument_id), period, count))
        if self.bar_rows is not None:
            return self.bar_rows
        return [
            MarketBar(
                timestamp=datetime(2026, 8, 5, 9, 30, tzinfo=UTC) + timedelta(minutes=index),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10.5"),
                volume=Decimal(index + 1),
                turnover=Decimal((index + 1) * 10),
                previous_close=Decimal("9.5"),
            )
            for index in range(count)
        ]

    def search(self, query: str) -> list[dict[str, Any]]:
        return [{"symbol": "SHSE.600000", "sec_name": "浦发银行"}]

    def trading_dates(self, start: date, end: date) -> list[date]:
        return [start] if start == end else []


def build_service(
    *,
    token: str | None = "token-value",
    provider_available: bool = True,
    watchlist_store: MemorySettings | None = None,
) -> tuple[MarketDataService, FakeProvider, MutableClock]:
    clock = MutableClock(datetime(2026, 8, 5, 2, 30, tzinfo=UTC))
    provider = FakeProvider(clock)
    service = MarketDataService(
        provider=provider if provider_available else None,
        budget=SubscriptionBudget(),
        secret_store=MemorySecretStore(token),
        watchlist_store=watchlist_store,
        clock=clock,
        poll_interval_seconds=0.01,
        stale_after_seconds=0.05,
    )
    return service, provider, clock


def test_service_builds_six_core_index_snapshots() -> None:
    async def scenario() -> None:
        service, provider, _ = build_service()
        await service.start()
        await service.wait_for_quotes(6, timeout_seconds=1)
        home = service.home_snapshot()
        assert [item.instrument_id for item in home.core_indices] == [
            item.instrument_id for item in CORE_INDICES
        ]
        assert all(item.quote is not None for item in home.core_indices)
        await service.stop()
        assert provider.disconnect_count == 1

    asyncio.run(scenario())


def test_start_and_stop_are_idempotent() -> None:
    async def scenario() -> None:
        service, provider, _ = build_service()
        await service.start()
        await service.start()
        await service.stop()
        await service.stop()
        assert provider.connect_count == 1
        assert provider.disconnect_count == 1

    asyncio.run(scenario())


def test_missing_token_or_sdk_is_explicitly_unavailable() -> None:
    async def scenario() -> None:
        missing_token, _, _ = build_service(token=None)
        await missing_token.start()
        assert missing_token.connection().state is ConnectionState.UNAVAILABLE
        assert missing_token.connection().error_code == "missing_token"

        missing_sdk, _, _ = build_service(provider_available=False)
        await missing_sdk.start()
        assert missing_sdk.connection().state is ConnectionState.UNAVAILABLE
        assert missing_sdk.connection().error_code == "missing_sdk"

    asyncio.run(scenario())


def test_failed_automatic_connection_does_not_block_a_later_retry() -> None:
    async def scenario() -> None:
        service, provider, _ = build_service()
        provider.fail_connects = 1

        await service.start()

        assert service.connection().state is ConnectionState.ERROR
        assert service.connection().error_code == "provider_connect_failed"

        await service.start()
        await service.wait_for_quotes(6, timeout_seconds=1)
        assert service.connection().state is ConnectionState.LIVE
        await service.stop()

    asyncio.run(scenario())


def test_watchlist_changes_apply_to_the_next_poll() -> None:
    async def scenario() -> None:
        service, provider, _ = build_service()
        await service.start()
        await service.wait_for_quotes(6, timeout_seconds=1)
        service.add_watchlist("600000.SSE")
        await service.wait_for_quotes(7, timeout_seconds=1)
        assert "600000.SSE" in provider.polls[-1]
        assert service.home_snapshot().watchlist[0].instrument_id == "600000.SSE"
        await service.stop()

    asyncio.run(scenario())


def test_search_result_name_is_reused_in_watchlist() -> None:
    async def scenario() -> None:
        service, _, _ = build_service()
        await service.search("浦发")
        service.add_watchlist("600000.SSE")

        assert service.home_snapshot().watchlist[0].name == "浦发银行"

    asyncio.run(scenario())


def test_watchlist_survives_service_restart_and_deletion() -> None:
    async def scenario() -> None:
        settings = MemorySettings()
        first, _, _ = build_service(watchlist_store=settings)
        await first.search("浦发")
        first.add_watchlist("600000.SSE")

        restarted, _, _ = build_service(watchlist_store=settings)
        restored = restarted.home_snapshot().watchlist
        assert [(item.instrument_id, item.name) for item in restored] == [
            ("600000.SSE", "浦发银行")
        ]

        restarted.remove_watchlist("600000.SSE")
        after_deletion, _, _ = build_service(watchlist_store=settings)
        assert after_deletion.home_snapshot().watchlist == ()

    asyncio.run(scenario())


def test_stale_and_closed_states_never_claim_realtime() -> None:
    service, _, clock = build_service()
    service.record_quotes(
        [
            LiveQuote.minimum(
                InstrumentId.parse("000001.SSE"),
                event_time=clock.now(),
                last_price=Decimal("10"),
                previous_close=Decimal("9"),
            )
        ]
    )
    clock.value += timedelta(seconds=1)
    service.refresh_connection_state(is_trading_date=True, is_session_open=True)
    assert service.connection().state is ConnectionState.STALE
    service.refresh_connection_state(is_trading_date=True, is_session_open=False)
    assert service.connection().state is ConnectionState.CLOSED


def test_history_cache_is_bounded_and_backoff_caps_at_thirty_seconds() -> None:
    async def scenario() -> None:
        service, _, _ = build_service()
        bars = await service.intraday("000001.SSE", count=1000)
        assert len(bars) == 240
        assert service.reconnect_delay_seconds(99) == 30

    asyncio.run(scenario())


def test_intraday_keeps_only_the_latest_trading_day() -> None:
    async def scenario() -> None:
        service, provider, _ = build_service()
        provider.history_rows = [
            {"bob": "2026-08-04T14:59:00+08:00", "close": 9.30},
            {"bob": "2026-08-05T09:30:00+08:00", "close": 9.35},
            {"bob": "2026-08-05T15:00:00+08:00", "close": 9.26},
        ]

        bars = await service.intraday("600000.SSE")

        assert [row["bob"] for row in bars] == [
            "2026-08-05T09:30:00+08:00",
            "2026-08-05T15:00:00+08:00",
        ]

    asyncio.run(scenario())


def test_period_bars_are_bounded_and_forward_the_requested_period() -> None:
    async def scenario() -> None:
        service, provider, _ = build_service()

        bars = await service.bars("600000.SSE", period=MarketPeriod.MINUTE_5, count=6000)

        assert len(bars) == 5000
        assert provider.bar_requests == [("600000.SSE", MarketPeriod.MINUTE_5, 5000)]

    asyncio.run(scenario())


def test_period_intraday_bars_keep_only_the_latest_trading_day() -> None:
    async def scenario() -> None:
        service, provider, _ = build_service()
        provider.bar_rows = [
            MarketBar(
                timestamp=datetime(2026, 8, 4, 14, 59, tzinfo=UTC),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10"),
                volume=Decimal("1"),
                turnover=Decimal("10"),
            ),
            MarketBar(
                timestamp=datetime(2026, 8, 5, 9, 30, tzinfo=UTC),
                open=Decimal("11"),
                high=Decimal("11"),
                low=Decimal("11"),
                close=Decimal("11"),
                volume=Decimal("2"),
                turnover=Decimal("22"),
            ),
        ]

        bars = await service.bars(
            "600000.SSE",
            period=MarketPeriod.INTRADAY,
            count=240,
        )

        assert [item.timestamp.date() for item in bars] == [date(2026, 8, 5)]

    asyncio.run(scenario())


def test_poll_failure_reconnects_before_resuming_quotes() -> None:
    async def scenario() -> None:
        service, provider, _ = build_service()
        provider.fail_polls = 1
        await service.start()
        await service.wait_for_quotes(6, timeout_seconds=2)
        assert provider.connect_count == 2
        assert provider.disconnect_count >= 1
        assert service.connection().state is ConnectionState.LIVE
        await service.stop()

    asyncio.run(scenario())

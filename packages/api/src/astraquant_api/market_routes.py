"""Authenticated loopback routes for realtime market observation."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Query

from astraquant_api.app import ApiProblem
from astraquant_api.market_config import (
    EastmoneyRuntimeConfig,
    load_eastmoney_runtime_config,
    save_eastmoney_runtime_config,
)
from astraquant_api.market_schemas import (
    EastmoneyConfigRequest,
    EastmoneyConfigStatus,
    InstrumentSearchResponse,
    MarketBarResponse,
    MarketConnectionResponse,
    MarketHomeResponse,
    QuoteCardResponse,
    UnavailableFeatureResponse,
    WatchlistRequest,
)
from astraquant_api.market_service import MarketDataService, MarketItemSnapshot
from astraquant_api.repository import TaskRepository
from astraquant_api.secret_store import SecretStore
from astraquant_data.eastmoney_protocol import from_eastmoney_symbol
from astraquant_data.live_providers import LiveMarketProvider
from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_data.subscriptions import SubscriptionLimitReached
from astraquant_domain import InstrumentId, Venue

ProviderFactory = Callable[[Path, float], LiveMarketProvider]
_FUTURE_VENUES = {
    Venue.CFFEX,
    Venue.SHFE,
    Venue.DCE,
    Venue.CZCE,
    Venue.INE,
    Venue.GFEX,
}


def validate_sdk_python(path: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(path), "-I", "-c", "import gm"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def build_market_router(
    *,
    repository: TaskRepository,
    service: MarketDataService,
    secret_store: SecretStore,
    provider_factory: ProviderFactory,
    authenticated: Any,
) -> APIRouter:
    router = APIRouter(prefix="/v1/market", dependencies=[authenticated])

    def connection_response() -> MarketConnectionResponse:
        health = service.connection()
        config = load_eastmoney_runtime_config(repository)
        return MarketConnectionResponse(
            sdk_configured=config.sdk_python is not None,
            token_configured=secret_store.get_eastmoney_token() is not None,
            state=health.state.value,
            connected_at=health.connected_at,
            last_event_at=health.last_event_at,
            error_code=health.error_code,
            instrument_count=health.instrument_count,
            parse_error_count=health.parse_error_count,
            reconnect_count=health.reconnect_count,
        )

    def home_response() -> MarketHomeResponse:
        snapshot = service.home_snapshot()
        cards = {
            item.instrument_id: _quote_card(item, snapshot.connection.state.value)
            for item in (*snapshot.core_indices, *snapshot.watchlist)
        }
        return MarketHomeResponse(
            connection=connection_response(),
            core_indices=[cards[item.instrument_id] for item in snapshot.core_indices],
            watchlist=[cards[item.instrument_id] for item in snapshot.watchlist],
            selected_instrument=(
                None
                if snapshot.selected_instrument is None
                else cards[snapshot.selected_instrument.instrument_id]
            ),
            breadth=UnavailableFeatureResponse(reason="当前东财免费行情不提供全市场宽度"),
            intelligence=UnavailableFeatureResponse(reason="AI 情报尚未接入真实证据链"),
            candidates=[],
            as_of=snapshot.as_of,
        )

    @router.get("/connection", response_model=MarketConnectionResponse)
    def get_connection() -> MarketConnectionResponse:
        return connection_response()

    @router.put("/eastmoney/config", response_model=EastmoneyConfigStatus)
    async def configure(request: EastmoneyConfigRequest) -> EastmoneyConfigStatus:
        sdk_python = Path(request.sdk_python_path).expanduser().resolve()
        if not sdk_python.is_file() or not validate_sdk_python(sdk_python):
            raise ApiProblem(422, "invalid_eastmoney_sdk", "东财 SDK Python 不可用")
        await service.stop()
        config = EastmoneyRuntimeConfig(sdk_python=sdk_python)
        save_eastmoney_runtime_config(repository, config)
        secret_store.set_eastmoney_token(request.token.get_secret_value())
        service.configure_provider(provider_factory(sdk_python, config.request_timeout_seconds))
        return EastmoneyConfigStatus(sdk_configured=True, token_configured=True)

    @router.post("/connection/start", response_model=MarketConnectionResponse)
    async def start_connection() -> MarketConnectionResponse:
        await service.start()
        return connection_response()

    @router.post("/connection/stop", response_model=MarketConnectionResponse)
    async def stop_connection() -> MarketConnectionResponse:
        await service.stop()
        return connection_response()

    @router.get("/home", response_model=MarketHomeResponse)
    def market_home() -> MarketHomeResponse:
        return home_response()

    @router.get("/instruments/search", response_model=list[InstrumentSearchResponse])
    async def search_instruments(
        q: Annotated[str, Query(min_length=2, max_length=40)],
    ) -> list[InstrumentSearchResponse]:
        rows = await service.search(q)
        results: list[InstrumentSearchResponse] = []
        for row in rows:
            try:
                instrument_id = from_eastmoney_symbol(str(row.get("symbol", "")))
            except ValueError:
                continue
            results.append(
                InstrumentSearchResponse(
                    instrument_id=str(instrument_id),
                    name=str(row.get("sec_name") or instrument_id.symbol),
                    kind=_instrument_kind(instrument_id),
                )
            )
        return results

    @router.get("/instruments/{instrument_id}/intraday", response_model=list[dict[str, Any]])
    async def intraday(
        instrument_id: str,
        count: Annotated[int, Query(ge=1, le=240)] = 240,
    ) -> list[dict[str, Any]]:
        canonical = _observable_instrument(instrument_id)
        return await service.intraday(str(canonical), count=count)

    @router.get(
        "/instruments/{instrument_id}/bars",
        response_model=list[MarketBarResponse],
    )
    async def bars(
        instrument_id: str,
        period: MarketPeriod,
        count: Annotated[int, Query(ge=1, le=5_000)] = 300,
    ) -> list[MarketBarResponse]:
        canonical = _observable_instrument(instrument_id)
        rows = await service.bars(str(canonical), period=period, count=count)
        return [_bar_response(item) for item in rows]

    @router.post("/watchlist", response_model=MarketHomeResponse)
    def add_watchlist(request: WatchlistRequest) -> MarketHomeResponse:
        canonical = _observable_instrument(request.instrument_id)
        try:
            service.add_watchlist(str(canonical))
        except SubscriptionLimitReached:
            raise ApiProblem(409, "subscription_limit_reached", "自选行情名额已满") from None
        return home_response()

    @router.delete("/watchlist/{instrument_id}", response_model=MarketHomeResponse)
    def remove_watchlist(instrument_id: str) -> MarketHomeResponse:
        try:
            service.remove_watchlist(str(InstrumentId.parse(instrument_id)))
        except ValueError as error:
            raise ApiProblem(422, "invalid_instrument", "证券代码不可观测") from error
        return home_response()

    return router


def _observable_instrument(value: str) -> InstrumentId:
    try:
        instrument_id = InstrumentId.parse(value)
    except ValueError as error:
        raise ApiProblem(422, "invalid_instrument", "证券代码不可观测") from error
    if instrument_id.venue in _FUTURE_VENUES and instrument_id.symbol.endswith("0"):
        raise ApiProblem(422, "continuous_future_unsupported", "实时行情需要具体月份合约")
    return instrument_id


def _instrument_kind(instrument_id: InstrumentId) -> str:
    if instrument_id.venue in _FUTURE_VENUES:
        return "future"
    return "fund" if instrument_id.symbol.startswith(("5", "1")) else "equity"


def _quote_card(item: MarketItemSnapshot, state: str) -> QuoteCardResponse:
    quote = item.quote
    return QuoteCardResponse(
        instrument_id=item.instrument_id,
        name=item.name or item.instrument_id,
        kind=item.kind or _instrument_kind(InstrumentId.parse(item.instrument_id)),
        state=state,
        event_time=None if quote is None else quote.event_time,
        last_price=None if quote is None else str(quote.last_price),
        change=None if quote is None or quote.change is None else str(quote.change),
        change_percent=(
            None if quote is None or quote.change_percent is None else str(quote.change_percent)
        ),
        previous_close=(
            None if quote is None or quote.previous_close is None else str(quote.previous_close)
        ),
        open=None if quote is None else str(quote.open),
        high=None if quote is None else str(quote.high),
        low=None if quote is None else str(quote.low),
        volume=None if quote is None else str(quote.cumulative_volume),
        turnover=(
            None
            if quote is None or quote.cumulative_turnover is None
            else str(quote.cumulative_turnover)
        ),
        source_id=None if quote is None else quote.source_id,
    )


def _bar_response(item: MarketBar) -> MarketBarResponse:
    return MarketBarResponse(
        timestamp=item.timestamp,
        open=float(item.open),
        high=float(item.high),
        low=float(item.low),
        close=float(item.close),
        volume=float(item.volume),
        turnover=float(item.turnover),
        previous_close=None if item.previous_close is None else float(item.previous_close),
    )

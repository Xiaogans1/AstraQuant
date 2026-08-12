"""Delayed read-only A-share quotes for macOS through AKShare public endpoints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from astraquant_data.live_providers import ConnectionState, ProviderHealth
from astraquant_data.market_bars import MarketBar, MarketPeriod, aggregate_daily_bars
from astraquant_domain import Clock, InstrumentId, LiveQuote, MarketEventQuality, SystemClock, Venue

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SPOT_COLUMNS = frozenset(
    {"代码", "名称", "最新价", "今开", "最高", "最低", "昨收", "成交量", "成交额"}
)
_MINUTE_COLUMNS = frozenset({"时间", "开盘", "最高", "最低", "收盘", "成交量", "成交额"})
_DAILY_COLUMNS = frozenset({"日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"})
_INDEX_IDS = frozenset(
    {"000001.SSE", "399001.SZSE", "399006.SZSE", "000688.SSE", "000300.SSE", "399852.SZSE"}
)


class AkShareDelayedProvider:
    """Polling provider explicitly classified as delayed/exploratory, never formal realtime."""

    provider_id = "akshare"
    requires_token = False

    def __init__(self, *, client: Any | None = None, clock: Clock | None = None) -> None:
        if client is None:
            import akshare  # type: ignore[import-untyped]

            client = akshare
        self._client = client
        self._clock = clock or SystemClock()
        self._health = ProviderHealth(provider_id=self.provider_id)
        self._connected = False
        self._spot_rows: dict[str, Mapping[str, Any]] = {}

    def connect(self, token: str) -> None:
        del token
        self._connected = True
        self._health = replace(
            self._health,
            state=ConnectionState.CONNECTING,
            connected_at=self._clock.now(),
            error_code=None,
        )

    def disconnect(self) -> None:
        self._connected = False
        self._health = replace(self._health, state=ConnectionState.DISCONNECTED)

    def poll(self, instruments: Sequence[InstrumentId]) -> list[LiveQuote]:
        if not self._connected:
            raise RuntimeError("AKShare delayed provider is not connected")
        frame = self._client.stock_zh_a_spot_em()
        _require_columns(set(frame.columns), _SPOT_COLUMNS)
        rows = tuple(frame.to_dict(orient="records"))
        self._spot_rows = {str(_instrument(str(row["代码"]))): row for row in rows}
        requested_indices = {str(item) for item in instruments} & _INDEX_IDS
        if requested_indices:
            index_frame = self._client.stock_zh_index_spot_em(symbol="沪深重要指数")
            _require_columns(set(index_frame.columns), _SPOT_COLUMNS)
            for row in index_frame.to_dict(orient="records"):
                instrument_id = _index_instrument(str(row["代码"]))
                if str(instrument_id) in requested_indices:
                    self._spot_rows[str(instrument_id)] = row
        received = self._clock.now()
        quotes: list[LiveQuote] = []
        parse_errors = 0
        for instrument in instruments:
            if instrument.venue not in {Venue.SSE, Venue.SZSE, Venue.BSE}:
                continue
            row = self._spot_rows.get(str(instrument))
            if row is None:
                continue
            try:
                quotes.append(_spot_quote(instrument, row, received))
            except (ArithmeticError, TypeError, ValueError):
                parse_errors += 1
        self._health = replace(
            self._health,
            state=ConnectionState.LIVE if quotes else ConnectionState.CONNECTING,
            last_event_at=max((item.event_time for item in quotes), default=None),
            instrument_count=len(instruments),
            parse_error_count=self._health.parse_error_count + parse_errors,
            error_code=None,
        )
        return quotes

    def health(self) -> ProviderHealth:
        return self._health

    def history_n(self, instrument_id: InstrumentId, *, count: int) -> list[dict[str, Any]]:
        return [
            {
                "symbol": str(instrument_id),
                "eob": item.timestamp.isoformat(),
                "open": float(item.open),
                "high": float(item.high),
                "low": float(item.low),
                "close": float(item.close),
                "volume": float(item.volume),
                "amount": float(item.turnover),
            }
            for item in self.bars(instrument_id, period=MarketPeriod.MINUTE_1, count=count)
        ]

    def bars(
        self, instrument_id: InstrumentId, *, period: MarketPeriod, count: int
    ) -> list[MarketBar]:
        _require_equity(instrument_id)
        if period in {
            MarketPeriod.INTRADAY,
            MarketPeriod.MINUTE_1,
            MarketPeriod.MINUTE_5,
            MarketPeriod.MINUTE_15,
            MarketPeriod.MINUTE_30,
            MarketPeriod.MINUTE_60,
        }:
            minutes = "1" if period is MarketPeriod.INTRADAY else period.value.removesuffix("m")
            frame = self._client.stock_zh_a_hist_min_em(
                symbol=instrument_id.symbol,
                period=minutes,
                adjust="qfq",
            )
            _require_columns(set(frame.columns), _MINUTE_COLUMNS)
            return [_minute_bar(row) for row in frame.to_dict(orient="records")][-count:]
        frame = self._client.stock_zh_a_hist(
            symbol=instrument_id.symbol,
            period="daily",
            start_date="19700101",
            end_date=self._clock.now().astimezone(_SHANGHAI).strftime("%Y%m%d"),
            adjust="qfq",
            timeout=15,
        )
        _require_columns(set(frame.columns), _DAILY_COLUMNS)
        daily = [_daily_bar(row) for row in frame.to_dict(orient="records")]
        if period is MarketPeriod.DAY:
            return daily[-count:]
        if period in {MarketPeriod.WEEK, MarketPeriod.MONTH, MarketPeriod.YEAR}:
            return aggregate_daily_bars(daily, period)[-count:]
        raise ValueError(f"unsupported AKShare period: {period}")

    def search(self, query: str) -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        if not self._spot_rows:
            frame = self._client.stock_zh_a_spot_em()
            _require_columns(set(frame.columns), _SPOT_COLUMNS)
            self._spot_rows = {
                str(_instrument(str(row["代码"]))): row for row in frame.to_dict(orient="records")
            }
        results: list[dict[str, Any]] = []
        for instrument_id, row in self._spot_rows.items():
            symbol = str(row["代码"])
            name = str(row["名称"])
            if needle not in symbol.casefold() and needle not in name.casefold():
                continue
            results.append(
                {
                    "instrument_id": instrument_id,
                    "name": name,
                }
            )
            if len(results) == 30:
                break
        return results

    def trading_dates(self, start: date, end: date) -> list[date]:
        frame = self._client.tool_trade_date_hist_sina()
        values = {_as_date(row["trade_date"]) for row in frame.to_dict(orient="records")}
        return sorted(value for value in values if start <= value <= end)


def _spot_quote(instrument: InstrumentId, row: Mapping[str, Any], received: datetime) -> LiveQuote:
    last = _positive(row["最新价"])
    opened = _positive_or(row["今开"], last)
    high = max(_positive_or(row["最高"], last), opened, last)
    low = min(_positive_or(row["最低"], last), opened, last)
    local_received = received.astimezone(_SHANGHAI)
    return LiveQuote(
        instrument_id=instrument,
        trading_date=local_received.date(),
        event_time=received,
        received_time=received,
        last_price=last,
        previous_close=_optional_positive(row["昨收"]),
        open=opened,
        high=high,
        low=low,
        cumulative_volume=Decimal(str(row["成交量"])),
        cumulative_turnover=Decimal(str(row["成交额"])),
        open_interest=None,
        bid=(),
        ask=(),
        source_id="akshare-eastmoney-web",
        quality=frozenset({MarketEventQuality.DELAYED}),
    )


def _minute_bar(row: Mapping[str, Any]) -> MarketBar:
    timestamp = datetime.fromisoformat(str(row["时间"])).replace(tzinfo=_SHANGHAI)
    return _market_bar(timestamp, row)


def _daily_bar(row: Mapping[str, Any]) -> MarketBar:
    timestamp = datetime.combine(_as_date(row["日期"]), datetime.min.time(), _SHANGHAI)
    return _market_bar(timestamp, row)


def _market_bar(timestamp: datetime, row: Mapping[str, Any]) -> MarketBar:
    return MarketBar(
        timestamp=timestamp,
        open=Decimal(str(row["开盘"])),
        high=Decimal(str(row["最高"])),
        low=Decimal(str(row["最低"])),
        close=Decimal(str(row["收盘"])),
        volume=Decimal(str(row["成交量"])) * 100,
        turnover=Decimal(str(row["成交额"])),
    )


def _instrument(symbol: str) -> InstrumentId:
    if symbol.startswith(("4", "8", "9")):
        venue = Venue.BSE
    elif symbol.startswith(("5", "6", "9")):
        venue = Venue.SSE
    else:
        venue = Venue.SZSE
    return InstrumentId(symbol=symbol, venue=venue)


def _index_instrument(symbol: str) -> InstrumentId:
    venue = Venue.SZSE if symbol.startswith("399") else Venue.SSE
    return InstrumentId(symbol=symbol, venue=venue)


def _require_equity(instrument: InstrumentId) -> None:
    if instrument.venue not in {Venue.SSE, Venue.SZSE, Venue.BSE}:
        raise ValueError("AKShare delayed provider only supports A-share instruments")


def _require_columns(actual: set[str], required: frozenset[str]) -> None:
    missing = required - actual
    if missing:
        raise ValueError(f"AKShare response missing columns: {', '.join(sorted(missing))}")


def _positive(value: object) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("price must be positive")
    return parsed


def _positive_or(value: object, fallback: Decimal) -> Decimal:
    try:
        return _positive(value)
    except (ArithmeticError, ValueError):
        return fallback


def _optional_positive(value: object) -> Decimal | None:
    try:
        return _positive(value)
    except (ArithmeticError, ValueError):
        return None


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])

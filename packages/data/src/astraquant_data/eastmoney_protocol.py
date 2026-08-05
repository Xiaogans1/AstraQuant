"""Pure mappings between AstraQuant contracts and Eastmoney ``gm`` payloads."""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from astraquant_domain import InstrumentId, LiveQuote, MarketEventQuality, QuoteLevel, Venue

_TO_EASTMONEY = {
    Venue.SSE: "SHSE",
    Venue.SZSE: "SZSE",
    Venue.BSE: "BJSE",
    Venue.CFFEX: "CFFEX",
    Venue.SHFE: "SHFE",
    Venue.DCE: "DCE",
    Venue.CZCE: "CZCE",
    Venue.INE: "INE",
    Venue.GFEX: "GFEX",
}
_FROM_EASTMONEY = {value: key for key, value in _TO_EASTMONEY.items()}
_CHINA_ZONE = ZoneInfo("Asia/Shanghai")


def to_eastmoney_symbol(instrument_id: InstrumentId) -> str:
    return f"{_TO_EASTMONEY[instrument_id.venue]}.{instrument_id.symbol}"


def from_eastmoney_symbol(value: str) -> InstrumentId:
    parts = value.strip().upper().split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Invalid Eastmoney symbol: {value!r}")
    exchange, symbol = parts
    try:
        venue = _FROM_EASTMONEY[exchange]
    except KeyError as error:
        raise ValueError(f"Unknown Eastmoney exchange: {exchange!r}") from error
    return InstrumentId(symbol=symbol, venue=venue)


def _decimal(payload: Mapping[str, Any], key: str, *, default: Decimal | None = None) -> Decimal:
    value = payload.get(key)
    if value is None or value == "":
        if default is None:
            raise ValueError(f"Eastmoney quote is missing {key}")
        return default
    return Decimal(str(value))


def _aware_datetime(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Eastmoney event time must be timezone-aware")
    return parsed


def _depth_levels(payload: object) -> tuple[tuple[QuoteLevel, ...], tuple[QuoteLevel, ...]]:
    if not isinstance(payload, list):
        return (), ()
    bid: list[QuoteLevel] = []
    ask: list[QuoteLevel] = []
    for raw_level in payload[:10]:
        if not isinstance(raw_level, Mapping):
            continue
        bid_price = Decimal(str(raw_level.get("bid_p", 0)))
        bid_volume = Decimal(str(raw_level.get("bid_v", 0)))
        ask_price = Decimal(str(raw_level.get("ask_p", 0)))
        ask_volume = Decimal(str(raw_level.get("ask_v", 0)))
        if bid_price > 0 and bid_volume >= 0:
            bid.append(QuoteLevel(bid_price, bid_volume))
        if ask_price > 0 and ask_volume >= 0:
            ask.append(QuoteLevel(ask_price, ask_volume))
    return tuple(bid), tuple(ask)


def map_current_quote(
    payload: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
) -> LiveQuote:
    event_time = _aware_datetime(payload.get("created_at"))
    received_time = received_at or datetime.now(UTC)
    if received_time.tzinfo is None or received_time.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    last_price = _decimal(payload, "price")
    previous_close = _decimal(payload, "pre_close", default=Decimal("0"))
    open_price = _decimal(payload, "open", default=last_price)
    if open_price <= 0:
        open_price = last_price
    high = _decimal(payload, "high", default=last_price)
    low = _decimal(payload, "low", default=last_price)
    high = max(high, open_price, last_price)
    low = min((value for value in (low, open_price, last_price) if value > 0), default=last_price)
    bid, ask = _depth_levels(payload.get("quotes"))

    return LiveQuote(
        instrument_id=from_eastmoney_symbol(str(payload.get("symbol", ""))),
        trading_date=event_time.astimezone(_CHINA_ZONE).date(),
        event_time=event_time,
        received_time=received_time,
        last_price=last_price,
        previous_close=previous_close,
        open=open_price,
        high=high,
        low=low,
        cumulative_volume=_decimal(payload, "cum_volume", default=Decimal("0")),
        cumulative_turnover=_decimal(payload, "cum_amount", default=Decimal("0")),
        open_interest=_decimal(payload, "cum_position", default=Decimal("0")),
        bid=bid,
        ask=ask,
        source_id="eastmoney",
        quality=frozenset({MarketEventQuality.NORMAL}),
    )

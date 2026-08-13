"""Real Eastmoney stock discovery and unadjusted daily-bar normalization."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from astraquant_domain import Adjustment, Bar, BarFrequency

from .eastmoney_protocol import from_eastmoney_symbol

_COMMON_PREFIXES = {
    "SHSE": ("600", "601", "603", "605", "688"),
    "SZSE": ("000", "001", "002", "003", "300", "301"),
    "BSE": ("43", "83", "87", "88", "92"),
}


@dataclass(frozen=True, slots=True)
class DailyBootstrapCandidate:
    instrument_id: str
    provider_symbol: str
    security_name: str
    listed_on: date
    delisted_on: date | None
    current_turnover: float


def select_liquid_common_a_share_candidates(
    instruments: Sequence[Mapping[str, object]],
    quotes: Sequence[Mapping[str, object]],
    *,
    as_of: date,
    target_size: int,
) -> tuple[DailyBootstrapCandidate, ...]:
    """Rank currently observable common A shares without accepting B shares or ST names."""

    if isinstance(target_size, bool) or target_size <= 0:
        raise ValueError("target_size must be positive")
    quote_by_symbol: dict[str, Mapping[str, object]] = {}
    for quote in quotes:
        symbol = str(quote.get("symbol", ""))
        if not symbol or symbol in quote_by_symbol:
            raise ValueError("quote symbols must be unique and non-empty")
        quote_by_symbol[symbol] = quote
    candidates: list[DailyBootstrapCandidate] = []
    seen: set[str] = set()
    for instrument in instruments:
        provider_symbol = str(instrument.get("symbol", ""))
        if not provider_symbol or provider_symbol in seen:
            raise ValueError("instrument symbols must be unique and non-empty")
        seen.add(provider_symbol)
        if not _is_common_a_share(provider_symbol):
            continue
        name = str(instrument.get("sec_name", "")).strip()
        if not name or _is_special_treatment(name):
            continue
        listed_on = _provider_date(instrument.get("listed_date"), "listed_date")
        delisted_on = _provider_date(instrument.get("delisted_date"), "delisted_date")
        if listed_on > as_of or delisted_on < as_of:
            continue
        matched_quote = quote_by_symbol.get(provider_symbol)
        if matched_quote is None:
            continue
        try:
            price = float(str(matched_quote.get("price", 0) or 0))
            turnover = float(str(matched_quote.get("cum_amount", 0) or 0))
        except (TypeError, ValueError) as error:
            raise ValueError("quote price and turnover must be numeric") from error
        if not math.isfinite(price) or not math.isfinite(turnover):
            raise ValueError("quote price and turnover must be finite")
        if price <= 0 or turnover <= 0:
            continue
        instrument_id = str(from_eastmoney_symbol(provider_symbol))
        candidates.append(
            DailyBootstrapCandidate(
                instrument_id=instrument_id,
                provider_symbol=provider_symbol,
                security_name=name,
                listed_on=listed_on,
                delisted_on=None if delisted_on.year >= 2038 else delisted_on,
                current_turnover=turnover,
            )
        )
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (-item.current_turnover, item.instrument_id),
        )[:target_size]
    )
    if len(ordered) < target_size:
        raise ValueError("insufficient liquid common A-share candidates")
    return ordered


def eastmoney_daily_rows_to_domain_bars(
    instrument_id: str,
    rows: Sequence[Mapping[str, object]],
) -> tuple[Bar, ...]:
    """Map raw gm daily rows to unadjusted bars whose event time is session close."""

    exact_instrument = from_eastmoney_symbol(_to_provider_symbol(instrument_id))
    bars: dict[datetime, Bar] = {}
    for row in rows:
        provider_symbol = str(row.get("symbol", ""))
        if from_eastmoney_symbol(provider_symbol) != exact_instrument:
            raise ValueError("daily row symbol does not match requested instrument")
        raw_event_time = row.get("eob")
        if raw_event_time is None:
            raise ValueError("daily row requires exact eob session-close time")
        event_time = (
            raw_event_time
            if isinstance(raw_event_time, datetime)
            else datetime.fromisoformat(str(raw_event_time))
        )
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise ValueError("daily row eob must be timezone-aware")
        bar = Bar(
            instrument_id=exact_instrument,
            frequency=BarFrequency.DAY,
            trading_date=event_time.date(),
            event_time=event_time,
            available_time=event_time,
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=Decimal(str(row.get("volume", 0) or 0)),
            turnover=Decimal(str(row.get("amount", 0) or 0)),
            open_interest=None,
            settlement=None,
            adjustment=Adjustment.NONE,
            availability_estimated=False,
        )
        bars[event_time] = bar
    if not bars:
        raise ValueError("daily rows must not be empty")
    return tuple(bars[timestamp] for timestamp in sorted(bars))


def _is_common_a_share(provider_symbol: str) -> bool:
    try:
        exchange, symbol = provider_symbol.split(".", maxsplit=1)
    except ValueError:
        return False
    return exchange in _COMMON_PREFIXES and symbol.startswith(_COMMON_PREFIXES[exchange])


def _is_special_treatment(name: str) -> bool:
    normalized = name.upper().replace(" ", "")
    return normalized.startswith(("ST", "*ST", "S*ST", "SST"))


def _provider_date(value: object, name: str) -> date:
    try:
        parsed = datetime.fromisoformat(str(value)).date()
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO datetime") from error
    return parsed


def _to_provider_symbol(instrument_id: str) -> str:
    try:
        symbol, venue = instrument_id.split(".", maxsplit=1)
    except ValueError as error:
        raise ValueError("invalid canonical instrument_id") from error
    exchange = {"SSE": "SHSE", "SZSE": "SZSE", "BSE": "BSE"}.get(venue)
    if exchange is None:
        raise ValueError("unsupported daily bootstrap venue")
    return f"{exchange}.{symbol}"

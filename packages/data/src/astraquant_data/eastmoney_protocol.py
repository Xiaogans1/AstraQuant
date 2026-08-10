"""Pure mappings between AstraQuant contracts and Eastmoney ``gm`` payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from astraquant_domain import InstrumentId, LiveQuote, MarketEventQuality, QuoteLevel, Venue
from astraquant_domain.run_manifest import validate_digest

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


class PageFailureCode(StrEnum):
    DUPLICATE_PAGE = "DUPLICATE_PAGE"
    MISSING_PAGE = "MISSING_PAGE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    PAGE_MISMATCH = "PAGE_MISMATCH"
    OVERLAPPING_RANGE = "OVERLAPPING_RANGE"
    COUNT_MISMATCH = "COUNT_MISMATCH"
    SILENT_TRUNCATION = "SILENT_TRUNCATION"
    UNPROVEN_COMPLETENESS = "UNPROVEN_COMPLETENESS"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    UNIT_DRIFT = "UNIT_DRIFT"
    ADJUST_DRIFT = "ADJUST_DRIFT"
    FREQUENCY_DRIFT = "FREQUENCY_DRIFT"
    ROW_OUT_OF_RANGE = "ROW_OUT_OF_RANGE"


class HistoryCompletenessError(RuntimeError):
    def __init__(self, code: PageFailureCode) -> None:
        self.code = code
        super().__init__(f"Eastmoney history completeness failure: {code.value}")


def _page_time(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class HistoryPageSpec:
    index: int
    page_count: int
    cursor: str
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        if self.index < 0 or self.page_count <= 0 or self.index >= self.page_count:
            raise ValueError("invalid page index/count")
        if not self.cursor or self.cursor != self.cursor.strip():
            raise ValueError("cursor must be non-empty canonical text")
        object.__setattr__(self, "start_at", _page_time("start_at", self.start_at))
        object.__setattr__(self, "end_at", _page_time("end_at", self.end_at))
        if self.start_at >= self.end_at:
            raise ValueError("page start_at must be before end_at")


@dataclass(frozen=True, slots=True)
class HistoryPageEvidence:
    spec: HistoryPageSpec
    returned_count: int
    declared_total: int | None
    frequency: str
    adjust: int
    units: tuple[str, ...]
    schema_digest: str
    request_digest: str
    response_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.spec, HistoryPageSpec):
            raise ValueError("spec must be HistoryPageSpec")
        if self.returned_count < 0:
            raise ValueError("returned_count must be non-negative")
        if self.declared_total is not None and self.declared_total < 0:
            raise ValueError("declared_total must be non-negative")
        if not self.frequency or self.frequency != self.frequency.strip():
            raise ValueError("frequency must be non-empty canonical text")
        if self.adjust not in (0, 1, 2):
            raise ValueError("adjust must be 0, 1 or 2")
        units = tuple(sorted(self.units))
        if not units or any(not unit or unit != unit.strip() for unit in units):
            raise ValueError("units must contain canonical values")
        if len(units) != len(set(units)):
            raise ValueError("units must not contain duplicates")
        object.__setattr__(self, "units", units)
        object.__setattr__(
            self,
            "schema_digest",
            validate_digest("schema_digest", self.schema_digest),
        )
        object.__setattr__(
            self,
            "request_digest",
            validate_digest("request_digest", self.request_digest),
        )
        object.__setattr__(
            self,
            "response_digest",
            validate_digest("response_digest", self.response_digest),
        )


@dataclass(frozen=True, slots=True)
class HistoryPage:
    rows: tuple[dict[str, object], ...]
    evidence: HistoryPageEvidence

    def __post_init__(self) -> None:
        rows = tuple(dict(row) for row in self.rows)
        object.__setattr__(self, "rows", rows)
        if self.evidence.returned_count != len(rows):
            raise ValueError("returned_count does not match rows")


@dataclass(frozen=True, slots=True)
class HistoryBatch:
    rows: tuple[dict[str, object], ...]
    pages: tuple[HistoryPage, ...]
    declared_total: int
    complete: bool = True


def _raise(code: PageFailureCode) -> NoReturn:
    raise HistoryCompletenessError(code)


def validate_history_pages(
    pages: tuple[HistoryPage, ...],
    *,
    expected_specs: tuple[HistoryPageSpec, ...],
    expected_total: int | None = None,
) -> HistoryBatch:
    pages = tuple(pages)
    expected_specs = tuple(expected_specs)
    indexes = [page.evidence.spec.index for page in pages]
    if len(indexes) != len(set(indexes)):
        _raise(PageFailureCode.DUPLICATE_PAGE)
    if indexes != sorted(indexes):
        _raise(PageFailureCode.OUT_OF_ORDER)
    if len(pages) != len(expected_specs):
        _raise(PageFailureCode.MISSING_PAGE)
    if not expected_specs:
        _raise(PageFailureCode.UNPROVEN_COMPLETENESS)
    for previous, current in pairwise(expected_specs):
        if previous.end_at > current.start_at:
            _raise(PageFailureCode.OVERLAPPING_RANGE)
    for page, expected in zip(pages, expected_specs, strict=True):
        if page.evidence.spec != expected:
            _raise(PageFailureCode.PAGE_MISMATCH)
        for row in page.rows:
            raw_time = next(
                (row[key] for key in ("bob", "eob", "created_at") if key in row),
                None,
            )
            if raw_time is None:
                continue
            try:
                row_time = datetime.fromisoformat(str(raw_time))
            except ValueError:
                _raise(PageFailureCode.ROW_OUT_OF_RANGE)
            if row_time.tzinfo is None or row_time.utcoffset() is None:
                _raise(PageFailureCode.ROW_OUT_OF_RANGE)
            row_time = row_time.astimezone(UTC)
            if row_time < expected.start_at or row_time > expected.end_at:
                _raise(PageFailureCode.ROW_OUT_OF_RANGE)
    evidence = [page.evidence for page in pages]
    if len({item.schema_digest for item in evidence}) != 1:
        _raise(PageFailureCode.SCHEMA_DRIFT)
    if len({item.units for item in evidence}) != 1:
        _raise(PageFailureCode.UNIT_DRIFT)
    if len({item.adjust for item in evidence}) != 1:
        _raise(PageFailureCode.ADJUST_DRIFT)
    if len({item.frequency for item in evidence}) != 1:
        _raise(PageFailureCode.FREQUENCY_DRIFT)
    rows = tuple(row for page in pages for row in page.rows)
    declared_values = {item.declared_total for item in evidence if item.declared_total is not None}
    if len(declared_values) > 1:
        _raise(PageFailureCode.COUNT_MISMATCH)
    declared_total = next(iter(declared_values), None)
    proof_total = expected_total if expected_total is not None else declared_total
    if proof_total is None:
        _raise(PageFailureCode.UNPROVEN_COMPLETENESS)
    if proof_total < 0:
        raise ValueError("expected_total must be non-negative")
    if (
        declared_total is not None
        and expected_total is not None
        and declared_total != expected_total
    ):
        _raise(PageFailureCode.COUNT_MISMATCH)
    if len(rows) != proof_total:
        _raise(PageFailureCode.SILENT_TRUNCATION)
    return HistoryBatch(
        rows=rows,
        pages=pages,
        declared_total=proof_total,
    )


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


def _positive_decimal_or_none(payload: Mapping[str, Any], key: str) -> Decimal | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    parsed = Decimal(str(value))
    return parsed if parsed > 0 else None


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
    previous_close = _positive_decimal_or_none(payload, "pre_close")
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

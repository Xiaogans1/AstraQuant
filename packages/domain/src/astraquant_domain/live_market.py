"""Immutable contracts for realtime market snapshots."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from astraquant_domain.identifiers import InstrumentId


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class MarketEventQuality(StrEnum):
    """Quality annotations assigned without replacing the provider payload."""

    NORMAL = "NORMAL"
    DELAYED = "DELAYED"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    CLOCK_SKEW = "CLOCK_SKEW"


@dataclass(frozen=True, slots=True)
class QuoteLevel:
    """One provider-supplied order-book level."""

    price: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("quote level price must be positive")
        if self.volume < 0:
            raise ValueError("quote level volume must be non-negative")


@dataclass(frozen=True, slots=True)
class LiveQuote:
    """Latest real snapshot for one canonical instrument."""

    instrument_id: InstrumentId
    trading_date: date
    event_time: datetime
    received_time: datetime
    last_price: Decimal
    previous_close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    cumulative_volume: Decimal
    cumulative_turnover: Decimal | None
    open_interest: Decimal | None
    bid: tuple[QuoteLevel, ...]
    ask: tuple[QuoteLevel, ...]
    source_id: str
    quality: frozenset[MarketEventQuality]

    def __post_init__(self) -> None:
        _require_aware("event_time", self.event_time)
        _require_aware("received_time", self.received_time)
        if any(price <= 0 for price in (self.last_price, self.open, self.high, self.low)):
            raise ValueError("quote prices must be positive")
        if self.previous_close < 0:
            raise ValueError("previous close must be non-negative")
        if self.low > self.high:
            raise ValueError("quote low must not exceed high")
        if self.high < max(self.open, self.last_price):
            raise ValueError("quote high must include open and last price")
        if self.low > min(self.open, self.last_price):
            raise ValueError("quote low must include open and last price")
        if self.cumulative_volume < 0:
            raise ValueError("cumulative volume must be non-negative")
        if self.cumulative_turnover is not None and self.cumulative_turnover < 0:
            raise ValueError("cumulative turnover must be non-negative")
        if self.open_interest is not None and self.open_interest < 0:
            raise ValueError("open interest must be non-negative")
        if len(self.bid) > 10 or len(self.ask) > 10:
            raise ValueError("quote depth must contain at most ten levels per side")
        source_id = self.source_id.strip()
        if not source_id:
            raise ValueError("source_id must not be empty")
        object.__setattr__(self, "source_id", source_id)
        if not self.quality:
            raise ValueError("quality must contain at least one annotation")

    @property
    def change(self) -> Decimal:
        return self.last_price - self.previous_close

    @property
    def change_percent(self) -> Decimal:
        if self.previous_close == 0:
            return Decimal("0")
        return (self.change / self.previous_close * 100).quantize(Decimal("0.0001"))

    @classmethod
    def minimum(
        cls,
        instrument_id: InstrumentId,
        *,
        event_time: datetime,
        last_price: Decimal,
        previous_close: Decimal,
        received_time: datetime | None = None,
        bid: tuple[QuoteLevel, ...] = (),
        ask: tuple[QuoteLevel, ...] = (),
        source_id: str = "eastmoney",
        quality: frozenset[MarketEventQuality] | None = None,
    ) -> Self:
        return cls(
            instrument_id=instrument_id,
            trading_date=event_time.date(),
            event_time=event_time,
            received_time=received_time or event_time,
            last_price=last_price,
            previous_close=previous_close,
            open=last_price,
            high=last_price,
            low=last_price,
            cumulative_volume=Decimal("0"),
            cumulative_turnover=None,
            open_interest=None,
            bid=bid,
            ask=ask,
            source_id=source_id,
            quality=quality or frozenset({MarketEventQuality.NORMAL}),
        )

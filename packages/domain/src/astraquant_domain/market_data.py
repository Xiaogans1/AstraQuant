"""Canonical market-data records shared by batch and streaming providers."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from astraquant_domain.identifiers import InstrumentId


class BarFrequency(StrEnum):
    TICK = "tick"
    MINUTE = "1m"
    DAY = "1d"


class Adjustment(StrEnum):
    NONE = "none"
    FORWARD = "qfq"
    BACKWARD = "hfq"


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Bar:
    instrument_id: InstrumentId
    frequency: BarFrequency
    event_time: datetime
    available_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None
    settlement: Decimal | None
    adjustment: Adjustment
    availability_estimated: bool

    def __post_init__(self) -> None:
        _require_aware("event_time", self.event_time)
        _require_aware("available_time", self.available_time)
        if self.available_time < self.event_time:
            raise ValueError("available_time must not precede event_time")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")
        if self.high < max(self.open, self.close) or self.low > min(
            self.open, self.close
        ):
            raise ValueError("OHLC values are inconsistent")
        if self.low > self.high:
            raise ValueError("OHLC low must not exceed high")


@dataclass(frozen=True, slots=True)
class Tick:
    instrument_id: InstrumentId
    event_time: datetime
    available_time: datetime
    last_price: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None

    def __post_init__(self) -> None:
        _require_aware("event_time", self.event_time)
        _require_aware("available_time", self.available_time)
        if self.available_time < self.event_time:
            raise ValueError("available_time must not precede event_time")
        if self.last_price <= 0 or self.volume < 0:
            raise ValueError("tick price must be positive and volume non-negative")

"""Canonical market-data records shared by batch and streaming providers."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from astraquant_domain.identifiers import InstrumentId
from astraquant_domain.run_manifest import validate_digest


class BarFrequency(StrEnum):
    TICK = "tick"
    MINUTE = "1m"
    FIVE_MINUTE = "5m"
    DAY = "1d"


class Adjustment(StrEnum):
    NONE = "none"
    FORWARD = "qfq"
    BACKWARD = "hfq"


class VintageKind(StrEnum):
    SOURCE_CERTIFIED = "SOURCE_CERTIFIED"
    SOURCE_VERSIONED = "SOURCE_VERSIONED"
    LOCALLY_OBSERVED = "LOCALLY_OBSERVED"
    AS_DELIVERED_UNVERSIONED = "AS_DELIVERED_UNVERSIONED"


class AvailabilityBasis(StrEnum):
    SOURCE_DECLARED = "SOURCE_DECLARED"
    SESSION_CLOSE = "SESSION_CLOSE"
    SOURCE_REVISION = "SOURCE_REVISION"
    FIRST_RECEIVED = "FIRST_RECEIVED"


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ObservationInterval:
    interval_start: datetime
    interval_end: datetime
    event_time: datetime
    calendar_snapshot_id: str

    def __post_init__(self) -> None:
        for name in ("interval_start", "interval_end", "event_time"):
            _require_aware(name, getattr(self, name))
        if self.interval_start >= self.interval_end:
            raise ValueError("interval_start must precede interval_end")
        if self.event_time != self.interval_end:
            raise ValueError("bar event_time must equal exact interval_end")
        object.__setattr__(
            self,
            "calendar_snapshot_id",
            validate_digest("calendar_snapshot_id", self.calendar_snapshot_id),
        )
        if self.calendar_snapshot_id == f"sha256:{'0' * 64}":
            raise ValueError("calendar_snapshot_id must not be a sentinel digest")


@dataclass(frozen=True, slots=True)
class Bar:
    instrument_id: InstrumentId
    frequency: BarFrequency
    trading_date: date
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
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
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

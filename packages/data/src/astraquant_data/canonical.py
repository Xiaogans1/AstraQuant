"""Immutable v3 canonical bar observations with raw-capture and vintage lineage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal

from astraquant_domain import (
    Adjustment,
    AvailabilityBasis,
    BarFrequency,
    InstrumentId,
    ObservationInterval,
    VintageKind,
)
from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

CANONICAL_BAR_SCHEMA_VERSION = "astraquant.canonical-bar/v1"
_PRICE_QUANTUM = Decimal("0.00000001")
_MEASURE_QUANTUM = Decimal("0.00000001")
_SUPPORTED_UNITS = frozenset(
    {
        ("price=CNY", "turnover=CNY", "volume=contract"),
        ("price=CNY", "turnover=CNY", "volume=share"),
    }
)


class CanonicalQuarantineError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"canonical observation quarantined: {code}")


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _non_sentinel_digest(name: str, value: str) -> str:
    try:
        digest = validate_digest(name, value)
    except ValueError as error:
        raise CanonicalQuarantineError("LINEAGE_DIGEST") from error
    if digest == f"sha256:{'0' * 64}":
        raise CanonicalQuarantineError("LINEAGE_DIGEST")
    return digest


def _aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalQuarantineError(f"NAIVE_{name.upper()}")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CaptureRowLineage:
    capture_id: str
    chunk_id: str
    row_index: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "capture_id", _non_sentinel_digest("capture_id", self.capture_id))
        object.__setattr__(self, "chunk_id", _non_sentinel_digest("chunk_id", self.chunk_id))
        if self.row_index < 0:
            raise CanonicalQuarantineError("ROW_INDEX")

    def to_dict(self) -> dict[str, object]:
        return {
            "capture_id": self.capture_id,
            "chunk_id": self.chunk_id,
            "row_index": self.row_index,
        }


@dataclass(frozen=True, slots=True)
class CanonicalBarInput:
    instrument_id: InstrumentId
    frequency: BarFrequency
    trading_date: date
    source_available_time: datetime
    observed_received_time: datetime
    recorded_time: datetime
    first_received_time: datetime
    source_revision_time: datetime | None
    source_revision_id: str | None
    vintage_proven_time: datetime
    vintage_kind: VintageKind
    availability_basis: AvailabilityBasis
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None
    settlement: Decimal | None
    adjustment: Adjustment
    source_adjustment: Adjustment
    units: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CanonicalBarObservation:
    instrument_id: InstrumentId
    frequency: BarFrequency
    trading_date: date
    interval_start: datetime
    interval_end: datetime
    event_time: datetime
    source_available_time: datetime
    observed_received_time: datetime
    recorded_time: datetime
    first_received_time: datetime
    source_revision_time: datetime | None
    source_revision_id: str | None
    vintage_proven_time: datetime
    vintage_kind: VintageKind
    availability_basis: AvailabilityBasis
    calendar_snapshot_id: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None
    settlement: Decimal | None
    adjustment: Adjustment
    units: tuple[str, ...]
    value_hash: str
    vintage_id: str
    supersedes_vintage_id: str | None
    lineage: CaptureRowLineage
    schema_version: str = CANONICAL_BAR_SCHEMA_VERSION

    @property
    def canonical_key(self) -> tuple[str, str, datetime, datetime, str]:
        return (
            str(self.instrument_id),
            self.frequency.value,
            self.interval_start,
            self.interval_end,
            self.vintage_id,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "instrument_id": str(self.instrument_id),
            "frequency": self.frequency.value,
            "trading_date": self.trading_date.isoformat(),
            "interval_start": self.interval_start.isoformat(),
            "interval_end": self.interval_end.isoformat(),
            "event_time": self.event_time.isoformat(),
            "source_available_time": self.source_available_time.isoformat(),
            "observed_received_time": self.observed_received_time.isoformat(),
            "recorded_time": self.recorded_time.isoformat(),
            "first_received_time": self.first_received_time.isoformat(),
            "source_revision_time": (
                None if self.source_revision_time is None else self.source_revision_time.isoformat()
            ),
            "source_revision_id": self.source_revision_id,
            "vintage_proven_time": self.vintage_proven_time.isoformat(),
            "vintage_kind": self.vintage_kind.value,
            "availability_basis": self.availability_basis.value,
            "calendar_snapshot_id": self.calendar_snapshot_id,
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
            "turnover": None if self.turnover is None else str(self.turnover),
            "open_interest": (None if self.open_interest is None else str(self.open_interest)),
            "settlement": None if self.settlement is None else str(self.settlement),
            "adjustment": self.adjustment.value,
            "units": list(self.units),
            "value_hash": self.value_hash,
            "vintage_id": self.vintage_id,
            "supersedes_vintage_id": self.supersedes_vintage_id,
            "lineage": self.lineage.to_dict(),
        }


def _value_payload(value: CanonicalBarInput) -> dict[str, object]:
    return {
        "open": str(value.open),
        "high": str(value.high),
        "low": str(value.low),
        "close": str(value.close),
        "volume": str(value.volume),
        "turnover": None if value.turnover is None else str(value.turnover),
        "open_interest": (None if value.open_interest is None else str(value.open_interest)),
        "settlement": None if value.settlement is None else str(value.settlement),
        "adjustment": value.adjustment.value,
        "units": list(value.units),
    }


def _validate_input(value: CanonicalBarInput, interval: ObservationInterval) -> None:
    if value.adjustment is not Adjustment.NONE or value.source_adjustment is not Adjustment.NONE:
        raise CanonicalQuarantineError("RAW_ADJUSTMENT")
    units = tuple(sorted(value.units))
    if units not in _SUPPORTED_UNITS or len(units) != len(set(units)):
        raise CanonicalQuarantineError("UNITS")
    if value.high < max(value.open, value.close) or value.low > min(value.open, value.close):
        raise CanonicalQuarantineError("OHLC")
    if value.low > value.high or value.volume < 0:
        raise CanonicalQuarantineError("OHLCV")
    source_available = _aware("source_available_time", value.source_available_time)
    observed = _aware("observed_received_time", value.observed_received_time)
    recorded = _aware("recorded_time", value.recorded_time)
    first_received = _aware("first_received_time", value.first_received_time)
    proven = _aware("vintage_proven_time", value.vintage_proven_time)
    if source_available < interval.event_time:
        raise CanonicalQuarantineError("SOURCE_AVAILABILITY")
    if recorded < observed or first_received > observed:
        raise CanonicalQuarantineError("CAPTURE_CLOCK_ORDER")
    if value.vintage_kind is VintageKind.SOURCE_VERSIONED:
        if value.source_revision_time is None or not value.source_revision_id:
            raise CanonicalQuarantineError("REVISION_PROOF")
        revision = _aware("source_revision_time", value.source_revision_time)
        if (
            revision < source_available
            or proven != revision
            or value.availability_basis is not AvailabilityBasis.SOURCE_REVISION
        ):
            raise CanonicalQuarantineError("REVISION_PROOF")
    elif value.source_revision_time is not None or value.source_revision_id is not None:
        raise CanonicalQuarantineError("REVISION_PROOF")
    elif value.vintage_kind in {
        VintageKind.LOCALLY_OBSERVED,
        VintageKind.AS_DELIVERED_UNVERSIONED,
    }:
        if proven != first_received:
            raise CanonicalQuarantineError("VINTAGE_PROOF")
    elif value.vintage_kind is VintageKind.SOURCE_CERTIFIED:
        if proven != source_available:
            raise CanonicalQuarantineError("VINTAGE_PROOF")


def _vintage_digest(
    value: CanonicalBarInput, interval: ObservationInterval, value_hash: str
) -> str:
    source_revision_time = (
        None
        if value.source_revision_time is None
        else value.source_revision_time.astimezone(UTC).isoformat()
    )
    return _digest(
        {
            "instrument_id": str(value.instrument_id),
            "frequency": value.frequency.value,
            "interval_start": interval.interval_start.astimezone(UTC).isoformat(),
            "interval_end": interval.interval_end.astimezone(UTC).isoformat(),
            "source_revision_time": source_revision_time,
            "source_revision_id": value.source_revision_id,
            "vintage_proven_time": value.vintage_proven_time.astimezone(UTC).isoformat(),
            "vintage_kind": value.vintage_kind.value,
            "value_hash": value_hash,
        }
    )


def normalize_bar(
    value: CanonicalBarInput,
    *,
    interval: ObservationInterval,
    lineage: CaptureRowLineage,
    supersedes_vintage_id: str | None = None,
) -> CanonicalBarObservation:
    value = replace(
        value,
        open=value.open.quantize(_PRICE_QUANTUM),
        high=value.high.quantize(_PRICE_QUANTUM),
        low=value.low.quantize(_PRICE_QUANTUM),
        close=value.close.quantize(_PRICE_QUANTUM),
        volume=value.volume.quantize(_MEASURE_QUANTUM),
        turnover=(None if value.turnover is None else value.turnover.quantize(_MEASURE_QUANTUM)),
        open_interest=(
            None if value.open_interest is None else value.open_interest.quantize(_MEASURE_QUANTUM)
        ),
        settlement=(
            None if value.settlement is None else value.settlement.quantize(_PRICE_QUANTUM)
        ),
    )
    _validate_input(value, interval)
    units = tuple(sorted(value.units))
    source_revision_time = (
        None if value.source_revision_time is None else value.source_revision_time.astimezone(UTC)
    )
    value_hash = _digest(_value_payload(value))
    vintage_id = _vintage_digest(value, interval, value_hash)
    supersedes = (
        None
        if supersedes_vintage_id is None
        else _non_sentinel_digest("supersedes_vintage_id", supersedes_vintage_id)
    )
    if supersedes == vintage_id:
        raise CanonicalQuarantineError("SELF_SUPERSEDES")
    return CanonicalBarObservation(
        instrument_id=value.instrument_id,
        frequency=value.frequency,
        trading_date=value.trading_date,
        interval_start=interval.interval_start.astimezone(UTC),
        interval_end=interval.interval_end.astimezone(UTC),
        event_time=interval.event_time.astimezone(UTC),
        source_available_time=value.source_available_time.astimezone(UTC),
        observed_received_time=value.observed_received_time.astimezone(UTC),
        recorded_time=value.recorded_time.astimezone(UTC),
        first_received_time=value.first_received_time.astimezone(UTC),
        source_revision_time=source_revision_time,
        source_revision_id=value.source_revision_id,
        vintage_proven_time=value.vintage_proven_time.astimezone(UTC),
        vintage_kind=value.vintage_kind,
        availability_basis=value.availability_basis,
        calendar_snapshot_id=interval.calendar_snapshot_id,
        open=value.open,
        high=value.high,
        low=value.low,
        close=value.close,
        volume=value.volume,
        turnover=value.turnover,
        open_interest=value.open_interest,
        settlement=value.settlement,
        adjustment=value.adjustment,
        units=units,
        value_hash=value_hash,
        vintage_id=vintage_id,
        supersedes_vintage_id=supersedes,
        lineage=lineage,
    )


def _recomputed_value_hash(value: CanonicalBarObservation) -> str:
    return _digest(
        {
            "open": str(value.open),
            "high": str(value.high),
            "low": str(value.low),
            "close": str(value.close),
            "volume": str(value.volume),
            "turnover": None if value.turnover is None else str(value.turnover),
            "open_interest": (None if value.open_interest is None else str(value.open_interest)),
            "settlement": None if value.settlement is None else str(value.settlement),
            "adjustment": value.adjustment.value,
            "units": list(value.units),
        }
    )


def _validate_observation(value: CanonicalBarObservation) -> None:
    try:
        interval = ObservationInterval(
            interval_start=value.interval_start,
            interval_end=value.interval_end,
            event_time=value.event_time,
            calendar_snapshot_id=value.calendar_snapshot_id,
        )
    except ValueError as error:
        raise CanonicalQuarantineError("INTERVAL") from error
    canonical_input = CanonicalBarInput(
        instrument_id=value.instrument_id,
        frequency=value.frequency,
        trading_date=value.trading_date,
        source_available_time=value.source_available_time,
        observed_received_time=value.observed_received_time,
        recorded_time=value.recorded_time,
        first_received_time=value.first_received_time,
        source_revision_time=value.source_revision_time,
        source_revision_id=value.source_revision_id,
        vintage_proven_time=value.vintage_proven_time,
        vintage_kind=value.vintage_kind,
        availability_basis=value.availability_basis,
        open=value.open,
        high=value.high,
        low=value.low,
        close=value.close,
        volume=value.volume,
        turnover=value.turnover,
        open_interest=value.open_interest,
        settlement=value.settlement,
        adjustment=value.adjustment,
        source_adjustment=Adjustment.NONE,
        units=value.units,
    )
    _validate_input(canonical_input, interval)
    if _recomputed_value_hash(value) != value.value_hash:
        raise CanonicalQuarantineError("DUPLICATE_CONFLICT")
    if _vintage_digest(canonical_input, interval, value.value_hash) != value.vintage_id:
        raise CanonicalQuarantineError("VINTAGE_ID")


def validate_canonical_observations(
    observations: tuple[CanonicalBarObservation, ...] | list[CanonicalBarObservation],
) -> tuple[CanonicalBarObservation, ...]:
    ordered: list[CanonicalBarObservation] = []
    by_key: dict[tuple[str, str, datetime, datetime, str], CanonicalBarObservation] = {}
    seen_vintages: set[str] = set()
    for observation in observations:
        if observation.schema_version != CANONICAL_BAR_SCHEMA_VERSION:
            raise CanonicalQuarantineError("SCHEMA_VERSION")
        _validate_observation(observation)
        previous = by_key.get(observation.canonical_key)
        if previous is not None:
            if previous != observation:
                raise CanonicalQuarantineError("DUPLICATE_CONFLICT")
            continue
        if (
            observation.supersedes_vintage_id is not None
            and observation.supersedes_vintage_id not in seen_vintages
        ):
            raise CanonicalQuarantineError("MISSING_SUPERSEDED_VINTAGE")
        by_key[observation.canonical_key] = observation
        seen_vintages.add(observation.vintage_id)
        ordered.append(observation)
    return tuple(ordered)

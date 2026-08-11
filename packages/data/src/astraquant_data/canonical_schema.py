"""Exact Arrow persistence contract for v3 canonical bar observations."""

from __future__ import annotations

from datetime import UTC

import pyarrow as pa  # type: ignore[import-untyped]

from astraquant_data.canonical import (
    CANONICAL_BAR_SCHEMA_VERSION,
    CanonicalBarObservation,
    CaptureRowLineage,
    validate_canonical_observations,
)
from astraquant_domain import (
    Adjustment,
    AvailabilityBasis,
    BarFrequency,
    InstrumentId,
    VintageKind,
)

_UTC_TIMESTAMP = pa.timestamp("us", tz="UTC")
_DICTIONARY_STRING = pa.dictionary(pa.int8(), pa.string())

CANONICAL_BAR_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("frequency", _DICTIONARY_STRING, nullable=False),
        pa.field("trading_date", pa.date32(), nullable=False),
        pa.field("interval_start", _UTC_TIMESTAMP, nullable=False),
        pa.field("interval_end", _UTC_TIMESTAMP, nullable=False),
        pa.field("event_time", _UTC_TIMESTAMP, nullable=False),
        pa.field("source_available_time", _UTC_TIMESTAMP, nullable=False),
        pa.field("observed_received_time", _UTC_TIMESTAMP, nullable=False),
        pa.field("recorded_time", _UTC_TIMESTAMP, nullable=False),
        pa.field("first_received_time", _UTC_TIMESTAMP, nullable=False),
        pa.field("source_revision_time", _UTC_TIMESTAMP),
        pa.field("source_revision_id", pa.string()),
        pa.field("vintage_proven_time", _UTC_TIMESTAMP, nullable=False),
        pa.field("vintage_kind", _DICTIONARY_STRING, nullable=False),
        pa.field("availability_basis", _DICTIONARY_STRING, nullable=False),
        pa.field("calendar_snapshot_id", pa.string(), nullable=False),
        pa.field("open", pa.decimal128(24, 8), nullable=False),
        pa.field("high", pa.decimal128(24, 8), nullable=False),
        pa.field("low", pa.decimal128(24, 8), nullable=False),
        pa.field("close", pa.decimal128(24, 8), nullable=False),
        pa.field("volume", pa.decimal128(30, 8), nullable=False),
        pa.field("turnover", pa.decimal128(30, 8)),
        pa.field("open_interest", pa.decimal128(30, 8)),
        pa.field("settlement", pa.decimal128(24, 8)),
        pa.field("adjustment", _DICTIONARY_STRING, nullable=False),
        pa.field("units", pa.list_(pa.string()), nullable=False),
        pa.field("value_hash", pa.string(), nullable=False),
        pa.field("vintage_id", pa.string(), nullable=False),
        pa.field("supersedes_vintage_id", pa.string()),
        pa.field("capture_id", pa.string(), nullable=False),
        pa.field("chunk_id", pa.string(), nullable=False),
        pa.field("row_index", pa.int64(), nullable=False),
    ],
    metadata={b"schema_version": CANONICAL_BAR_SCHEMA_VERSION.encode("ascii")},
)


def canonical_bars_to_table(
    observations: tuple[CanonicalBarObservation, ...] | list[CanonicalBarObservation],
) -> pa.Table:
    validated = validate_canonical_observations(observations)
    records = []
    for value in validated:
        records.append(
            {
                "schema_version": value.schema_version,
                "instrument_id": str(value.instrument_id),
                "frequency": value.frequency.value,
                "trading_date": value.trading_date,
                "interval_start": value.interval_start.astimezone(UTC),
                "interval_end": value.interval_end.astimezone(UTC),
                "event_time": value.event_time.astimezone(UTC),
                "source_available_time": value.source_available_time.astimezone(UTC),
                "observed_received_time": value.observed_received_time.astimezone(UTC),
                "recorded_time": value.recorded_time.astimezone(UTC),
                "first_received_time": value.first_received_time.astimezone(UTC),
                "source_revision_time": value.source_revision_time,
                "source_revision_id": value.source_revision_id,
                "vintage_proven_time": value.vintage_proven_time.astimezone(UTC),
                "vintage_kind": value.vintage_kind.value,
                "availability_basis": value.availability_basis.value,
                "calendar_snapshot_id": value.calendar_snapshot_id,
                "open": value.open,
                "high": value.high,
                "low": value.low,
                "close": value.close,
                "volume": value.volume,
                "turnover": value.turnover,
                "open_interest": value.open_interest,
                "settlement": value.settlement,
                "adjustment": value.adjustment.value,
                "units": list(value.units),
                "value_hash": value.value_hash,
                "vintage_id": value.vintage_id,
                "supersedes_vintage_id": value.supersedes_vintage_id,
                "capture_id": value.lineage.capture_id,
                "chunk_id": value.lineage.chunk_id,
                "row_index": value.lineage.row_index,
            }
        )
    return pa.Table.from_pylist(records, schema=CANONICAL_BAR_SCHEMA)


def table_to_canonical_bars(table: pa.Table) -> tuple[CanonicalBarObservation, ...]:
    if not table.schema.equals(CANONICAL_BAR_SCHEMA, check_metadata=True):
        raise ValueError(f"canonical bar schema does not match frozen contract: {table.schema}")
    observations = []
    for row in table.to_pylist():
        observations.append(
            CanonicalBarObservation(
                instrument_id=InstrumentId.parse(row["instrument_id"]),
                frequency=BarFrequency(row["frequency"]),
                trading_date=row["trading_date"],
                interval_start=row["interval_start"],
                interval_end=row["interval_end"],
                event_time=row["event_time"],
                source_available_time=row["source_available_time"],
                observed_received_time=row["observed_received_time"],
                recorded_time=row["recorded_time"],
                first_received_time=row["first_received_time"],
                source_revision_time=row["source_revision_time"],
                source_revision_id=row["source_revision_id"],
                vintage_proven_time=row["vintage_proven_time"],
                vintage_kind=VintageKind(row["vintage_kind"]),
                availability_basis=AvailabilityBasis(row["availability_basis"]),
                calendar_snapshot_id=row["calendar_snapshot_id"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                turnover=row["turnover"],
                open_interest=row["open_interest"],
                settlement=row["settlement"],
                adjustment=Adjustment(row["adjustment"]),
                units=tuple(row["units"]),
                value_hash=row["value_hash"],
                vintage_id=row["vintage_id"],
                supersedes_vintage_id=row["supersedes_vintage_id"],
                lineage=CaptureRowLineage(
                    capture_id=row["capture_id"],
                    chunk_id=row["chunk_id"],
                    row_index=row["row_index"],
                ),
                schema_version=row["schema_version"],
            )
        )
    return validate_canonical_observations(observations)

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from astraquant_data.canonical import (
    CanonicalBarInput,
    CanonicalQuarantineError,
    CaptureRowLineage,
    normalize_bar,
    validate_canonical_observations,
)
from astraquant_data.canonical_schema import (
    CANONICAL_BAR_SCHEMA,
    canonical_bars_to_table,
    table_to_canonical_bars,
)
from astraquant_domain import (
    Adjustment,
    AvailabilityBasis,
    BarFrequency,
    InstrumentId,
    ObservationInterval,
    VintageKind,
)

SOURCE_AVAILABLE = datetime(2010, 1, 4, 7, 1, tzinfo=UTC)
RECEIVED = datetime(2026, 8, 11, 1, 2, tzinfo=UTC)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _interval() -> ObservationInterval:
    return ObservationInterval(
        interval_start=datetime(2010, 1, 4, 1, 30, tzinfo=UTC),
        interval_end=datetime(2010, 1, 4, 7, 0, tzinfo=UTC),
        event_time=datetime(2010, 1, 4, 7, 0, tzinfo=UTC),
        calendar_snapshot_id=_digest("1"),
    )


def _lineage() -> CaptureRowLineage:
    return CaptureRowLineage(
        capture_id=_digest("2"),
        chunk_id=_digest("3"),
        row_index=7,
    )


def _input(**changes: object) -> CanonicalBarInput:
    values: dict[str, object] = {
        "instrument_id": InstrumentId.parse("600000.SSE"),
        "frequency": BarFrequency.DAY,
        "trading_date": date(2010, 1, 4),
        "source_available_time": SOURCE_AVAILABLE,
        "observed_received_time": RECEIVED,
        "recorded_time": RECEIVED + timedelta(seconds=1),
        "first_received_time": RECEIVED,
        "source_revision_time": None,
        "source_revision_id": None,
        "vintage_proven_time": RECEIVED,
        "vintage_kind": VintageKind.AS_DELIVERED_UNVERSIONED,
        "availability_basis": AvailabilityBasis.SESSION_CLOSE,
        "open": Decimal("10.00"),
        "high": Decimal("10.80"),
        "low": Decimal("9.90"),
        "close": Decimal("10.50"),
        "volume": Decimal("120000"),
        "turnover": Decimal("1250000"),
        "open_interest": None,
        "settlement": None,
        "adjustment": Adjustment.NONE,
        "source_adjustment": Adjustment.NONE,
        "units": ("price=CNY", "turnover=CNY", "volume=share"),
    }
    values.update(changes)
    return CanonicalBarInput(**values)  # type: ignore[arg-type]


def test_historical_backfill_keeps_nominal_and_observed_clocks_separate() -> None:
    bar = normalize_bar(_input(), interval=_interval(), lineage=_lineage())

    assert bar.event_time == _interval().interval_end
    assert bar.source_available_time.year == 2010
    assert bar.observed_received_time.year == 2026
    assert bar.recorded_time > bar.observed_received_time
    assert bar.lineage == _lineage()
    assert bar.value_hash.startswith("sha256:")
    assert bar.vintage_id.startswith("sha256:")
    assert normalize_bar(_input(), interval=_interval(), lineage=_lineage()) == bar


@pytest.mark.parametrize("adjustment", [Adjustment.FORWARD, Adjustment.BACKWARD])
def test_raw_canonical_bar_rejects_adjusted_provider_values(
    adjustment: Adjustment,
) -> None:
    with pytest.raises(CanonicalQuarantineError, match="RAW_ADJUSTMENT"):
        normalize_bar(
            _input(adjustment=adjustment),
            interval=_interval(),
            lineage=_lineage(),
        )


def test_raw_canonical_bar_rejects_adjusted_api_request_mislabeled_as_none() -> None:
    with pytest.raises(CanonicalQuarantineError, match="RAW_ADJUSTMENT"):
        normalize_bar(
            _input(
                adjustment=Adjustment.NONE,
                source_adjustment=Adjustment.FORWARD,
            ),
            interval=_interval(),
            lineage=_lineage(),
        )


def test_canonical_bar_rejects_unknown_units() -> None:
    with pytest.raises(CanonicalQuarantineError, match="UNITS"):
        normalize_bar(
            _input(units=("price=CNY", "volume=lot")),
            interval=_interval(),
            lineage=_lineage(),
        )


def test_source_versioned_vintage_requires_exact_revision_proof() -> None:
    with pytest.raises(CanonicalQuarantineError, match="REVISION_PROOF"):
        normalize_bar(
            _input(vintage_kind=VintageKind.SOURCE_VERSIONED),
            interval=_interval(),
            lineage=_lineage(),
        )


def test_locally_observed_vintage_proof_must_equal_first_receive() -> None:
    with pytest.raises(CanonicalQuarantineError, match="VINTAGE_PROOF"):
        normalize_bar(
            _input(
                vintage_kind=VintageKind.LOCALLY_OBSERVED,
                vintage_proven_time=SOURCE_AVAILABLE,
            ),
            interval=_interval(),
            lineage=_lineage(),
        )


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"observed_received_time": RECEIVED.replace(tzinfo=None)}, "NAIVE_"),
        (
            {"recorded_time": RECEIVED - timedelta(microseconds=1)},
            "CAPTURE_CLOCK_ORDER",
        ),
        (
            {"first_received_time": RECEIVED + timedelta(microseconds=1)},
            "CAPTURE_CLOCK_ORDER",
        ),
    ],
)
def test_canonical_bar_rejects_invalid_capture_clocks(
    changes: dict[str, object], code: str
) -> None:
    with pytest.raises(CanonicalQuarantineError, match=code):
        normalize_bar(_input(**changes), interval=_interval(), lineage=_lineage())


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 8, 10, 9, 30), datetime(2026, 8, 10, 11, 30)),
        (datetime(2026, 8, 10, 13, 0), datetime(2026, 8, 10, 15, 0)),
        (datetime(2026, 12, 31, 9, 30), datetime(2026, 12, 31, 11, 30)),
    ],
)
def test_bar_keeps_exact_calendar_interval_across_breaks_and_half_days(
    start: datetime, end: datetime
) -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    exact = ObservationInterval(
        interval_start=start.replace(tzinfo=shanghai),
        interval_end=end.replace(tzinfo=shanghai),
        event_time=end.replace(tzinfo=shanghai),
        calendar_snapshot_id=_digest("9"),
    )
    source_available = end.replace(tzinfo=shanghai) + timedelta(minutes=1)
    bar = normalize_bar(
        _input(
            trading_date=start.date(),
            source_available_time=source_available,
        ),
        interval=exact,
        lineage=_lineage(),
    )

    assert bar.interval_start == exact.interval_start.astimezone(UTC)
    assert bar.event_time == exact.interval_end.astimezone(UTC)
    assert bar.calendar_snapshot_id == _digest("9")


def test_duplicate_canonical_key_with_different_value_is_quarantined() -> None:
    first = normalize_bar(_input(), interval=_interval(), lineage=_lineage())
    conflicting = replace(first, close=Decimal("10.51"))

    with pytest.raises(CanonicalQuarantineError, match="DUPLICATE_CONFLICT"):
        validate_canonical_observations((first, conflicting))

    assert validate_canonical_observations((first, first)) == (first,)


def test_canonical_validator_rechecks_interval_and_vintage_identity() -> None:
    first = normalize_bar(_input(), interval=_interval(), lineage=_lineage())

    with pytest.raises(CanonicalQuarantineError, match="INTERVAL"):
        validate_canonical_observations(
            (replace(first, event_time=first.event_time - timedelta(seconds=1)),)
        )
    with pytest.raises(CanonicalQuarantineError, match="VINTAGE_ID"):
        validate_canonical_observations((replace(first, vintage_id=_digest("8")),))


def test_source_revision_creates_new_vintage_that_supersedes_old_value() -> None:
    first = normalize_bar(_input(), interval=_interval(), lineage=_lineage())
    revision_time = RECEIVED + timedelta(days=1)
    revised = normalize_bar(
        _input(
            close=Decimal("10.51"),
            observed_received_time=revision_time,
            recorded_time=revision_time + timedelta(seconds=1),
            source_revision_time=revision_time - timedelta(minutes=1),
            source_revision_id="vendor-revision-2",
            vintage_proven_time=revision_time - timedelta(minutes=1),
            vintage_kind=VintageKind.SOURCE_VERSIONED,
            availability_basis=AvailabilityBasis.SOURCE_REVISION,
        ),
        interval=_interval(),
        lineage=replace(_lineage(), row_index=8),
        supersedes_vintage_id=first.vintage_id,
    )

    assert revised.vintage_id != first.vintage_id
    assert revised.supersedes_vintage_id == first.vintage_id
    assert validate_canonical_observations((first, revised)) == (first, revised)


def test_canonical_arrow_schema_freezes_fields_nullability_and_metadata() -> None:
    assert CANONICAL_BAR_SCHEMA.metadata == {b"schema_version": b"astraquant.canonical-bar/v1"}
    assert CANONICAL_BAR_SCHEMA.names == [
        "schema_version",
        "instrument_id",
        "frequency",
        "trading_date",
        "interval_start",
        "interval_end",
        "event_time",
        "source_available_time",
        "observed_received_time",
        "recorded_time",
        "first_received_time",
        "source_revision_time",
        "source_revision_id",
        "vintage_proven_time",
        "vintage_kind",
        "availability_basis",
        "calendar_snapshot_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "open_interest",
        "settlement",
        "adjustment",
        "units",
        "value_hash",
        "vintage_id",
        "supersedes_vintage_id",
        "capture_id",
        "chunk_id",
        "row_index",
    ]
    nullable = {field.name for field in CANONICAL_BAR_SCHEMA if field.nullable}
    assert nullable == {
        "source_revision_time",
        "source_revision_id",
        "turnover",
        "open_interest",
        "settlement",
        "supersedes_vintage_id",
    }
    assert CANONICAL_BAR_SCHEMA.field("open").type == pa.decimal128(24, 8)
    assert CANONICAL_BAR_SCHEMA.field("volume").type == pa.decimal128(30, 8)


def test_canonical_arrow_round_trip_preserves_observation_and_digests() -> None:
    bar = normalize_bar(_input(), interval=_interval(), lineage=_lineage())

    table = canonical_bars_to_table((bar,))
    restored = table_to_canonical_bars(table)

    assert table.schema == CANONICAL_BAR_SCHEMA
    assert restored == (bar,)
    assert restored[0].value_hash == bar.value_hash
    assert restored[0].vintage_id == bar.vintage_id


def test_canonical_arrow_reader_rejects_schema_or_metadata_drift() -> None:
    bar = normalize_bar(_input(), interval=_interval(), lineage=_lineage())
    table = canonical_bars_to_table((bar,))
    drifted = table.replace_schema_metadata({b"schema_version": b"unexpected"})

    with pytest.raises(ValueError, match="canonical bar schema"):
        table_to_canonical_bars(drifted)

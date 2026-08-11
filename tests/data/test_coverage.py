from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_data.canonical import (
    CanonicalBarInput,
    CanonicalBarObservation,
    CaptureRowLineage,
    normalize_bar,
)
from astraquant_data.coverage import (
    CaptureChunkCoverage,
    CoveragePlan,
    CoverageReason,
    CoverageRequirement,
    InstrumentLifecycle,
    ReferenceCoverageProof,
    ReferenceSubject,
    evaluate_coverage,
)
from astraquant_domain import (
    Adjustment,
    AvailabilityBasis,
    BarFrequency,
    InstrumentId,
    ObservationInterval,
    VintageKind,
)

CALENDAR = f"sha256:{'1' * 64}"
POLICY = f"sha256:{'2' * 64}"
LIFECYCLE = f"sha256:{'3' * 64}"


def _requirement(day: int, *, symbol: str = "600000.SSE") -> CoverageRequirement:
    return CoverageRequirement(
        instrument_id=InstrumentId.parse(symbol),
        frequency=BarFrequency.DAY,
        trading_date=date(2026, 8, day),
        interval_start=datetime(2026, 8, day, 1, 30, tzinfo=UTC),
        interval_end=datetime(2026, 8, day, 7, 0, tzinfo=UTC),
        calendar_snapshot_id=CALENDAR,
    )


def _observation(
    requirement: CoverageRequirement, *, close: str = "10.5"
) -> CanonicalBarObservation:
    received = datetime(2026, 8, 20, tzinfo=UTC)
    return normalize_bar(
        CanonicalBarInput(
            instrument_id=requirement.instrument_id,
            frequency=requirement.frequency,
            trading_date=requirement.trading_date,
            source_available_time=requirement.interval_end + timedelta(minutes=1),
            observed_received_time=received,
            recorded_time=received + timedelta(seconds=1),
            first_received_time=received,
            source_revision_time=None,
            source_revision_id=None,
            vintage_proven_time=received,
            vintage_kind=VintageKind.AS_DELIVERED_UNVERSIONED,
            availability_basis=AvailabilityBasis.SESSION_CLOSE,
            open=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal(close),
            volume=Decimal("1000"),
            turnover=Decimal("10500"),
            open_interest=None,
            settlement=None,
            adjustment=Adjustment.NONE,
            source_adjustment=Adjustment.NONE,
            units=("price=CNY", "turnover=CNY", "volume=share"),
        ),
        interval=ObservationInterval(
            interval_start=requirement.interval_start,
            interval_end=requirement.interval_end,
            event_time=requirement.interval_end,
            calendar_snapshot_id=requirement.calendar_snapshot_id,
        ),
        lineage=CaptureRowLineage(
            capture_id=f"sha256:{'4' * 64}",
            chunk_id=f"sha256:{'5' * 64}",
            row_index=requirement.trading_date.day,
        ),
    )


def _lifecycle(*, symbol: str = "600000.SSE") -> InstrumentLifecycle:
    return InstrumentLifecycle(
        instrument_id=InstrumentId.parse(symbol),
        listed_on=date(2026, 8, 10),
        delisted_on=date(2026, 8, 12),
        evidence_digest=LIFECYCLE,
    )


def _chunk(expected: int, received: int | None = None) -> CaptureChunkCoverage:
    return CaptureChunkCoverage(
        sequence=0,
        expected_rows=expected,
        received_rows=expected if received is None else received,
        qualified_row_limit=5_000,
        sealed=True,
    )


def _references(
    *, incomplete: ReferenceSubject | None = None
) -> tuple[ReferenceCoverageProof, ...]:
    return tuple(
        ReferenceCoverageProof(
            subject=subject,
            covered_from=date(2026, 8, 1),
            covered_to=date(2026, 8, 31),
            evidence_digest=f"sha256:{character * 64}",
            complete=subject is not incomplete,
        )
        for subject, character in zip(ReferenceSubject, ("6", "7", "8"), strict=True)
    )


def test_denominator_uses_exact_lifecycle_and_excludes_pre_post_listing_dates() -> None:
    plan = CoveragePlan.create(
        lifecycles=(_lifecycle(),),
        candidate_requirements=tuple(_requirement(day) for day in range(9, 14)),
        chunks=(_chunk(3),),
        reference_proofs=_references(),
        coverage_policy_id=POLICY,
    )

    assert tuple(item.trading_date.day for item in plan.requirements) == (10, 11, 12)


def test_plan_rejects_current_universe_inference_and_missing_evidence() -> None:
    with pytest.raises(ValueError, match="lifecycle evidence"):
        CoveragePlan.create(
            lifecycles=(_lifecycle(),),
            candidate_requirements=(_requirement(10, symbol="000001.SZSE"),),
            chunks=(_chunk(1),),
            reference_proofs=_references(),
            coverage_policy_id=POLICY,
        )
    with pytest.raises(ValueError, match="evidence_digest"):
        InstrumentLifecycle(
            instrument_id=InstrumentId.parse("600000.SSE"),
            listed_on=date(2026, 8, 10),
            delisted_on=None,
            evidence_digest="",
        )


def test_missing_and_unexpected_intervals_are_explicit_coverage_gaps() -> None:
    expected = (_requirement(10), _requirement(11))
    plan = CoveragePlan.create(
        lifecycles=(_lifecycle(),),
        candidate_requirements=expected,
        chunks=(_chunk(2),),
        reference_proofs=_references(),
        coverage_policy_id=POLICY,
    )

    report = evaluate_coverage((_observation(expected[0]), _observation(_requirement(12))), plan)

    assert report.expected_count == 2
    assert report.observed_count == 1
    assert report.missing_count == 1
    assert report.unexpected_count == 1
    assert report.coverage_ratio == Decimal("0.5")
    assert report.reasons == (
        CoverageReason.MISSING_OBSERVATION,
        CoverageReason.UNEXPECTED_OBSERVATION,
    )
    assert not report.complete


@pytest.mark.parametrize(
    ("chunk", "reason"),
    [
        (
            CaptureChunkCoverage(0, 10, 10, 5_000, False),
            CoverageReason.PAGINATION_INCOMPLETE,
        ),
        (
            CaptureChunkCoverage(0, 6_000, 5_000, 5_000, True),
            CoverageReason.SILENT_ROW_LIMIT_TRUNCATION,
        ),
        (
            CaptureChunkCoverage(0, 10, 9, 5_000, True),
            CoverageReason.ROW_COUNT_MISMATCH,
        ),
    ],
)
def test_chunk_proof_faults_cannot_silently_pass(
    chunk: CaptureChunkCoverage, reason: CoverageReason
) -> None:
    requirement = _requirement(10)
    plan = CoveragePlan.create(
        lifecycles=(_lifecycle(),),
        candidate_requirements=(requirement,),
        chunks=(chunk,),
        reference_proofs=_references(),
        coverage_policy_id=POLICY,
    )

    report = evaluate_coverage((_observation(requirement),), plan)

    assert reason in report.reasons
    assert not report.complete


def test_multiple_vintages_of_one_interval_count_as_one_covered_requirement() -> None:
    requirement = _requirement(10)
    first = _observation(requirement)
    revision_time = first.recorded_time + timedelta(days=1)
    revised_input = CanonicalBarInput(
        instrument_id=first.instrument_id,
        frequency=first.frequency,
        trading_date=first.trading_date,
        source_available_time=first.source_available_time,
        observed_received_time=revision_time,
        recorded_time=revision_time + timedelta(seconds=1),
        first_received_time=first.first_received_time,
        source_revision_time=revision_time,
        source_revision_id="revision-2",
        vintage_proven_time=revision_time,
        vintage_kind=VintageKind.SOURCE_VERSIONED,
        availability_basis=AvailabilityBasis.SOURCE_REVISION,
        open=first.open,
        high=first.high,
        low=first.low,
        close=Decimal("10.6"),
        volume=first.volume,
        turnover=first.turnover,
        open_interest=None,
        settlement=None,
        adjustment=Adjustment.NONE,
        source_adjustment=Adjustment.NONE,
        units=first.units,
    )
    revised = normalize_bar(
        revised_input,
        interval=ObservationInterval(
            interval_start=first.interval_start,
            interval_end=first.interval_end,
            event_time=first.event_time,
            calendar_snapshot_id=first.calendar_snapshot_id,
        ),
        lineage=CaptureRowLineage(
            capture_id=f"sha256:{'6' * 64}",
            chunk_id=f"sha256:{'7' * 64}",
            row_index=1,
        ),
        supersedes_vintage_id=first.vintage_id,
    )
    plan = CoveragePlan.create(
        lifecycles=(_lifecycle(),),
        candidate_requirements=(requirement,),
        chunks=(_chunk(1),),
        reference_proofs=_references(),
        coverage_policy_id=POLICY,
    )

    report = evaluate_coverage((first, revised), plan)

    assert report.observed_count == 1
    assert report.coverage_ratio == Decimal("1")
    assert report.complete


def test_reference_proofs_are_required_for_universe_status_and_actions() -> None:
    requirement = _requirement(10)
    with pytest.raises(ValueError, match="reference proofs"):
        CoveragePlan.create(
            lifecycles=(_lifecycle(),),
            candidate_requirements=(requirement,),
            chunks=(_chunk(1),),
            reference_proofs=_references()[:-1],
            coverage_policy_id=POLICY,
        )


@pytest.mark.parametrize(
    ("subject", "reason"),
    [
        (ReferenceSubject.UNIVERSE, CoverageReason.UNIVERSE_REFERENCE_GAP),
        (ReferenceSubject.STATUS, CoverageReason.STATUS_REFERENCE_GAP),
        (
            ReferenceSubject.CORPORATE_ACTION,
            CoverageReason.CORPORATE_ACTION_REFERENCE_GAP,
        ),
    ],
)
def test_incomplete_reference_coverage_is_never_silently_complete(
    subject: ReferenceSubject, reason: CoverageReason
) -> None:
    requirement = _requirement(10)
    plan = CoveragePlan.create(
        lifecycles=(_lifecycle(),),
        candidate_requirements=(requirement,),
        chunks=(_chunk(1),),
        reference_proofs=_references(incomplete=subject),
        coverage_policy_id=POLICY,
    )

    report = evaluate_coverage((_observation(requirement),), plan)

    assert reason in report.reasons
    assert not report.complete

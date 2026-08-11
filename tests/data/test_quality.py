from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_data.canonical import (
    CanonicalBarInput,
    CanonicalBarObservation,
    CaptureRowLineage,
    normalize_bar,
)
from astraquant_data.coverage import CoverageReason, CoverageReport
from astraquant_data.quality import (
    AggregationResult,
    DataRole,
    FormalGateState,
    FormalQualityCode,
    FormalQualityPolicy,
    QualityCode,
    QualitySeverity,
    check_bar_aggregation,
    evaluate_bars,
    evaluate_formal_quality,
)
from astraquant_domain import (
    Adjustment,
    AvailabilityBasis,
    BarFrequency,
    InstrumentId,
    ObservationInterval,
    VintageKind,
)

from .factories import make_bar

FETCHED_AT = datetime(2026, 7, 30, tzinfo=UTC)


def test_duplicate_and_unexpected_date_issues_are_stable_and_machine_readable() -> None:
    first = make_bar(day=24, availability_estimated=False)
    report = evaluate_bars(
        [
            first,
            first,
            make_bar(day=28, availability_estimated=False),
        ],
        expected_trading_dates={date(2026, 7, 24)},
        source_fetched_at=FETCHED_AT,
    )

    assert [(issue.code, issue.severity) for issue in report.issues] == [
        (QualityCode.DUPLICATE_KEY, QualitySeverity.ERROR),
        (QualityCode.UNEXPECTED_TRADING_DATE, QualitySeverity.WARNING),
    ]
    assert report.publishable is False


def test_a_later_revision_of_the_same_event_is_not_an_exact_duplicate() -> None:
    first = make_bar(day=24, availability_estimated=False)
    revised = make_bar(
        day=24,
        close="10.80",
        available_time=first.available_time + timedelta(hours=1),
        availability_estimated=False,
    )

    report = evaluate_bars(
        [first, revised],
        expected_trading_dates={date(2026, 7, 24)},
        source_fetched_at=FETCHED_AT,
    )

    assert QualityCode.DUPLICATE_KEY not in {issue.code for issue in report.issues}
    assert report.publishable


def test_information_available_after_fetch_time_is_rejected() -> None:
    bar = make_bar(available_time=FETCHED_AT + timedelta(seconds=1))

    report = evaluate_bars(
        [bar],
        expected_trading_dates={date(2026, 7, 24)},
        source_fetched_at=FETCHED_AT,
    )

    assert QualityCode.AVAILABLE_AFTER_SOURCE_FETCH in {issue.code for issue in report.issues}
    assert report.publishable is False


def test_estimated_availability_is_visible_but_publishable() -> None:
    report = evaluate_bars(
        [make_bar()],
        expected_trading_dates={date(2026, 7, 24)},
        source_fetched_at=FETCHED_AT,
    )

    assert report.issues[0].code is QualityCode.ESTIMATED_AVAILABILITY
    assert report.publishable


def _formal_policy(*, research_minimum: str = "0.95") -> FormalQualityPolicy:
    return FormalQualityPolicy(
        policy_version="formal-quality/v1",
        policy_source="docs/superpowers/specs/2026-08-10-quant-core-open-source-architecture-design.md#6.6",
        policy_source_digest=f"sha256:{'9' * 64}",
        raw_execution_minimum=Decimal("1"),
        research_minimum=Decimal(research_minimum),
    )


def _coverage(*, ratio: str = "1", reasons: tuple[CoverageReason, ...] = ()) -> CoverageReport:
    expected = 100
    observed = int(Decimal(ratio) * expected)
    return CoverageReport(
        coverage_policy_id=f"sha256:{'1' * 64}",
        expected_count=expected,
        observed_count=observed,
        missing_count=expected - observed,
        unexpected_count=0,
        coverage_ratio=Decimal(ratio),
        reasons=reasons,
        missing_samples=("missing",) if observed < expected else (),
        unexpected_samples=(),
    )


def _canonical_bar(
    *,
    interval_start: datetime = datetime(2026, 8, 10, 1, 30, tzinfo=UTC),
    interval_end: datetime = datetime(2026, 8, 10, 7, 0, tzinfo=UTC),
    frequency: BarFrequency = BarFrequency.DAY,
    open_value: str = "10",
    high: str = "11",
    low: str = "9",
    close: str = "10.5",
    volume: str = "1000",
    turnover: str = "10500",
    row_index: int = 0,
) -> CanonicalBarObservation:
    received = datetime(2026, 8, 11, tzinfo=UTC)
    return normalize_bar(
        CanonicalBarInput(
            instrument_id=InstrumentId.parse("600000.SSE"),
            frequency=frequency,
            trading_date=date(2026, 8, 10),
            source_available_time=interval_end + timedelta(minutes=1),
            observed_received_time=received,
            recorded_time=received + timedelta(seconds=1),
            first_received_time=received,
            source_revision_time=None,
            source_revision_id=None,
            vintage_proven_time=received,
            vintage_kind=VintageKind.AS_DELIVERED_UNVERSIONED,
            availability_basis=AvailabilityBasis.SESSION_CLOSE,
            open=Decimal(open_value),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=Decimal(volume),
            turnover=Decimal(turnover),
            open_interest=None,
            settlement=None,
            adjustment=Adjustment.NONE,
            source_adjustment=Adjustment.NONE,
            units=("price=CNY", "turnover=CNY", "volume=share"),
        ),
        interval=ObservationInterval(
            interval_start=interval_start,
            interval_end=interval_end,
            event_time=interval_end,
            calendar_snapshot_id=f"sha256:{'2' * 64}",
        ),
        lineage=CaptureRowLineage(
            capture_id=f"sha256:{'3' * 64}",
            chunk_id=f"sha256:{'4' * 64}",
            row_index=row_index,
        ),
    )


def test_formal_policy_digest_binds_version_source_and_thresholds() -> None:
    first = _formal_policy(research_minimum="0.95")
    same = _formal_policy(research_minimum="0.95")
    stricter = _formal_policy(research_minimum="0.99")

    assert first.policy_digest == same.policy_digest
    assert first.policy_digest != stricter.policy_digest
    assert first.policy_digest.startswith("sha256:")

    with pytest.raises(ValueError, match="policy_source_digest"):
        FormalQualityPolicy(
            policy_version="formal-quality/v1",
            policy_source="official-rule",
            policy_source_digest="unverified",
            raw_execution_minimum=Decimal("1"),
            research_minimum=Decimal("0.95"),
        )


def test_formal_gate_passes_only_without_errors_or_warnings() -> None:
    report = evaluate_formal_quality(
        (_canonical_bar(),),
        coverage=_coverage(),
        role=DataRole.RAW_EXECUTION,
        policy=_formal_policy(),
    )

    assert report.state is FormalGateState.PASS
    assert report.issues == ()
    assert report.publishable


def test_raw_requires_complete_coverage_but_research_gap_is_incomplete() -> None:
    coverage = _coverage(ratio="0.98", reasons=(CoverageReason.MISSING_OBSERVATION,))

    raw = evaluate_formal_quality(
        (_canonical_bar(),),
        coverage=coverage,
        role=DataRole.RAW_EXECUTION,
        policy=_formal_policy(),
    )
    research = evaluate_formal_quality(
        (_canonical_bar(),),
        coverage=coverage,
        role=DataRole.RESEARCH,
        policy=_formal_policy(research_minimum="0.95"),
    )

    assert raw.state is FormalGateState.QUARANTINE
    assert not raw.publishable
    assert research.state is FormalGateState.INCOMPLETE
    assert research.publishable
    assert research.issues[0].severity is QualitySeverity.WARNING


def test_research_below_frozen_threshold_and_silent_truncation_quarantine() -> None:
    below = evaluate_formal_quality(
        (_canonical_bar(),),
        coverage=_coverage(ratio="0.98", reasons=(CoverageReason.MISSING_OBSERVATION,)),
        role=DataRole.RESEARCH,
        policy=_formal_policy(research_minimum="0.99"),
    )
    truncated = evaluate_formal_quality(
        (_canonical_bar(),),
        coverage=_coverage(reasons=(CoverageReason.SILENT_ROW_LIMIT_TRUNCATION,)),
        role=DataRole.RESEARCH,
        policy=_formal_policy(),
    )

    assert below.state is FormalGateState.QUARANTINE
    assert truncated.state is FormalGateState.QUARANTINE
    assert truncated.issues[0].code is FormalQualityCode.SILENT_ROW_LIMIT_TRUNCATION


def test_canonical_conflict_is_converted_to_quarantine_issue() -> None:
    valid = _canonical_bar()
    tampered = replace(valid, close=Decimal("10.6"))

    report = evaluate_formal_quality(
        (tampered,),
        coverage=_coverage(),
        role=DataRole.RAW_EXECUTION,
        policy=_formal_policy(),
    )

    assert report.state is FormalGateState.QUARANTINE
    assert report.issues[0].code is FormalQualityCode.CANONICAL_INVALID


def test_minute_to_daily_aggregation_is_exact_and_mismatch_quarantines() -> None:
    first = _canonical_bar(
        interval_end=datetime(2026, 8, 10, 1, 31, tzinfo=UTC),
        frequency=BarFrequency.MINUTE,
        close="10.4",
        volume="400",
        turnover="4000",
        row_index=1,
    )
    second = _canonical_bar(
        interval_start=datetime(2026, 8, 10, 1, 31, tzinfo=UTC),
        interval_end=datetime(2026, 8, 10, 1, 32, tzinfo=UTC),
        frequency=BarFrequency.MINUTE,
        open_value="10.4",
        high="10.8",
        low="10",
        volume="600",
        turnover="6500",
        row_index=2,
    )
    valid = check_bar_aggregation(_canonical_bar(), (first, second))
    mismatch = check_bar_aggregation(_canonical_bar(volume="1001"), (first, second))

    assert valid == AggregationResult(valid=True, mismatch_fields=(), child_count=2)
    assert not mismatch.valid
    assert mismatch.mismatch_fields == ("volume",)

    report = evaluate_formal_quality(
        (_canonical_bar(),),
        coverage=_coverage(),
        role=DataRole.RAW_EXECUTION,
        policy=_formal_policy(),
        aggregation_results=(mismatch,),
    )
    assert report.state is FormalGateState.QUARANTINE
    assert report.issues[0].code is FormalQualityCode.AGGREGATION_MISMATCH

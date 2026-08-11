"""Deterministic, machine-readable market-data quality reports."""

import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from astraquant_domain import Bar, BarFrequency
from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

from .canonical import (
    CanonicalBarObservation,
    CanonicalQuarantineError,
    validate_canonical_observations,
)
from .coverage import CoverageReason, CoverageReport


class QualitySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class QualityCode(StrEnum):
    EMPTY_DATASET = "EMPTY_DATASET"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    NON_MONOTONIC_TIME = "NON_MONOTONIC_TIME"
    AVAILABLE_AFTER_SOURCE_FETCH = "AVAILABLE_AFTER_SOURCE_FETCH"
    UNEXPECTED_TRADING_DATE = "UNEXPECTED_TRADING_DATE"
    ESTIMATED_AVAILABILITY = "ESTIMATED_AVAILABILITY"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: QualityCode
    severity: QualitySeverity
    count: int
    sample_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityReport:
    row_count: int
    issues: tuple[QualityIssue, ...]

    @property
    def publishable(self) -> bool:
        return all(issue.severity is not QualitySeverity.ERROR for issue in self.issues)


def evaluate_bars(
    bars: Iterable[Bar],
    *,
    expected_trading_dates: set[date],
    source_fetched_at: datetime,
) -> QualityReport:
    if source_fetched_at.tzinfo is None or source_fetched_at.utcoffset() is None:
        raise ValueError("source_fetched_at must be timezone-aware")
    rows = tuple(bars)
    findings: dict[QualityCode, list[str]] = defaultdict(list)
    if not rows:
        findings[QualityCode.EMPTY_DATASET].append("dataset")

    exact_keys = [
        (
            str(bar.instrument_id),
            bar.frequency.value,
            bar.event_time.isoformat(),
            bar.available_time.isoformat(),
        )
        for bar in rows
    ]
    for key, count in Counter(exact_keys).items():
        if count > 1:
            findings[QualityCode.DUPLICATE_KEY].extend(["|".join(key)] * (count - 1))

    groups: dict[tuple[str, str], list[Bar]] = defaultdict(list)
    for bar in rows:
        groups[(str(bar.instrument_id), bar.frequency.value)].append(bar)
    for group in groups.values():
        previous_available: datetime | None = None
        previous_event: datetime | None = None
        for bar in sorted(group, key=lambda item: (item.event_time, item.available_time)):
            if (
                previous_event is not None
                and bar.event_time > previous_event
                and previous_available is not None
                and bar.available_time < previous_available
            ):
                findings[QualityCode.NON_MONOTONIC_TIME].append(_bar_key(bar))
            previous_event = bar.event_time
            previous_available = bar.available_time

    for bar in rows:
        if bar.available_time > source_fetched_at:
            findings[QualityCode.AVAILABLE_AFTER_SOURCE_FETCH].append(_bar_key(bar))
        if bar.trading_date not in expected_trading_dates:
            findings[QualityCode.UNEXPECTED_TRADING_DATE].append(_bar_key(bar))
        if bar.availability_estimated:
            findings[QualityCode.ESTIMATED_AVAILABILITY].append(_bar_key(bar))

    severity = {
        QualityCode.EMPTY_DATASET: QualitySeverity.ERROR,
        QualityCode.DUPLICATE_KEY: QualitySeverity.ERROR,
        QualityCode.NON_MONOTONIC_TIME: QualitySeverity.ERROR,
        QualityCode.AVAILABLE_AFTER_SOURCE_FETCH: QualitySeverity.ERROR,
        QualityCode.UNEXPECTED_TRADING_DATE: QualitySeverity.WARNING,
        QualityCode.ESTIMATED_AVAILABILITY: QualitySeverity.WARNING,
    }
    issues = tuple(
        QualityIssue(
            code=code,
            severity=severity[code],
            count=len(findings[code]),
            sample_keys=tuple(findings[code][:5]),
        )
        for code in QualityCode
        if findings[code]
    )
    return QualityReport(row_count=len(rows), issues=issues)


def _bar_key(bar: Bar) -> str:
    return "|".join(
        (
            str(bar.instrument_id),
            bar.frequency.value,
            bar.event_time.isoformat(),
            bar.available_time.isoformat(),
        )
    )


class DataRole(StrEnum):
    RAW_EXECUTION = "RAW_EXECUTION"
    RESEARCH = "RESEARCH"


class FormalGateState(StrEnum):
    PASS = "PASS"
    INCOMPLETE = "INCOMPLETE"
    QUARANTINE = "QUARANTINE"


class FormalQualityCode(StrEnum):
    CANONICAL_INVALID = "CANONICAL_INVALID"
    AGGREGATION_MISMATCH = "AGGREGATION_MISMATCH"
    COVERAGE_GAP = "COVERAGE_GAP"
    UNEXPECTED_INTERVAL = "UNEXPECTED_INTERVAL"
    UNIVERSE_REFERENCE_GAP = "UNIVERSE_REFERENCE_GAP"
    STATUS_REFERENCE_GAP = "STATUS_REFERENCE_GAP"
    CORPORATE_ACTION_REFERENCE_GAP = "CORPORATE_ACTION_REFERENCE_GAP"
    PAGINATION_INCOMPLETE = "PAGINATION_INCOMPLETE"
    SILENT_ROW_LIMIT_TRUNCATION = "SILENT_ROW_LIMIT_TRUNCATION"
    ROW_COUNT_MISMATCH = "ROW_COUNT_MISMATCH"


@dataclass(frozen=True, slots=True)
class FormalQualityPolicy:
    policy_version: str
    policy_source: str
    policy_source_digest: str
    raw_execution_minimum: Decimal
    research_minimum: Decimal

    def __post_init__(self) -> None:
        if not self.policy_version or self.policy_version != self.policy_version.strip():
            raise ValueError("policy_version must be non-empty canonical text")
        if not self.policy_source or self.policy_source != self.policy_source.strip():
            raise ValueError("policy_source must be non-empty canonical text")
        try:
            source_digest = validate_digest("policy_source_digest", self.policy_source_digest)
        except ValueError as error:
            raise ValueError("policy_source_digest must be a valid digest") from error
        if source_digest == f"sha256:{'0' * 64}":
            raise ValueError("policy_source_digest must not be a sentinel digest")
        object.__setattr__(self, "policy_source_digest", source_digest)
        if self.raw_execution_minimum != Decimal(1):
            raise ValueError("RAW_EXECUTION minimum coverage must equal 1")
        if not Decimal(0) <= self.research_minimum <= Decimal(1):
            raise ValueError("research_minimum must be between 0 and 1")

    @property
    def policy_digest(self) -> str:
        payload = {
            "policy_version": self.policy_version,
            "policy_source": self.policy_source,
            "policy_source_digest": self.policy_source_digest,
            "raw_execution_minimum": str(self.raw_execution_minimum),
            "research_minimum": str(self.research_minimum),
        }
        return f"sha256:{hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}"


@dataclass(frozen=True, slots=True)
class FormalQualityIssue:
    code: FormalQualityCode
    severity: QualitySeverity
    count: int
    sample_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AggregationResult:
    valid: bool
    mismatch_fields: tuple[str, ...]
    child_count: int


def check_bar_aggregation(
    parent: CanonicalBarObservation,
    children: tuple[CanonicalBarObservation, ...] | list[CanonicalBarObservation],
) -> AggregationResult:
    exact_children = tuple(children)
    if not exact_children:
        return AggregationResult(False, ("children",), 0)
    try:
        validate_canonical_observations((parent,))
        validated = validate_canonical_observations(exact_children)
    except CanonicalQuarantineError:
        return AggregationResult(False, ("canonical",), len(exact_children))
    ordered = tuple(sorted(validated, key=lambda item: item.interval_start))
    structure_valid = all(
        item.instrument_id == parent.instrument_id
        and item.trading_date == parent.trading_date
        and item.frequency is BarFrequency.MINUTE
        and parent.interval_start <= item.interval_start < item.interval_end <= parent.interval_end
        for item in ordered
    ) and all(
        previous.interval_end <= current.interval_start for previous, current in pairwise(ordered)
    )
    if parent.frequency is not BarFrequency.DAY or not structure_valid:
        return AggregationResult(False, ("structure",), len(ordered))
    expected = {
        "open": ordered[0].open,
        "high": max(item.high for item in ordered),
        "low": min(item.low for item in ordered),
        "close": ordered[-1].close,
        "volume": sum((item.volume for item in ordered), Decimal(0)),
        "turnover": (
            None
            if any(item.turnover is None for item in ordered)
            else sum(
                (item.turnover for item in ordered if item.turnover is not None),
                Decimal(0),
            )
        ),
    }
    mismatches = tuple(
        field
        for field, expected_value in expected.items()
        if getattr(parent, field) != expected_value
    )
    return AggregationResult(not mismatches, mismatches, len(ordered))


@dataclass(frozen=True, slots=True)
class FormalQualityReport:
    policy_digest: str
    coverage_policy_id: str
    role: DataRole
    state: FormalGateState
    row_count: int
    issues: tuple[FormalQualityIssue, ...]

    @property
    def publishable(self) -> bool:
        return self.state is not FormalGateState.QUARANTINE


_COVERAGE_CODES = {
    CoverageReason.MISSING_OBSERVATION: FormalQualityCode.COVERAGE_GAP,
    CoverageReason.UNEXPECTED_OBSERVATION: FormalQualityCode.UNEXPECTED_INTERVAL,
    CoverageReason.UNIVERSE_REFERENCE_GAP: FormalQualityCode.UNIVERSE_REFERENCE_GAP,
    CoverageReason.STATUS_REFERENCE_GAP: FormalQualityCode.STATUS_REFERENCE_GAP,
    CoverageReason.CORPORATE_ACTION_REFERENCE_GAP: (
        FormalQualityCode.CORPORATE_ACTION_REFERENCE_GAP
    ),
    CoverageReason.PAGINATION_INCOMPLETE: FormalQualityCode.PAGINATION_INCOMPLETE,
    CoverageReason.SILENT_ROW_LIMIT_TRUNCATION: (FormalQualityCode.SILENT_ROW_LIMIT_TRUNCATION),
    CoverageReason.ROW_COUNT_MISMATCH: FormalQualityCode.ROW_COUNT_MISMATCH,
}


def evaluate_formal_quality(
    observations: tuple[CanonicalBarObservation, ...] | list[CanonicalBarObservation],
    *,
    coverage: CoverageReport,
    role: DataRole,
    policy: FormalQualityPolicy,
    aggregation_results: tuple[AggregationResult, ...] | list[AggregationResult] = (),
) -> FormalQualityReport:
    issues: list[FormalQualityIssue] = []
    try:
        validated = validate_canonical_observations(observations)
        row_count = len(validated)
    except CanonicalQuarantineError as error:
        row_count = len(observations)
        issues.append(
            FormalQualityIssue(
                code=FormalQualityCode.CANONICAL_INVALID,
                severity=QualitySeverity.ERROR,
                count=1,
                sample_keys=(error.code,),
            )
        )

    invalid_aggregations = tuple(result for result in aggregation_results if not result.valid)
    if invalid_aggregations:
        issues.append(
            FormalQualityIssue(
                code=FormalQualityCode.AGGREGATION_MISMATCH,
                severity=QualitySeverity.ERROR,
                count=len(invalid_aggregations),
                sample_keys=tuple(
                    ",".join(result.mismatch_fields) for result in invalid_aggregations[:5]
                ),
            )
        )

    minimum = (
        policy.raw_execution_minimum if role is DataRole.RAW_EXECUTION else policy.research_minimum
    )
    coverage_reasons = set(coverage.reasons)
    if coverage.coverage_ratio < minimum:
        coverage_reasons.add(CoverageReason.MISSING_OBSERVATION)
    for reason in CoverageReason:
        if reason not in coverage_reasons:
            continue
        if reason is CoverageReason.MISSING_OBSERVATION:
            severity = (
                QualitySeverity.ERROR
                if coverage.coverage_ratio < minimum
                else QualitySeverity.WARNING
            )
            count = coverage.missing_count
            samples = coverage.missing_samples
        elif reason is CoverageReason.UNEXPECTED_OBSERVATION:
            severity = QualitySeverity.ERROR
            count = coverage.unexpected_count
            samples = coverage.unexpected_samples
        else:
            severity = QualitySeverity.ERROR
            count = 1
            samples = (reason.value,)
        issues.append(
            FormalQualityIssue(
                code=_COVERAGE_CODES[reason],
                severity=severity,
                count=count,
                sample_keys=samples,
            )
        )

    if any(item.severity is QualitySeverity.ERROR for item in issues):
        state = FormalGateState.QUARANTINE
    elif issues:
        state = FormalGateState.INCOMPLETE
    else:
        state = FormalGateState.PASS
    return FormalQualityReport(
        policy_digest=policy.policy_digest,
        coverage_policy_id=coverage.coverage_policy_id,
        role=role,
        state=state,
        row_count=row_count,
        issues=tuple(issues),
    )

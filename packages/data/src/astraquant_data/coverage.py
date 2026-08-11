"""Exact historical-lifecycle and capture-proof coverage accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from astraquant_data.canonical import (
    CanonicalBarObservation,
    validate_canonical_observations,
)
from astraquant_domain import BarFrequency, InstrumentId
from astraquant_domain.run_manifest import validate_digest


class CoverageReason(StrEnum):
    MISSING_OBSERVATION = "MISSING_OBSERVATION"
    UNEXPECTED_OBSERVATION = "UNEXPECTED_OBSERVATION"
    UNIVERSE_REFERENCE_GAP = "UNIVERSE_REFERENCE_GAP"
    STATUS_REFERENCE_GAP = "STATUS_REFERENCE_GAP"
    CORPORATE_ACTION_REFERENCE_GAP = "CORPORATE_ACTION_REFERENCE_GAP"
    PAGINATION_INCOMPLETE = "PAGINATION_INCOMPLETE"
    SILENT_ROW_LIMIT_TRUNCATION = "SILENT_ROW_LIMIT_TRUNCATION"
    ROW_COUNT_MISMATCH = "ROW_COUNT_MISMATCH"


def _evidence_digest(name: str, value: str) -> str:
    try:
        digest = validate_digest(name, value)
    except ValueError as error:
        raise ValueError(f"{name} must be a valid evidence digest") from error
    if digest == f"sha256:{'0' * 64}":
        raise ValueError(f"{name} must not be a sentinel digest")
    return digest


def _aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class InstrumentLifecycle:
    instrument_id: InstrumentId
    listed_on: date
    delisted_on: date | None
    evidence_digest: str

    def __post_init__(self) -> None:
        if self.delisted_on is not None and self.delisted_on < self.listed_on:
            raise ValueError("delisted_on must not precede listed_on")
        object.__setattr__(
            self,
            "evidence_digest",
            _evidence_digest("evidence_digest", self.evidence_digest),
        )

    def active_on(self, trading_date: date) -> bool:
        return self.listed_on <= trading_date and (
            self.delisted_on is None or trading_date <= self.delisted_on
        )


class ReferenceSubject(StrEnum):
    UNIVERSE = "UNIVERSE"
    STATUS = "STATUS"
    CORPORATE_ACTION = "CORPORATE_ACTION"


@dataclass(frozen=True, slots=True)
class ReferenceCoverageProof:
    subject: ReferenceSubject
    covered_from: date
    covered_to: date
    evidence_digest: str
    complete: bool

    def __post_init__(self) -> None:
        if self.covered_from > self.covered_to:
            raise ValueError("reference covered_from must not follow covered_to")
        object.__setattr__(
            self,
            "evidence_digest",
            _evidence_digest("reference evidence_digest", self.evidence_digest),
        )


@dataclass(frozen=True, slots=True)
class CoverageRequirement:
    instrument_id: InstrumentId
    frequency: BarFrequency
    trading_date: date
    interval_start: datetime
    interval_end: datetime
    calendar_snapshot_id: str

    def __post_init__(self) -> None:
        start = _aware("interval_start", self.interval_start)
        end = _aware("interval_end", self.interval_end)
        if start >= end:
            raise ValueError("interval_start must precede interval_end")
        object.__setattr__(self, "interval_start", start)
        object.__setattr__(self, "interval_end", end)
        object.__setattr__(
            self,
            "calendar_snapshot_id",
            _evidence_digest("calendar_snapshot_id", self.calendar_snapshot_id),
        )

    @property
    def logical_key(self) -> tuple[object, ...]:
        return (
            self.instrument_id,
            self.frequency,
            self.trading_date,
            self.interval_start,
            self.interval_end,
            self.calendar_snapshot_id,
        )

    def sample_key(self) -> str:
        return "|".join(
            (
                str(self.instrument_id),
                self.frequency.value,
                self.trading_date.isoformat(),
                self.interval_start.isoformat(),
                self.interval_end.isoformat(),
            )
        )


@dataclass(frozen=True, slots=True)
class CaptureChunkCoverage:
    sequence: int
    expected_rows: int
    received_rows: int
    qualified_row_limit: int
    sealed: bool

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("chunk sequence must be non-negative")
        if self.expected_rows < 0 or self.received_rows < 0:
            raise ValueError("chunk row counts must be non-negative")
        if self.qualified_row_limit <= 0:
            raise ValueError("qualified_row_limit must be positive")
        if self.received_rows > self.qualified_row_limit:
            raise ValueError("received rows exceed qualified row limit")


@dataclass(frozen=True, slots=True)
class CoveragePlan:
    lifecycles: tuple[InstrumentLifecycle, ...]
    requirements: tuple[CoverageRequirement, ...]
    chunks: tuple[CaptureChunkCoverage, ...]
    reference_proofs: tuple[ReferenceCoverageProof, ...]
    coverage_policy_id: str

    @classmethod
    def create(
        cls,
        *,
        lifecycles: tuple[InstrumentLifecycle, ...] | list[InstrumentLifecycle],
        candidate_requirements: tuple[CoverageRequirement, ...] | list[CoverageRequirement],
        chunks: tuple[CaptureChunkCoverage, ...] | list[CaptureChunkCoverage],
        reference_proofs: tuple[ReferenceCoverageProof, ...] | list[ReferenceCoverageProof],
        coverage_policy_id: str,
    ) -> Self:
        exact_lifecycles = tuple(lifecycles)
        by_instrument = {item.instrument_id: item for item in exact_lifecycles}
        if len(by_instrument) != len(exact_lifecycles):
            raise ValueError("instrument lifecycles must be unique")
        candidates = tuple(candidate_requirements)
        missing_evidence = sorted(
            {
                str(item.instrument_id)
                for item in candidates
                if item.instrument_id not in by_instrument
            }
        )
        if missing_evidence:
            raise ValueError("lifecycle evidence missing for: " + ", ".join(missing_evidence))
        requirements = tuple(
            sorted(
                (
                    item
                    for item in candidates
                    if by_instrument[item.instrument_id].active_on(item.trading_date)
                ),
                key=lambda item: item.logical_key,
            )
        )
        if not requirements:
            raise ValueError("coverage requirements must not be empty")
        keys = tuple(item.logical_key for item in requirements)
        if len(set(keys)) != len(keys):
            raise ValueError("coverage requirements must be unique")
        exact_chunks = tuple(sorted(chunks, key=lambda item: item.sequence))
        if not exact_chunks:
            raise ValueError("capture chunk coverage must not be empty")
        if tuple(item.sequence for item in exact_chunks) != tuple(range(len(exact_chunks))):
            raise ValueError("capture chunk sequences must be contiguous")
        proofs_by_subject = {item.subject: item for item in reference_proofs}
        if set(proofs_by_subject) != set(ReferenceSubject) or len(proofs_by_subject) != len(
            tuple(reference_proofs)
        ):
            raise ValueError(
                "reference proofs must contain exact universe, status and corporate-action subjects"
            )
        exact_proofs = tuple(proofs_by_subject[subject] for subject in ReferenceSubject)
        return cls(
            lifecycles=tuple(sorted(exact_lifecycles, key=lambda item: item.instrument_id)),
            requirements=requirements,
            chunks=exact_chunks,
            reference_proofs=exact_proofs,
            coverage_policy_id=_evidence_digest("coverage_policy_id", coverage_policy_id),
        )


@dataclass(frozen=True, slots=True)
class CoverageReport:
    coverage_policy_id: str
    expected_count: int
    observed_count: int
    missing_count: int
    unexpected_count: int
    coverage_ratio: Decimal
    reasons: tuple[CoverageReason, ...]
    missing_samples: tuple[str, ...]
    unexpected_samples: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.reasons


def _observation_key(value: CanonicalBarObservation) -> tuple[object, ...]:
    return (
        value.instrument_id,
        value.frequency,
        value.trading_date,
        value.interval_start,
        value.interval_end,
        value.calendar_snapshot_id,
    )


def evaluate_coverage(
    observations: tuple[CanonicalBarObservation, ...] | list[CanonicalBarObservation],
    plan: CoveragePlan,
) -> CoverageReport:
    validated = validate_canonical_observations(observations)
    expected_by_key = {item.logical_key: item for item in plan.requirements}
    actual_keys = {_observation_key(item) for item in validated}
    expected_keys = set(expected_by_key)
    missing = expected_keys - actual_keys
    unexpected = actual_keys - expected_keys
    reasons: set[CoverageReason] = set()
    if missing:
        reasons.add(CoverageReason.MISSING_OBSERVATION)
    if unexpected:
        reasons.add(CoverageReason.UNEXPECTED_OBSERVATION)
    for chunk in plan.chunks:
        if not chunk.sealed:
            reasons.add(CoverageReason.PAGINATION_INCOMPLETE)
        if (
            chunk.received_rows == chunk.qualified_row_limit
            and chunk.received_rows < chunk.expected_rows
        ):
            reasons.add(CoverageReason.SILENT_ROW_LIMIT_TRUNCATION)
        if chunk.received_rows != chunk.expected_rows:
            reasons.add(CoverageReason.ROW_COUNT_MISMATCH)
    required_from = min(item.trading_date for item in plan.requirements)
    required_to = max(item.trading_date for item in plan.requirements)
    reference_reason = {
        ReferenceSubject.UNIVERSE: CoverageReason.UNIVERSE_REFERENCE_GAP,
        ReferenceSubject.STATUS: CoverageReason.STATUS_REFERENCE_GAP,
        ReferenceSubject.CORPORATE_ACTION: (CoverageReason.CORPORATE_ACTION_REFERENCE_GAP),
    }
    for proof in plan.reference_proofs:
        if (
            not proof.complete
            or proof.covered_from > required_from
            or proof.covered_to < required_to
        ):
            reasons.add(reference_reason[proof.subject])
    observed = len(expected_keys & actual_keys)
    expected = len(expected_keys)
    return CoverageReport(
        coverage_policy_id=plan.coverage_policy_id,
        expected_count=expected,
        observed_count=observed,
        missing_count=len(missing),
        unexpected_count=len(unexpected),
        coverage_ratio=Decimal(observed) / Decimal(expected),
        reasons=tuple(reason for reason in CoverageReason if reason in reasons),
        missing_samples=tuple(expected_by_key[key].sample_key() for key in sorted(missing))[:5],
        unexpected_samples=tuple("|".join(str(part) for part in key) for key in sorted(unexpected))[
            :5
        ],
    )

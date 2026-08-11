"""Server-side admission and immutable resolution for formal captures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from astraquant_api.formal_data_schemas import (
    FormalCaptureRequest,
    ResolvedFormalCaptureCommand,
)
from astraquant_data.provider_identity import ProviderCapability
from astraquant_data.provider_qualification import ProviderQualificationTimeline
from astraquant_domain import BarFrequency, InstrumentId
from astraquant_domain.run_manifest import validate_digest


class FormalCaptureAdmissionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TrustedCoverage:
    sessions: tuple[date, ...]
    rows_per_session: int
    coverage_membership_digest: str
    policy_digest: str


class QualificationLookup(Protocol):
    def get_timeline_for_approval(
        self,
        approval_id: str,
    ) -> ProviderQualificationTimeline | None: ...


class TrustedCoverageResolver(Protocol):
    def resolve(
        self,
        *,
        instrument_id: str,
        frequency: str,
        start: date,
        end: date,
    ) -> TrustedCoverage: ...


_CAPABILITY_BY_FREQUENCY = {
    BarFrequency.DAY: ProviderCapability.DAILY_BARS,
    BarFrequency.MINUTE: ProviderCapability.MINUTE_BARS,
}


class FormalCaptureAdmissionService:
    def __init__(
        self,
        *,
        lookup: QualificationLookup,
        coverage: TrustedCoverageResolver,
    ) -> None:
        self._lookup = lookup
        self._coverage = coverage

    def resolve(
        self,
        request: FormalCaptureRequest,
        *,
        created_at: datetime,
    ) -> ResolvedFormalCaptureCommand:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        timeline = self._lookup.get_timeline_for_approval(request.approval_id)
        if timeline is None or timeline.approval is None:
            raise FormalCaptureAdmissionError("provider approval was not found")
        if timeline.approval.approval_id != request.approval_id:
            raise FormalCaptureAdmissionError("provider approval identity drift")
        if not timeline.is_approved_for(timeline.identity, captured_at=created_at):
            raise FormalCaptureAdmissionError("provider is not approved at command time")
        expected_capability = _CAPABILITY_BY_FREQUENCY.get(request.frequency)
        if expected_capability is None or timeline.identity.capability is not expected_capability:
            raise FormalCaptureAdmissionError("provider capability does not match frequency")
        instrument = str(InstrumentId.parse(request.instrument_id))
        report_coverage = timeline.report.coverage
        if (
            instrument not in report_coverage.instruments
            or request.start < report_coverage.start
            or request.end > report_coverage.end
        ):
            raise FormalCaptureAdmissionError("request exceeds qualified provider coverage")
        if request.adjustment.name not in timeline.report.adjust_modes:
            raise FormalCaptureAdmissionError("adjustment is not qualified")
        coverage = self._coverage.resolve(
            instrument_id=instrument,
            frequency=request.frequency.value,
            start=request.start,
            end=request.end,
        )
        sessions = tuple(coverage.sessions)
        if not sessions or tuple(sorted(set(sessions))) != sessions:
            raise FormalCaptureAdmissionError("trusted coverage is empty or non-canonical")
        if coverage.rows_per_session <= 0:
            raise FormalCaptureAdmissionError("trusted coverage row count is invalid")
        try:
            validate_digest(
                "coverage_membership_digest",
                coverage.coverage_membership_digest,
            )
            validate_digest("policy_digest", coverage.policy_digest)
        except ValueError as error:
            raise FormalCaptureAdmissionError("trusted coverage digest is invalid") from error
        return ResolvedFormalCaptureCommand(
            identity={key: str(value) for key, value in timeline.identity.to_dict().items()},
            identity_digest=timeline.identity.identity_digest,
            report_digest=timeline.report.report_digest,
            approval_id=timeline.approval.approval_id,
            instrument_id=instrument,
            frequency=request.frequency,
            start=request.start,
            end=request.end,
            adjustment=request.adjustment,
            sessions=sessions,
            rows_per_session=coverage.rows_per_session,
            coverage_membership_digest=coverage.coverage_membership_digest,
            policy_digest=coverage.policy_digest,
            created_at=created_at,
        )

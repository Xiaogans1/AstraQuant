"""Immutable evidence report for qualifying one provider capability."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum

from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

from .provider_identity import ProviderIdentity

QUALIFICATION_REPORT_SCHEMA = "astraquant.provider-qualification-report/v1"


class QualificationCheck(StrEnum):
    COVERAGE = "COVERAGE"
    DELISTED_INSTRUMENT = "DELISTED_INSTRUMENT"
    ADJUST_AND_UNITS = "ADJUST_AND_UNITS"
    PAGINATION_AND_TRUNCATION = "PAGINATION_AND_TRUNCATION"
    REVISION_BEHAVIOR = "REVISION_BEHAVIOR"
    RATE_LIMIT = "RATE_LIMIT"
    SCHEMA_EVOLUTION = "SCHEMA_EVOLUTION"


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_TESTED = "NOT_TESTED"


class QualificationState(StrEnum):
    UNQUALIFIED = "UNQUALIFIED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"
    COMPROMISED = "COMPROMISED"


class RevocationKind(StrEnum):
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    RETROACTIVE_COMPROMISE = "RETROACTIVE_COMPROMISE"


class QualificationError(ValueError):
    """Raised when a provider qualification state transition is not valid."""


def _utc(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    if value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _canonical_strings(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    canonical: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"{name} entries must be non-empty canonical text")
        canonical.append(value)
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{name} contains duplicate entries")
    return tuple(sorted(canonical))


def _canonical_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty canonical text")
    return value


def _content_digest(value: object) -> str:
    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return f"sha256:{digest}"


@dataclass(frozen=True, slots=True)
class ProbeEvidence:
    request_digest: str
    raw_response_digest: str
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_digest",
            validate_digest("request_digest", self.request_digest),
        )
        object.__setattr__(
            self,
            "raw_response_digest",
            validate_digest("raw_response_digest", self.raw_response_digest),
        )
        object.__setattr__(self, "observed_at", _utc("observed_at", self.observed_at))

    def to_dict(self) -> dict[str, str]:
        return {
            "request_digest": self.request_digest,
            "raw_response_digest": self.raw_response_digest,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class QualificationCoverage:
    start: date
    end: date
    instruments: tuple[str, ...]
    delisted_instruments: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.start, date) or isinstance(self.start, datetime):
            raise ValueError("start must be a date")
        if not isinstance(self.end, date) or isinstance(self.end, datetime):
            raise ValueError("end must be a date")
        if self.start > self.end:
            raise ValueError("coverage start must not be after end")
        object.__setattr__(
            self,
            "instruments",
            _canonical_strings("instruments", tuple(self.instruments)),
        )
        object.__setattr__(
            self,
            "delisted_instruments",
            _canonical_strings(
                "delisted_instruments",
                tuple(self.delisted_instruments),
            ),
        )

    def to_dict(self) -> dict[str, str | list[str]]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "instruments": list(self.instruments),
            "delisted_instruments": list(self.delisted_instruments),
        }


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    check: QualificationCheck
    status: CheckStatus
    evidence_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.check, QualificationCheck):
            raise ValueError("check must be a known QualificationCheck")
        if not isinstance(self.status, CheckStatus):
            raise ValueError("status must be a known CheckStatus")
        object.__setattr__(
            self,
            "evidence_digest",
            validate_digest("evidence_digest", self.evidence_digest),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "check": self.check.value,
            "status": self.status.value,
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True, slots=True)
class QualificationReport:
    identity: ProviderIdentity
    probes: tuple[ProbeEvidence, ...]
    coverage: QualificationCoverage
    results: tuple[CapabilityResult, ...]
    adjust_modes: tuple[str, ...]
    units: tuple[str, ...]
    observed_at: datetime
    schema_version: str = QUALIFICATION_REPORT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ProviderIdentity):
            raise ValueError("identity must be a ProviderIdentity")
        probes = tuple(self.probes)
        if not all(isinstance(probe, ProbeEvidence) for probe in probes):
            raise ValueError("probes must contain ProbeEvidence")
        object.__setattr__(
            self,
            "probes",
            tuple(
                sorted(
                    probes,
                    key=lambda probe: canonical_json_bytes(probe.to_dict()),
                )
            ),
        )
        if not isinstance(self.coverage, QualificationCoverage):
            raise ValueError("coverage must be QualificationCoverage")
        results = tuple(self.results)
        if not all(isinstance(result, CapabilityResult) for result in results):
            raise ValueError("results must contain CapabilityResult")
        checks = [result.check for result in results]
        if len(checks) != len(set(checks)):
            raise ValueError("duplicate qualification check")
        object.__setattr__(
            self,
            "results",
            tuple(sorted(results, key=lambda result: result.check.value)),
        )
        object.__setattr__(
            self,
            "adjust_modes",
            _canonical_strings("adjust_modes", tuple(self.adjust_modes)),
        )
        object.__setattr__(self, "units", _canonical_strings("units", tuple(self.units)))
        object.__setattr__(self, "observed_at", _utc("observed_at", self.observed_at))
        if self.schema_version != QUALIFICATION_REPORT_SCHEMA:
            raise ValueError("unsupported qualification report schema")

    @property
    def approvable(self) -> bool:
        return (
            bool(self.probes)
            and bool(self.coverage.instruments)
            and bool(self.coverage.delisted_instruments)
            and bool(self.adjust_modes)
            and bool(self.units)
            and {result.check for result in self.results} == set(QualificationCheck)
            and all(result.status is CheckStatus.PASS for result in self.results)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "identity_digest": self.identity.identity_digest,
            "probes": [probe.to_dict() for probe in self.probes],
            "coverage": self.coverage.to_dict(),
            "results": [result.to_dict() for result in self.results],
            "adjust_modes": list(self.adjust_modes),
            "units": list(self.units),
            "observed_at": self.observed_at.isoformat(),
        }

    @property
    def report_digest(self) -> str:
        return _content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ProviderApproval:
    identity_digest: str
    report_digest: str
    reviewer: str
    policy_version: str
    effective_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identity_digest",
            validate_digest("identity_digest", self.identity_digest),
        )
        object.__setattr__(
            self,
            "report_digest",
            validate_digest("report_digest", self.report_digest),
        )
        object.__setattr__(self, "reviewer", _canonical_text("reviewer", self.reviewer))
        object.__setattr__(
            self,
            "policy_version",
            _canonical_text("policy_version", self.policy_version),
        )
        object.__setattr__(
            self,
            "effective_at",
            _utc("effective_at", self.effective_at),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "identity_digest": self.identity_digest,
            "report_digest": self.report_digest,
            "reviewer": self.reviewer,
            "policy_version": self.policy_version,
            "effective_at": self.effective_at.isoformat(),
        }

    @property
    def approval_id(self) -> str:
        return _content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ProviderRevocation:
    kind: RevocationKind
    effective_at: datetime
    reviewer: str
    reason_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RevocationKind):
            raise ValueError("kind must be a known RevocationKind")
        object.__setattr__(
            self,
            "effective_at",
            _utc("effective_at", self.effective_at),
        )
        object.__setattr__(self, "reviewer", _canonical_text("reviewer", self.reviewer))
        object.__setattr__(
            self,
            "reason_digest",
            validate_digest("reason_digest", self.reason_digest),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "effective_at": self.effective_at.isoformat(),
            "reviewer": self.reviewer,
            "reason_digest": self.reason_digest,
        }

    @property
    def revocation_id(self) -> str:
        return _content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ProviderQualificationTimeline:
    identity: ProviderIdentity
    report: QualificationReport
    approval: ProviderApproval | None = None
    revocations: tuple[ProviderRevocation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ProviderIdentity):
            raise ValueError("identity must be ProviderIdentity")
        if not isinstance(self.report, QualificationReport):
            raise ValueError("report must be QualificationReport")
        if self.report.identity.identity_digest != self.identity.identity_digest:
            raise ValueError("report identity does not match timeline identity")
        if self.approval is not None:
            if not isinstance(self.approval, ProviderApproval):
                raise ValueError("approval must be ProviderApproval")
            if self.approval.identity_digest != self.identity.identity_digest:
                raise ValueError("approval identity does not match timeline identity")
            if self.approval.report_digest != self.report.report_digest:
                raise ValueError("approval report does not match timeline report")
        revocations = tuple(self.revocations)
        if not all(isinstance(item, ProviderRevocation) for item in revocations):
            raise ValueError("revocations must contain ProviderRevocation")
        object.__setattr__(
            self,
            "revocations",
            tuple(sorted(revocations, key=lambda item: (item.effective_at, item.kind.value))),
        )

    @property
    def state(self) -> QualificationState:
        if any(item.kind is RevocationKind.RETROACTIVE_COMPROMISE for item in self.revocations):
            return QualificationState.COMPROMISED
        if self.revocations:
            return QualificationState.REVOKED
        if self.approval is not None:
            return QualificationState.APPROVED
        return QualificationState.UNQUALIFIED

    def approve(
        self,
        *,
        reviewer: str,
        policy_version: str,
        effective_at: datetime,
    ) -> ProviderQualificationTimeline:
        if self.state is QualificationState.COMPROMISED:
            raise QualificationError("provider qualification is compromised")
        if not self.report.approvable:
            raise QualificationError("report is not approvable")
        if self.approval is not None:
            raise QualificationError("provider qualification is already approved")
        approval = ProviderApproval(
            identity_digest=self.identity.identity_digest,
            report_digest=self.report.report_digest,
            reviewer=reviewer,
            policy_version=policy_version,
            effective_at=effective_at,
        )
        return replace(self, approval=approval)

    def revoke(
        self,
        *,
        kind: RevocationKind,
        effective_at: datetime,
        reviewer: str,
        reason_digest: str,
    ) -> ProviderQualificationTimeline:
        if self.approval is None:
            raise QualificationError("provider qualification is not approved")
        revocation = ProviderRevocation(
            kind=kind,
            effective_at=effective_at,
            reviewer=reviewer,
            reason_digest=reason_digest,
        )
        if revocation.effective_at < self.approval.effective_at:
            raise QualificationError("revocation cannot be before approval")
        if any(item.revocation_id == revocation.revocation_id for item in self.revocations):
            raise QualificationError("duplicate revocation")
        if self.state is QualificationState.COMPROMISED:
            raise QualificationError("provider qualification is compromised")
        if revocation.kind is not RevocationKind.RETROACTIVE_COMPROMISE and self.revocations:
            raise QualificationError("provider qualification is already revoked")
        return replace(self, revocations=(*self.revocations, revocation))

    def is_approved_for(
        self,
        identity: ProviderIdentity,
        *,
        captured_at: datetime,
    ) -> bool:
        capture_time = _utc("captured_at", captured_at)
        if identity.identity_digest != self.identity.identity_digest:
            return False
        if self.approval is None or capture_time < self.approval.effective_at:
            return False
        if any(item.kind is RevocationKind.RETROACTIVE_COMPROMISE for item in self.revocations):
            return False
        return not any(capture_time >= item.effective_at for item in self.revocations)

"""Immutable evidence report for qualifying one provider capability."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
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
        digest = hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()
        return f"sha256:{digest}"

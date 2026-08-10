"""Typed evidence lineage and fail-closed formal admission."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from astraquant_domain.run_manifest import RunClass, validate_digest


class EvidenceClass(StrEnum):
    REAL_API_MARKET = "REAL_API_MARKET"
    REAL_API_REFERENCE = "REAL_API_REFERENCE"
    REAL_API_BROKER = "REAL_API_BROKER"
    DERIVED_REAL_API = "DERIVED_REAL_API"
    OFFICIAL_RULE = "OFFICIAL_RULE"
    TEST_ONLY = "TEST_ONLY"
    EXPLORATORY_ONLY = "EXPLORATORY_ONLY"
    LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"


class EvidenceRole(StrEnum):
    MARKET = "MARKET"
    REFERENCE = "REFERENCE"
    BROKER = "BROKER"
    RULE = "RULE"
    DERIVED = "DERIVED"


class EvidenceError(ValueError):
    """Base error for invalid evidence graphs."""


class FormalAdmissionError(EvidenceError):
    """Raised when evidence cannot enter a FORMAL run."""


class EvidenceCycleError(EvidenceError):
    """Raised when an evidence ancestry graph contains a cycle."""


class EvidenceCollisionError(EvidenceError):
    """Raised when one artifact ID identifies different evidence."""


_CLASS_ROLE = {
    EvidenceClass.REAL_API_MARKET: EvidenceRole.MARKET,
    EvidenceClass.REAL_API_REFERENCE: EvidenceRole.REFERENCE,
    EvidenceClass.REAL_API_BROKER: EvidenceRole.BROKER,
    EvidenceClass.DERIVED_REAL_API: EvidenceRole.DERIVED,
    EvidenceClass.OFFICIAL_RULE: EvidenceRole.RULE,
}
_AUTHORITY_CLASSES = frozenset(
    {
        EvidenceClass.REAL_API_MARKET,
        EvidenceClass.REAL_API_REFERENCE,
        EvidenceClass.REAL_API_BROKER,
        EvidenceClass.OFFICIAL_RULE,
    }
)
_FORMAL_CLASSES = _AUTHORITY_CLASSES | {EvidenceClass.DERIVED_REAL_API}
_MUTABLE_ALIASES = frozenset({"latest", "current", "head", "as_of", "as-of"})


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    artifact_id: str | None
    evidence_class: EvidenceClass
    role: EvidenceRole
    content_digest: str
    parents: tuple[EvidenceRef, ...] = ()
    approval_id: str | None = None
    sealed: bool = True
    manifest_schema_version: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_class, EvidenceClass):
            raise EvidenceError("unknown evidence_class")
        if not isinstance(self.role, EvidenceRole):
            raise EvidenceError("unknown evidence role")
        validate_digest("content_digest", self.content_digest)
        if not isinstance(self.manifest_schema_version, int):
            raise EvidenceError("manifest schema version must be an integer")
        if not isinstance(self.sealed, bool):
            raise EvidenceError("sealed must be a boolean")
        object.__setattr__(self, "parents", tuple(self.parents))

        required_role = _CLASS_ROLE.get(self.evidence_class)
        if required_role is not None and self.role is not required_role:
            raise EvidenceError(
                f"{self.evidence_class.value} evidence requires role {required_role.value}"
            )
        if self.evidence_class in _AUTHORITY_CLASSES:
            if not self.approval_id or self.approval_id != self.approval_id.strip():
                raise EvidenceError(f"{self.evidence_class.value} requires an approval_id")
            if self.parents:
                raise EvidenceError(f"{self.evidence_class.value} cannot declare parents")
        elif self.approval_id is not None:
            raise EvidenceError(f"{self.evidence_class.value} cannot carry an approval_id")
        if self.evidence_class is EvidenceClass.DERIVED_REAL_API and not self.parents:
            raise EvidenceError("DERIVED_REAL_API requires at least one parent")

    @classmethod
    def real_api_market(
        cls,
        *,
        artifact_id: str | None,
        approval_id: str,
        digest: str,
    ) -> EvidenceRef:
        return cls(
            artifact_id=artifact_id,
            evidence_class=EvidenceClass.REAL_API_MARKET,
            role=EvidenceRole.MARKET,
            content_digest=digest,
            approval_id=approval_id,
        )

    @classmethod
    def real_api_reference(
        cls,
        *,
        artifact_id: str | None,
        approval_id: str,
        digest: str,
    ) -> EvidenceRef:
        return cls(
            artifact_id=artifact_id,
            evidence_class=EvidenceClass.REAL_API_REFERENCE,
            role=EvidenceRole.REFERENCE,
            content_digest=digest,
            approval_id=approval_id,
        )

    @classmethod
    def real_api_broker(
        cls,
        *,
        artifact_id: str | None,
        approval_id: str,
        digest: str,
    ) -> EvidenceRef:
        return cls(
            artifact_id=artifact_id,
            evidence_class=EvidenceClass.REAL_API_BROKER,
            role=EvidenceRole.BROKER,
            content_digest=digest,
            approval_id=approval_id,
        )

    @classmethod
    def official_rule(
        cls,
        *,
        artifact_id: str | None,
        approval_id: str,
        digest: str,
    ) -> EvidenceRef:
        return cls(
            artifact_id=artifact_id,
            evidence_class=EvidenceClass.OFFICIAL_RULE,
            role=EvidenceRole.RULE,
            content_digest=digest,
            approval_id=approval_id,
        )

    @classmethod
    def derived(
        cls,
        *,
        artifact_id: str | None,
        digest: str,
        parents: tuple[EvidenceRef, ...],
    ) -> EvidenceRef:
        return cls(
            artifact_id=artifact_id,
            evidence_class=EvidenceClass.DERIVED_REAL_API,
            role=EvidenceRole.DERIVED,
            content_digest=digest,
            parents=parents,
        )

    @classmethod
    def fixture(cls, artifact_id: str, digest: str) -> EvidenceRef:
        return cls(
            artifact_id=artifact_id,
            evidence_class=EvidenceClass.TEST_ONLY,
            role=EvidenceRole.MARKET,
            content_digest=digest,
        )

    @classmethod
    def exploratory(cls, artifact_id: str, digest: str) -> EvidenceRef:
        return cls(
            artifact_id=artifact_id,
            evidence_class=EvidenceClass.EXPLORATORY_ONLY,
            role=EvidenceRole.MARKET,
            content_digest=digest,
        )

    @classmethod
    def legacy(
        cls,
        artifact_id: str | None,
        digest: str,
        *,
        manifest_schema_version: int = 1,
    ) -> EvidenceRef:
        return cls(
            artifact_id=artifact_id,
            evidence_class=EvidenceClass.LEGACY_UNVERIFIED,
            role=EvidenceRole.MARKET,
            content_digest=digest,
            manifest_schema_version=manifest_schema_version,
        )

    @classmethod
    def from_manifest_metadata(
        cls,
        *,
        artifact_id: str | None,
        digest: str,
        manifest_schema_version: int,
        evidence_class: str | None,
        role: str | None,
        parents: tuple[EvidenceRef, ...] | None,
        approval_id: str | None,
        sealed: bool,
    ) -> EvidenceRef:
        """Load untrusted metadata, degrading incomplete contracts to legacy."""

        if manifest_schema_version != 2:
            return cls.legacy(
                artifact_id,
                digest,
                manifest_schema_version=manifest_schema_version,
            )
        if evidence_class is None or role is None:
            return cls.legacy(
                artifact_id,
                digest,
                manifest_schema_version=manifest_schema_version,
            )
        try:
            loaded_class = EvidenceClass(evidence_class)
            loaded_role = EvidenceRole(role)
        except (TypeError, ValueError):
            return cls.legacy(
                artifact_id,
                digest,
                manifest_schema_version=manifest_schema_version,
            )
        try:
            return cls(
                artifact_id=artifact_id,
                evidence_class=loaded_class,
                role=loaded_role,
                content_digest=digest,
                parents=tuple(parents or ()),
                approval_id=approval_id,
                sealed=sealed,
                manifest_schema_version=manifest_schema_version,
            )
        except EvidenceError:
            return cls.legacy(
                artifact_id,
                digest,
                manifest_schema_version=manifest_schema_version,
            )

    def require_exact_id(self) -> str:
        if self.artifact_id is None or not self.artifact_id.strip():
            raise FormalAdmissionError("formal evidence root requires an exact artifact ID")
        normalized = self.artifact_id.strip().casefold()
        prefix = normalized.split(":", maxsplit=1)[0]
        if normalized in _MUTABLE_ALIASES or prefix in _MUTABLE_ALIASES:
            raise FormalAdmissionError(
                f"mutable alias {self.artifact_id!r} is not an exact artifact ID"
            )
        if self.artifact_id != self.artifact_id.strip():
            raise FormalAdmissionError("artifact ID must be canonical")
        return self.artifact_id


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    root_artifact_ids: tuple[str, ...]
    evidence_digests: tuple[str, ...]


class EvidenceGate:
    def __init__(self, *, approved_authority_ids: Iterable[str] = ()) -> None:
        self._approved_authority_ids = frozenset(approved_authority_ids)

    def admit(
        self,
        run_class: RunClass,
        *,
        roots: tuple[EvidenceRef, ...],
    ) -> AdmissionResult:
        if not isinstance(run_class, RunClass):
            raise EvidenceError("unknown run_class")
        if not roots:
            raise EvidenceError("at least one evidence root is required")

        seen: dict[str, tuple[object, ...]] = {}
        for root in roots:
            self._visit(root, run_class=run_class, path=(), seen=seen)

        return AdmissionResult(
            root_artifact_ids=tuple(sorted(root.require_exact_id() for root in roots)),
            evidence_digests=tuple(sorted({item.content_digest for item in self._walk(roots)})),
        )

    def _visit(
        self,
        evidence: EvidenceRef,
        *,
        run_class: RunClass,
        path: tuple[int, ...],
        seen: dict[str, tuple[object, ...]],
    ) -> None:
        identity = id(evidence)
        if identity in path:
            label = evidence.artifact_id or evidence.content_digest
            raise EvidenceCycleError(f"evidence cycle contains {label}")

        artifact_id = evidence.require_exact_id()
        fingerprint = self._fingerprint(evidence)
        previous = seen.get(artifact_id)
        if previous is not None and previous != fingerprint:
            raise EvidenceCollisionError(
                f"artifact ID {artifact_id!r} identifies conflicting evidence"
            )
        seen[artifact_id] = fingerprint

        next_path = (*path, identity)
        for parent in evidence.parents:
            self._visit(parent, run_class=run_class, path=next_path, seen=seen)
        if run_class is RunClass.FORMAL:
            self._require_formal(evidence)

    def _require_formal(self, evidence: EvidenceRef) -> None:
        if evidence.evidence_class not in _FORMAL_CLASSES:
            raise FormalAdmissionError(
                f"{evidence.evidence_class.value} evidence cannot enter FORMAL"
            )
        if evidence.manifest_schema_version != 2:
            raise FormalAdmissionError(
                f"formal evidence requires schema v2, got {evidence.manifest_schema_version}"
            )
        if not evidence.sealed:
            raise FormalAdmissionError("formal evidence must be sealed")
        if evidence.evidence_class in _AUTHORITY_CLASSES:
            if evidence.approval_id not in self._approved_authority_ids:
                raise FormalAdmissionError(
                    f"formal evidence approval {evidence.approval_id!r} is not approved"
                )
        elif not self._has_data_ancestor(evidence, visited=set()):
            raise FormalAdmissionError(
                "DERIVED_REAL_API requires at least one market/reference/broker data ancestor"
            )

    def _has_data_ancestor(self, evidence: EvidenceRef, *, visited: set[int]) -> bool:
        identity = id(evidence)
        if identity in visited:
            return False
        visited.add(identity)
        for parent in evidence.parents:
            if parent.evidence_class in {
                EvidenceClass.REAL_API_MARKET,
                EvidenceClass.REAL_API_REFERENCE,
                EvidenceClass.REAL_API_BROKER,
            }:
                return True
            if self._has_data_ancestor(parent, visited=visited):
                return True
        return False

    @staticmethod
    def _fingerprint(evidence: EvidenceRef) -> tuple[object, ...]:
        return (
            evidence.evidence_class.value,
            evidence.role.value,
            evidence.content_digest,
            evidence.approval_id,
            evidence.sealed,
            evidence.manifest_schema_version,
            tuple((parent.artifact_id, parent.content_digest) for parent in evidence.parents),
        )

    @staticmethod
    def _walk(roots: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
        ordered: list[EvidenceRef] = []
        visited: set[int] = set()
        stack = list(reversed(roots))
        while stack:
            current = stack.pop()
            identity = id(current)
            if identity in visited:
                continue
            visited.add(identity)
            ordered.append(current)
            stack.extend(reversed(current.parents))
        return tuple(ordered)

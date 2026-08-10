"""The single API boundary for admitting immutable FORMAL runs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from astraquant_data.evidence import EvidenceGate, EvidenceRef, FormalAdmissionError
from astraquant_domain.run_manifest import RunClass, RunManifest


class FormalModelDecision(StrEnum):
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class FormalRunAdmission:
    manifest_digest: str
    root_artifact_ids: tuple[str, ...]
    root_content_digests: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class FormalModelSelection:
    decision: FormalModelDecision
    allow_new_orders: bool
    model_id: None
    reason: str


class FormalAdmissionService:
    """Combine shared run and evidence contracts without accepting aliases or paths."""

    def __init__(self, *, approved_authority_ids: Iterable[str] = ()) -> None:
        self._evidence_gate = EvidenceGate(approved_authority_ids=approved_authority_ids)

    def admit_run(
        self,
        manifest: RunManifest,
        *,
        evidence_roots: tuple[EvidenceRef, ...],
    ) -> FormalRunAdmission:
        if not isinstance(manifest, RunManifest):
            raise FormalAdmissionError("formal admission requires a typed RunManifest")
        manifest.assert_runnable()
        if manifest.run_class is not RunClass.FORMAL:
            raise FormalAdmissionError("formal admission requires run_class=FORMAL")
        if not evidence_roots:
            raise FormalAdmissionError("formal admission requires evidence roots")

        root_identity: dict[str, str] = {}
        for root in evidence_roots:
            artifact_id = root.require_exact_id()
            previous = root_identity.get(artifact_id)
            if previous is not None and previous != root.content_digest:
                raise FormalAdmissionError(
                    f"root artifact ID {artifact_id!r} has conflicting digests"
                )
            root_identity[artifact_id] = root.content_digest
        if dict(manifest.input_digests) != root_identity:
            raise FormalAdmissionError(
                "run manifest input_digests must exactly match evidence roots"
            )

        evidence = self._evidence_gate.admit(
            RunClass.FORMAL,
            roots=evidence_roots,
        )
        return FormalRunAdmission(
            manifest_digest=manifest.manifest_digest,
            root_artifact_ids=evidence.root_artifact_ids,
            root_content_digests=tuple(sorted(root_identity.items())),
        )

    def select_formal_model(self) -> FormalModelSelection:
        """Fail closed until Phase 5 introduces immutable model release targets."""

        return FormalModelSelection(
            decision=FormalModelDecision.HOLD,
            allow_new_orders=False,
            model_id=None,
            reason="Phase 5 model release targets are not available; no new orders",
        )

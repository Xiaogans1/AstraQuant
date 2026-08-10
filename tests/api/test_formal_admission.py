from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from astraquant_api.formal_admission import (
    FormalAdmissionService,
    FormalModelDecision,
)
from astraquant_data.evidence import EvidenceRef, FormalAdmissionError
from astraquant_domain.run_manifest import (
    RunClass,
    RunManifest,
    UnsealedRunManifestError,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _root(*, artifact_id: str = "snapshot:bars-v2") -> EvidenceRef:
    return EvidenceRef.real_api_market(
        artifact_id=artifact_id,
        approval_id="eastmoney-qualified-v1",
        digest=_digest("1"),
    )


def _manifest(
    root: EvidenceRef,
    *,
    run_class: RunClass = RunClass.FORMAL,
    sealed: bool = True,
) -> RunManifest:
    manifest = RunManifest(
        run_class=run_class,
        code_digest=_digest("2"),
        environment_digest=_digest("3"),
        input_digests={str(root.artifact_id): root.content_digest},
        config_digest=_digest("4"),
        randomness_digest=_digest("5"),
        event_order_policy_digest=_digest("6"),
        matcher_policy_digest=_digest("7"),
        vintage_policy_digest=_digest("8"),
        policy_digests={"release": _digest("9")},
    )
    return manifest.seal() if sealed else manifest


def _service() -> FormalAdmissionService:
    return FormalAdmissionService(approved_authority_ids={"eastmoney-qualified-v1"})


def test_admit_run_returns_frozen_exact_identity() -> None:
    root = _root()
    manifest = _manifest(root)

    admission = _service().admit_run(manifest, evidence_roots=(root,))

    assert admission.manifest_digest == manifest.manifest_digest
    assert admission.root_artifact_ids == ("snapshot:bars-v2",)
    assert admission.root_content_digests == ((_root().artifact_id, _digest("1")),)
    with pytest.raises(FrozenInstanceError):
        admission.manifest_digest = _digest("a")  # type: ignore[misc]


def test_admit_run_rejects_draft_nonformal_and_untyped_manifest() -> None:
    root = _root()
    service = _service()

    with pytest.raises(UnsealedRunManifestError):
        service.admit_run(_manifest(root, sealed=False), evidence_roots=(root,))
    with pytest.raises(FormalAdmissionError, match="FORMAL"):
        service.admit_run(
            _manifest(root, run_class=RunClass.EXPLORATORY),
            evidence_roots=(root,),
        )
    with pytest.raises(FormalAdmissionError, match="typed RunManifest"):
        service.admit_run(
            _manifest(root).to_dict(),  # type: ignore[arg-type]
            evidence_roots=(root,),
        )


@pytest.mark.parametrize("artifact_id", ["latest", "current:bars", "as_of"])
def test_admit_run_rejects_mutable_evidence_aliases(artifact_id: str) -> None:
    root = _root(artifact_id=artifact_id)

    with pytest.raises(FormalAdmissionError, match="exact artifact ID"):
        _service().admit_run(_manifest(root), evidence_roots=(root,))


def test_admit_run_rejects_legacy_unapproved_and_input_mismatch() -> None:
    service = _service()
    approved = _root()
    legacy = EvidenceRef.legacy("snapshot:legacy", _digest("a"))
    unapproved = EvidenceRef.real_api_market(
        artifact_id="snapshot:unapproved",
        approval_id="unknown-provider",
        digest=_digest("b"),
    )

    with pytest.raises(FormalAdmissionError, match="LEGACY_UNVERIFIED"):
        service.admit_run(_manifest(legacy), evidence_roots=(legacy,))
    with pytest.raises(FormalAdmissionError, match="not approved"):
        service.admit_run(_manifest(unapproved), evidence_roots=(unapproved,))

    mismatched = replace(
        _manifest(approved),
        input_digests={"snapshot:other": approved.content_digest},
    )
    with pytest.raises(FormalAdmissionError, match="input_digests"):
        service.admit_run(mismatched, evidence_roots=(approved,))


def test_phase0_formal_model_selection_is_always_hold() -> None:
    selection = _service().select_formal_model()

    assert selection.decision is FormalModelDecision.HOLD
    assert selection.allow_new_orders is False
    assert selection.model_id is None
    assert "Phase 5" in selection.reason

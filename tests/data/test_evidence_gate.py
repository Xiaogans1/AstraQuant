from dataclasses import replace
from datetime import UTC, datetime

import pytest

from astraquant_data.evidence import (
    EvidenceClass,
    EvidenceCollisionError,
    EvidenceCycleError,
    EvidenceGate,
    EvidenceRef,
    FormalAdmissionError,
)
from astraquant_data.manifests import SnapshotFile, SnapshotManifest
from astraquant_data.quality import QualityReport
from astraquant_domain import RunClass


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _approved_market(
    *,
    artifact_id: str | None = "capture-1",
    digest: str = _digest("1"),
) -> EvidenceRef:
    return EvidenceRef.real_api_market(
        artifact_id=artifact_id,
        approval_id="eastmoney-bars-v1",
        digest=digest,
    )


def _formal_gate() -> EvidenceGate:
    return EvidenceGate(approved_authority_ids={"eastmoney-bars-v1", "sse-rule-v1"})


def test_derived_real_api_requires_closed_approved_ancestry() -> None:
    raw = _approved_market()
    feature = EvidenceRef.derived(
        artifact_id="feature-1",
        digest=_digest("2"),
        parents=(raw,),
    )

    result = _formal_gate().admit(RunClass.FORMAL, roots=(feature,))

    assert result.root_artifact_ids == ("feature-1",)
    assert result.evidence_digests == (_digest("1"), _digest("2"))


@pytest.mark.parametrize(
    "bad",
    [
        EvidenceRef.fixture("renamed-real-api.parquet", _digest("1")),
        EvidenceRef.exploratory("akshare-bars", _digest("1")),
        EvidenceRef.legacy("old-snapshot", _digest("1")),
    ],
)
def test_nonformal_evidence_cannot_enter_formal_even_when_renamed(
    bad: EvidenceRef,
) -> None:
    with pytest.raises(FormalAdmissionError, match=bad.evidence_class.value):
        _formal_gate().admit(RunClass.FORMAL, roots=(bad,))


def test_formal_rejects_a_mixed_real_and_fixture_ancestry() -> None:
    feature = EvidenceRef.derived(
        artifact_id="feature-1",
        digest=_digest("3"),
        parents=(
            _approved_market(),
            EvidenceRef.fixture("renamed-reference.json", _digest("2")),
        ),
    )

    with pytest.raises(FormalAdmissionError, match="TEST_ONLY"):
        _formal_gate().admit(RunClass.FORMAL, roots=(feature,))


def test_formal_rejects_unpinned_or_mutable_alias_roots() -> None:
    unpinned = EvidenceRef.derived(
        artifact_id=None,
        digest=_digest("2"),
        parents=(_approved_market(),),
    )
    latest = EvidenceRef.derived(
        artifact_id="latest",
        digest=_digest("2"),
        parents=(_approved_market(),),
    )

    with pytest.raises(FormalAdmissionError, match="exact"):
        _formal_gate().admit(RunClass.FORMAL, roots=(unpinned,))
    with pytest.raises(FormalAdmissionError, match="mutable alias"):
        _formal_gate().admit(RunClass.FORMAL, roots=(latest,))


@pytest.mark.parametrize("schema_version", [1, 0, 99])
def test_formal_rejects_legacy_or_unknown_manifest_schema(schema_version: int) -> None:
    raw = replace(_approved_market(), manifest_schema_version=schema_version)

    with pytest.raises(FormalAdmissionError, match="schema"):
        _formal_gate().admit(RunClass.FORMAL, roots=(raw,))


def test_formal_rejects_unapproved_or_unsealed_real_api() -> None:
    unapproved = _approved_market()
    unsealed = replace(_approved_market(), sealed=False)

    with pytest.raises(FormalAdmissionError, match="approval"):
        EvidenceGate().admit(RunClass.FORMAL, roots=(unapproved,))
    with pytest.raises(FormalAdmissionError, match="sealed"):
        _formal_gate().admit(RunClass.FORMAL, roots=(unsealed,))


def test_gate_rejects_a_recursive_evidence_cycle() -> None:
    feature = EvidenceRef.derived(
        artifact_id="feature-1",
        digest=_digest("2"),
        parents=(_approved_market(),),
    )
    object.__setattr__(feature, "parents", (feature,))

    with pytest.raises(EvidenceCycleError, match="feature-1"):
        _formal_gate().admit(RunClass.FORMAL, roots=(feature,))


def test_gate_rejects_same_artifact_id_with_different_identity() -> None:
    first = _approved_market(artifact_id="capture-1", digest=_digest("1"))
    second = _approved_market(artifact_id="capture-1", digest=_digest("2"))
    feature = EvidenceRef.derived(
        artifact_id="feature-1",
        digest=_digest("3"),
        parents=(first, second),
    )

    with pytest.raises(EvidenceCollisionError, match="capture-1"):
        _formal_gate().admit(RunClass.FORMAL, roots=(feature,))


def test_rule_only_parents_cannot_claim_derived_market_evidence() -> None:
    rule = EvidenceRef.official_rule(
        artifact_id="rule-1",
        approval_id="sse-rule-v1",
        digest=_digest("1"),
    )
    feature = EvidenceRef.derived(
        artifact_id="feature-1",
        digest=_digest("2"),
        parents=(rule,),
    )

    with pytest.raises(FormalAdmissionError, match="data ancestor"):
        _formal_gate().admit(RunClass.FORMAL, roots=(feature,))


def test_approved_official_rule_can_be_a_formal_root() -> None:
    rule = EvidenceRef.official_rule(
        artifact_id="rule-1",
        approval_id="sse-rule-v1",
        digest=_digest("1"),
    )

    result = _formal_gate().admit(RunClass.FORMAL, roots=(rule,))

    assert result.root_artifact_ids == ("rule-1",)


def test_exploratory_run_can_use_explicitly_nonformal_evidence() -> None:
    fixture = EvidenceRef.fixture("fixture-bars.csv", _digest("1"))

    result = EvidenceGate().admit(RunClass.EXPLORATORY, roots=(fixture,))

    assert result.root_artifact_ids == ("fixture-bars.csv",)
    assert fixture.evidence_class is EvidenceClass.TEST_ONLY


def test_snapshot_manifest_v1_is_always_legacy_unverified() -> None:
    observed_at = datetime(2026, 8, 10, tzinfo=UTC)
    manifest = SnapshotManifest.create(
        dataset_id="renamed-formal-bars",
        kind="bars",
        created_at=observed_at,
        source_fetched_at=observed_at,
        provider={"id": "eastmoney", "approval_id": "eastmoney-bars-v1"},
        adjustment="NONE",
        calendar_version="calendar-v1",
        series_kind="spot",
        roll_policy=None,
        availability_policy="exact",
        row_count=1,
        min_event_time=observed_at,
        max_event_time=observed_at,
        files=(SnapshotFile(path="renamed-real-api.parquet", sha256="1" * 64, rows=1),),
        quality=QualityReport(row_count=1, issues=()),
    )

    evidence = manifest.to_evidence_ref()

    assert evidence.evidence_class is EvidenceClass.LEGACY_UNVERIFIED
    assert evidence.manifest_schema_version == 1
    with pytest.raises(FormalAdmissionError, match="LEGACY_UNVERIFIED"):
        _formal_gate().admit(RunClass.FORMAL, roots=(evidence,))

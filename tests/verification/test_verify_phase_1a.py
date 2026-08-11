from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astraquant_data.capture import CaptureChunk, CapturePlan, CapturePurpose
from astraquant_data.capture_reconciliation import reconcile_captures
from astraquant_data.capture_store import CaptureStore
from astraquant_data.eastmoney_client import BridgeResponseRepresentation
from astraquant_data.provider_identity import (
    ProviderCapability,
    ProviderIdentity,
    ProviderTransport,
)
from astraquant_data.provider_qualification import (
    CapabilityResult,
    CheckStatus,
    ProbeEvidence,
    ProviderApproval,
    QualificationCheck,
    QualificationCoverage,
    QualificationReport,
)
from tools.verification.verify_phase_1a import run_verification

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _git_head(repository_root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _manifest(tmp_path: Path, repository_root: Path) -> tuple[Path, dict[str, object]]:
    identity = ProviderIdentity(
        vendor="eastmoney",
        product="eastmoney-terminal",
        endpoint="market.daily-bars",
        capability=ProviderCapability.DAILY_BARS,
        interface="gm_python_sdk",
        interface_build="3.0.176",
        transport=ProviderTransport.NDJSON_BRIDGE,
        permission_tier="level1-history",
        schema_fingerprint=_digest("1"),
    )
    probe_request = b'{"method":"qualification_probe"}'
    probe_response = b'{"result":"provider-response"}'
    probe_request_digest = f"sha256:{hashlib.sha256(probe_request).hexdigest()}"
    probe_response_digest = f"sha256:{hashlib.sha256(probe_response).hexdigest()}"
    report = QualificationReport(
        identity=identity,
        probes=(ProbeEvidence(probe_request_digest, probe_response_digest, NOW),),
        coverage=QualificationCoverage(
            start=date(2026, 8, 11),
            end=date(2026, 8, 11),
            instruments=("600000.SSE",),
            delisted_instruments=("600001.SSE",),
        ),
        results=tuple(
            CapabilityResult(check, CheckStatus.PASS, _digest(format(index + 4, "x")))
            for index, check in enumerate(QualificationCheck)
        ),
        adjust_modes=("NONE",),
        units=("price=CNY", "volume=share"),
        observed_at=NOW,
    )
    approval = ProviderApproval(
        identity_digest=identity.identity_digest,
        report_digest=report.report_digest,
        reviewer="test-reviewer",
        policy_version="provider-policy/v1",
        effective_at=NOW,
    )
    qualification_root = tmp_path / "external" / "qualification"
    qualification_root.mkdir(parents=True)
    report_path = qualification_root / f"{report.report_digest[7:]}.json"
    report_path.write_text(
        json.dumps({**report.to_dict(), "report_digest": report.report_digest}),
        encoding="utf-8",
    )
    capture_root = tmp_path / "external" / "capture"
    store = CaptureStore(capture_root)
    probe_plan = CapturePlan(
        identity_digest=identity.identity_digest,
        report_digest=None,
        approval_id=None,
        endpoint=identity.endpoint,
        expected_chunk_count=1,
        expected_row_count=1,
        coverage_proof_digest=_digest("a"),
        started_at=NOW,
        purpose=CapturePurpose.QUALIFICATION_PROBE,
    )
    probe_chunk = CaptureChunk(
        sequence=0,
        canonical_request=probe_request,
        canonical_response=probe_response,
        response_representation=BridgeResponseRepresentation.SDK_OBJECT_CANONICAL,
        requested_at=NOW,
        received_at=NOW,
        recorded_at=NOW,
        serialization_version="astraquant.sdk-object-json/v1",
        dtype="object",
        schema={"kind": "object"},
        units=("count=item",),
        adjust="NONE",
        page_cursor="qualification-probe-0",
        page_count=1,
        returned_count=1,
        declared_total=1,
        attempt=1,
        retry_of_request_digest=None,
    )
    store.begin(probe_plan)
    store.append_chunk(probe_plan.capture_id, probe_chunk)
    probe_envelope = store.seal(probe_plan.capture_id, sealed_at=NOW)
    plan = CapturePlan(
        identity_digest=identity.identity_digest,
        report_digest=report.report_digest,
        approval_id=approval.approval_id,
        endpoint=identity.endpoint,
        expected_chunk_count=1,
        expected_row_count=1,
        coverage_proof_digest=_digest("b"),
        started_at=NOW,
        command_digest=_digest("c"),
    )
    request = {
        "method": "history_range",
        "params": {
            "symbol": "SHSE.600000",
            "frequency": "1d",
            "adjust": 0,
            "page": {"cursor": "2026-08-11/2026-08-11"},
        },
    }
    chunk = CaptureChunk(
        sequence=0,
        canonical_request=json.dumps(request).encode(),
        canonical_response=b'{"rows":[{"close":"10.00"}]}',
        response_representation=BridgeResponseRepresentation.SDK_OBJECT_CANONICAL,
        requested_at=NOW,
        received_at=NOW,
        recorded_at=NOW,
        serialization_version="astraquant.sdk-object-json/v1",
        dtype="list[bar]",
        schema={"kind": "list", "fields": ["close"]},
        units=("price=CNY", "volume=share"),
        adjust="NONE",
        page_cursor="2026-08-11/2026-08-11",
        page_count=1,
        returned_count=1,
        declared_total=1,
        attempt=1,
        retry_of_request_digest=None,
    )
    store.begin(plan)
    store.append_chunk(plan.capture_id, chunk)
    envelope = store.seal(plan.capture_id, sealed_at=NOW)
    second_plan = CapturePlan(
        identity_digest=identity.identity_digest,
        report_digest=report.report_digest,
        approval_id=approval.approval_id,
        endpoint=identity.endpoint,
        expected_chunk_count=1,
        expected_row_count=1,
        coverage_proof_digest=_digest("b"),
        started_at=NOW.replace(hour=1),
        command_digest=_digest("d"),
    )
    second_chunk = CaptureChunk(
        sequence=0,
        canonical_request=chunk.canonical_request,
        canonical_response=chunk.canonical_response,
        response_representation=chunk.response_representation,
        requested_at=NOW.replace(hour=1),
        received_at=NOW.replace(hour=1),
        recorded_at=NOW.replace(hour=1),
        serialization_version=chunk.serialization_version,
        dtype=chunk.dtype,
        schema=dict(chunk.schema),
        units=chunk.units,
        adjust=chunk.adjust,
        page_cursor=chunk.page_cursor,
        page_count=1,
        returned_count=1,
        declared_total=1,
        attempt=1,
        retry_of_request_digest=None,
    )
    store.begin(second_plan)
    store.append_chunk(second_plan.capture_id, second_chunk)
    second_envelope = store.seal(second_plan.capture_id, sealed_at=NOW.replace(hour=1))
    reconciliation = reconcile_captures(store, plan.capture_id, second_plan.capture_id)
    value: dict[str, object] = {
        "schema_version": "astraquant.phase1a-evidence-manifest/v1",
        "evidence_class": "TEST_ONLY",
        "provider_vendor": "eastmoney",
        "implementation_commit": _git_head(repository_root),
        "probe_captures": [
            {
                "capture_root": str(capture_root.resolve()),
                "capture_id": probe_plan.capture_id,
                "seal_digest": probe_envelope.seal_digest,
                "identity_digest": identity.identity_digest,
            }
        ],
        "qualifications": [
            {
                "report_path": str(report_path.resolve()),
                "report_digest": report.report_digest,
                "approval": approval.to_dict(),
                "approval_id": approval.approval_id,
            }
        ],
        "captures": [
            {
                "capture_root": str(capture_root.resolve()),
                "capture_id": plan.capture_id,
                "seal_digest": envelope.seal_digest,
                "capability": ProviderCapability.DAILY_BARS.value,
            },
            {
                "capture_root": str(capture_root.resolve()),
                "capture_id": second_plan.capture_id,
                "seal_digest": second_envelope.seal_digest,
                "capability": ProviderCapability.DAILY_BARS.value,
            },
        ],
        "reconciliations": [
            {
                "capture_root": str(capture_root.resolve()),
                "report_digest": reconciliation.report_digest,
            }
        ],
        "unqualified_capabilities": [
            ProviderCapability.CORPORATE_ACTIONS.value,
            ProviderCapability.INSTRUMENT_STATUS.value,
        ],
    }
    path = tmp_path / "phase1a-evidence.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, value


def test_verifier_revalidates_artifacts_but_rejects_test_only_evidence(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest, _ = _manifest(tmp_path, repository_root)
    output = tmp_path / "run" / "verification.json"

    exit_code = run_verification(
        manifest,
        output,
        repository_root=repository_root,
        created_at=NOW,
    )

    assert exit_code == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    checks = {item["id"]: item["status"] for item in result["checks"]}
    assert checks["evidence-class-real-api"] == "FAIL"
    assert checks["qualification-probe-integrity"] == "PASS"
    assert checks["qualification-binding"] == "PASS"
    assert checks["capture-integrity"] == "PASS"
    assert checks["reconciliation-integrity"] == "PASS"
    assert checks["required-capabilities"] == "FAIL"
    assert result["run_manifest_digest"] != _digest("0")


def test_verifier_detects_tampered_capture(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest_path, manifest = _manifest(tmp_path, repository_root)
    captures = manifest["captures"]
    assert isinstance(captures, list)
    capture = captures[0]
    assert isinstance(capture, dict)
    root = Path(str(capture["capture_root"]))
    capture_id = str(capture["capture_id"])
    store = CaptureStore(root)
    chunk_id = store.list_chunk_ids(capture_id)[0]
    chunk_path = store.chunk_path(capture_id, chunk_id)
    value = json.loads(chunk_path.read_text(encoding="utf-8"))
    value["canonical_response_b64"] = "W10="
    chunk_path.write_text(json.dumps(value), encoding="utf-8")

    output = tmp_path / "tamper-run" / "verification.json"
    assert run_verification(manifest_path, output, repository_root=repository_root) == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    capture_check = next(item for item in result["checks"] if item["id"] == "capture-integrity")
    assert capture_check["status"] == "FAIL"


def test_verifier_refuses_existing_output_directory(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest, _ = _manifest(tmp_path, repository_root)
    output = tmp_path / "existing" / "verification.json"
    output.parent.mkdir()

    with pytest.raises(FileExistsError, match="already exists"):
        run_verification(manifest, output, repository_root=repository_root)


def test_verifier_rejects_sentinel_digest_without_trusting_declared_artifact(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest_path, manifest = _manifest(tmp_path, repository_root)
    qualifications = manifest["qualifications"]
    assert isinstance(qualifications, list)
    assert isinstance(qualifications[0], dict)
    qualifications[0]["report_digest"] = "sha256:" + "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "sentinel-run" / "verification.json"

    assert run_verification(manifest_path, output, repository_root=repository_root) == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    qualification = next(item for item in result["checks"] if item["id"] == "qualification-binding")
    assert qualification["status"] == "FAIL"


def test_verifier_requires_existing_evidence_manifest(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]

    with pytest.raises(FileNotFoundError):
        run_verification(
            tmp_path / "missing.json",
            tmp_path / "missing-run" / "verification.json",
            repository_root=repository_root,
        )


def test_verifier_documented_cli_fails_closed_without_real_manifest(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest, _ = _manifest(tmp_path, repository_root)
    output = tmp_path / "cli-run" / "verification.json"

    completed = subprocess.run(
        [
            sys.executable,
            "tools/verification/verify_phase_1a.py",
            "--evidence-manifest",
            str(manifest),
            "--output",
            str(output),
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 1
    assert output.is_file()

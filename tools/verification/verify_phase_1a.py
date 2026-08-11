"""Verify external real-provider qualification and sealed capture evidence for Phase 1a."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from astraquant_api.capture_repository import qualification_report_from_dict
from astraquant_data.capture import CapturePurpose
from astraquant_data.capture_store import CaptureStore
from astraquant_data.provider_identity import ProviderCapability
from astraquant_data.provider_qualification import ProviderApproval, QualificationReport
from astraquant_domain.run_manifest import RunClass, RunManifest, canonical_json_bytes

EVIDENCE_MANIFEST_SCHEMA = "astraquant.phase1a-evidence-manifest/v1"
_REQUIRED_CAPABILITIES = frozenset({ProviderCapability.DAILY_BARS, ProviderCapability.MINUTE_BARS})
_PHASE1C_CAPABILITIES = frozenset(
    {ProviderCapability.CORPORATE_ACTIONS, ProviderCapability.INSTRUMENT_STATUS}
)
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "evidence_class",
        "provider_vendor",
        "implementation_commit",
        "probe_captures",
        "qualifications",
        "captures",
        "reconciliations",
        "unqualified_capabilities",
    }
)
_SECRET_KEYS = frozenset(
    {"authorization", "cookie", "password", "secret", "session_token", "token"}
)
_COMMAND = [
    "uv",
    "run",
    "python",
    "tools/verification/verify_phase_1a.py",
    "--evidence-manifest",
    "<external>",
    "--output",
    "<artifact>",
]


class Phase1aVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    id: str
    status: str
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class QualificationBinding:
    report: QualificationReport
    approval: ProviderApproval


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    qualifications: Mapping[str, QualificationBinding]
    capture_ids: frozenset[str]
    captured_capabilities: frozenset[ProviderCapability]
    input_digests: Mapping[str, str]


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _digest(value: object) -> str:
    return _sha256_bytes(canonical_json_bytes(value))


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    if frozenset(value) != expected:
        raise Phase1aVerificationError(f"{label} keys do not match schema")


def _non_sentinel_digest(name: str, value: object) -> str:
    text = str(value)
    if (
        len(text) != 71
        or not text.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in text[7:])
        or text[7:] == "0" * 64
    ):
        raise Phase1aVerificationError(f"{name} must be a non-sentinel digest")
    return text


def _git_commit(repository_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    value = completed.stdout.strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise Phase1aVerificationError("git HEAD is not canonical")
    return value


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Phase1aVerificationError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise Phase1aVerificationError(f"{label} must be an object")
    return value


def _scan_secret_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in _SECRET_KEYS:
                raise Phase1aVerificationError("evidence manifest contains a secret-like key")
            _scan_secret_keys(item)
    elif isinstance(value, list):
        for item in value:
            _scan_secret_keys(item)


def _object_list(value: object, label: str) -> list[dict[str, Any]]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, dict) for item in value)
    ):
        raise Phase1aVerificationError(f"{label} must be a non-empty object list")
    return value


def _external_path(
    value: object,
    repository_root: Path,
    *,
    directory: bool,
    allow_repository_fixture: bool,
) -> Path:
    path = Path(str(value))
    if not path.is_absolute():
        raise Phase1aVerificationError("formal evidence paths must be absolute")
    resolved = path.resolve(strict=True)
    if not allow_repository_fixture and (
        resolved == repository_root or resolved.is_relative_to(repository_root)
    ):
        raise Phase1aVerificationError("repository fixtures cannot be formal evidence")
    if directory != resolved.is_dir():
        raise Phase1aVerificationError("formal evidence path type is invalid")
    return resolved


def _check(
    check_id: str,
    operation: Callable[[], dict[str, object]],
) -> VerificationCheck:
    try:
        details = operation()
    except Exception as error:
        return VerificationCheck(
            id=check_id,
            status="FAIL",
            details={"error_type": type(error).__name__, "reason": "evidence validation failed"},
        )
    return VerificationCheck(id=check_id, status="PASS", details=details)


def _manifest_contract(manifest: Mapping[str, Any]) -> dict[str, object]:
    _exact_keys(manifest, _TOP_LEVEL_KEYS, "evidence manifest")
    _scan_secret_keys(manifest)
    if manifest["schema_version"] != EVIDENCE_MANIFEST_SCHEMA:
        raise Phase1aVerificationError("unsupported evidence manifest schema")
    if manifest["provider_vendor"] != "eastmoney":
        raise Phase1aVerificationError("Phase 1a provider must be eastmoney")
    commit = str(manifest["implementation_commit"])
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise Phase1aVerificationError("implementation commit is invalid")
    _object_list(manifest["qualifications"], "qualifications")
    _object_list(manifest["probe_captures"], "probe captures")
    _object_list(manifest["captures"], "captures")
    _object_list(manifest["reconciliations"], "reconciliations")
    raw_unqualified = manifest["unqualified_capabilities"]
    if not isinstance(raw_unqualified, list) or len(raw_unqualified) != len(set(raw_unqualified)):
        raise Phase1aVerificationError("unqualified capabilities are invalid")
    return {"schema_version": EVIDENCE_MANIFEST_SCHEMA, "provider_vendor": "eastmoney"}


def _evidence_class(manifest: Mapping[str, Any]) -> dict[str, object]:
    if manifest["evidence_class"] != "REAL_API":
        raise Phase1aVerificationError("formal verification requires REAL_API evidence")
    return {"evidence_class": "REAL_API"}


def _git_binding(manifest: Mapping[str, Any], git_commit: str) -> dict[str, object]:
    if manifest["implementation_commit"] != git_commit:
        raise Phase1aVerificationError("manifest implementation commit does not match HEAD")
    return {"git_commit": git_commit}


def _qualification_bindings(
    manifest: Mapping[str, Any],
    repository_root: Path,
    probe_evidence: Mapping[str, frozenset[tuple[str, str]]],
) -> tuple[dict[str, QualificationBinding], dict[str, str]]:
    bindings: dict[str, QualificationBinding] = {}
    inputs: dict[str, str] = {}
    for entry in _object_list(manifest["qualifications"], "qualifications"):
        _exact_keys(
            entry,
            frozenset({"report_path", "report_digest", "approval", "approval_id"}),
            "qualification",
        )
        report_path = _external_path(
            entry["report_path"],
            repository_root,
            directory=False,
            allow_repository_fixture=manifest["evidence_class"] != "REAL_API",
        )
        report_digest = _non_sentinel_digest("report_digest", entry["report_digest"])
        payload = _read_object(report_path, "qualification report")
        if payload.get("report_digest") != report_digest:
            raise Phase1aVerificationError("qualification report digest field drift")
        report = qualification_report_from_dict(payload)
        if canonical_json_bytes(payload) != canonical_json_bytes(
            {**report.to_dict(), "report_digest": report.report_digest}
        ):
            raise Phase1aVerificationError("qualification report artifact is not canonical")
        if report.report_digest != report_digest or not report.approvable:
            raise Phase1aVerificationError("qualification report is not approvable or exact")
        if report.identity.vendor != "eastmoney":
            raise Phase1aVerificationError("qualification vendor drift")
        available_probes = probe_evidence.get(report.identity.identity_digest, frozenset())
        required_probes = {
            (probe.request_digest, probe.raw_response_digest) for probe in report.probes
        }
        if not required_probes or not required_probes.issubset(available_probes):
            raise Phase1aVerificationError("qualification probes lack sealed raw evidence")
        raw_approval = entry["approval"]
        if not isinstance(raw_approval, dict):
            raise Phase1aVerificationError("approval must be an object")
        _exact_keys(
            raw_approval,
            frozenset(
                {
                    "identity_digest",
                    "report_digest",
                    "reviewer",
                    "policy_version",
                    "effective_at",
                }
            ),
            "approval",
        )
        approval = ProviderApproval(
            identity_digest=str(raw_approval["identity_digest"]),
            report_digest=str(raw_approval["report_digest"]),
            reviewer=str(raw_approval["reviewer"]),
            policy_version=str(raw_approval["policy_version"]),
            effective_at=datetime.fromisoformat(str(raw_approval["effective_at"])),
        )
        approval_id = _non_sentinel_digest("approval_id", entry["approval_id"])
        if approval.approval_id != approval_id:
            raise Phase1aVerificationError("approval digest drift")
        if (
            approval.identity_digest != report.identity.identity_digest
            or approval.report_digest != report.report_digest
        ):
            raise Phase1aVerificationError("approval does not bind exact report identity")
        if approval_id in bindings:
            raise Phase1aVerificationError("duplicate approval id")
        bindings[approval_id] = QualificationBinding(report=report, approval=approval)
        inputs[f"qualification:{report_digest}"] = report_digest
        inputs[f"approval:{approval_id}"] = approval_id
    return bindings, inputs


def _qualification_probe_integrity(
    manifest: Mapping[str, Any],
    repository_root: Path,
) -> tuple[dict[str, frozenset[tuple[str, str]]], dict[str, str]]:
    evidence: dict[str, set[tuple[str, str]]] = {}
    inputs: dict[str, str] = {}
    for entry in _object_list(manifest["probe_captures"], "probe captures"):
        _exact_keys(
            entry,
            frozenset({"capture_root", "capture_id", "seal_digest", "identity_digest"}),
            "probe capture",
        )
        root = _external_path(
            entry["capture_root"],
            repository_root,
            directory=True,
            allow_repository_fixture=manifest["evidence_class"] != "REAL_API",
        )
        capture_id = _non_sentinel_digest("probe capture_id", entry["capture_id"])
        seal_digest = _non_sentinel_digest("probe seal_digest", entry["seal_digest"])
        identity_digest = _non_sentinel_digest("probe identity_digest", entry["identity_digest"])
        store = CaptureStore(root)
        envelope = store.read(capture_id)
        if (
            envelope.seal_digest != seal_digest
            or envelope.plan.purpose is not CapturePurpose.QUALIFICATION_PROBE
            or envelope.plan.identity_digest != identity_digest
        ):
            raise Phase1aVerificationError("qualification probe capture binding drift")
        pairs = evidence.setdefault(identity_digest, set())
        for chunk_id in envelope.chunk_ids:
            chunk = store.read_chunk(capture_id, chunk_id)
            pairs.add((chunk.request_digest, chunk.response_digest))
        inputs[f"probe-capture:{capture_id}"] = capture_id
        inputs[f"probe-seal:{capture_id}"] = seal_digest
    return {key: frozenset(value) for key, value in evidence.items()}, inputs


def _capture_integrity(
    manifest: Mapping[str, Any],
    repository_root: Path,
    qualifications: Mapping[str, QualificationBinding],
) -> tuple[frozenset[str], frozenset[ProviderCapability], dict[str, str]]:
    capture_ids: set[str] = set()
    capabilities: set[ProviderCapability] = set()
    inputs: dict[str, str] = {}
    for entry in _object_list(manifest["captures"], "captures"):
        _exact_keys(
            entry,
            frozenset({"capture_root", "capture_id", "seal_digest", "capability"}),
            "capture",
        )
        root = _external_path(
            entry["capture_root"],
            repository_root,
            directory=True,
            allow_repository_fixture=manifest["evidence_class"] != "REAL_API",
        )
        capture_id = _non_sentinel_digest("capture_id", entry["capture_id"])
        seal_digest = _non_sentinel_digest("seal_digest", entry["seal_digest"])
        capability = ProviderCapability(str(entry["capability"]))
        envelope = CaptureStore(root).read(capture_id)
        if envelope.seal_digest != seal_digest:
            raise Phase1aVerificationError("capture seal digest drift")
        plan = envelope.plan
        if plan.approval_id is None or plan.approval_id not in qualifications:
            raise Phase1aVerificationError("capture approval is absent from manifest")
        binding = qualifications[plan.approval_id]
        if (
            plan.identity_digest != binding.report.identity.identity_digest
            or plan.report_digest != binding.report.report_digest
            or plan.endpoint != binding.report.identity.endpoint
            or capability is not binding.report.identity.capability
            or plan.started_at < binding.approval.effective_at
            or plan.command_digest is None
        ):
            raise Phase1aVerificationError("capture qualification binding drift")
        if capture_id in capture_ids:
            raise Phase1aVerificationError("duplicate capture id")
        capture_ids.add(capture_id)
        capabilities.add(capability)
        inputs[f"capture:{capture_id}"] = capture_id
        inputs[f"seal:{capture_id}"] = seal_digest
    return frozenset(capture_ids), frozenset(capabilities), inputs


def _reconciliation_integrity(
    manifest: Mapping[str, Any],
    repository_root: Path,
    capture_ids: frozenset[str],
) -> dict[str, str]:
    inputs: dict[str, str] = {}
    for entry in _object_list(manifest["reconciliations"], "reconciliations"):
        _exact_keys(
            entry,
            frozenset({"capture_root", "report_digest"}),
            "reconciliation",
        )
        root = _external_path(
            entry["capture_root"],
            repository_root,
            directory=True,
            allow_repository_fixture=manifest["evidence_class"] != "REAL_API",
        )
        report_digest = _non_sentinel_digest("reconciliation digest", entry["report_digest"])
        report = CaptureStore(root).read_reconciliation(report_digest)
        if (
            report.left_capture_id not in capture_ids
            or report.right_capture_id not in capture_ids
            or report.left_capture_id == report.right_capture_id
            or report.status.value != "MATCH"
        ):
            raise Phase1aVerificationError("reconciliation does not prove matching captures")
        inputs[f"reconciliation:{report_digest}"] = report_digest
    return inputs


def _required_capabilities(
    manifest: Mapping[str, Any],
    captured: frozenset[ProviderCapability],
) -> dict[str, object]:
    if not _REQUIRED_CAPABILITIES.issubset(captured):
        raise Phase1aVerificationError("daily and minute captures are required")
    try:
        unqualified = {
            ProviderCapability(str(item)) for item in manifest["unqualified_capabilities"]
        }
    except (TypeError, ValueError) as error:
        raise Phase1aVerificationError("unqualified capability is unknown") from error
    if not _PHASE1C_CAPABILITIES.issubset(unqualified):
        raise Phase1aVerificationError("Phase 1c capabilities must remain explicitly unqualified")
    if captured.intersection(unqualified):
        raise Phase1aVerificationError("captured and unqualified capability sets overlap")
    return {
        "captured_capabilities": sorted(item.value for item in captured),
        "unqualified_capabilities": sorted(item.value for item in unqualified),
    }


def _repository_policy(repository_root: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "tools/repository_policy.py"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        raise Phase1aVerificationError("repository policy failed")
    return {"exit_code": 0}


def _verification_manifest(git_commit: str, inputs: Mapping[str, str]) -> RunManifest:
    return RunManifest(
        run_class=RunClass.TEST,
        code_digest=_digest({"git_commit": git_commit}),
        environment_digest=_digest("phase1a-verifier-python-3.12-uv"),
        input_digests=dict(inputs),
        config_digest=_digest("phase1a-verifier-config-v1"),
        randomness_digest=_digest("phase1a-verifier-no-randomness"),
        event_order_policy_digest=_digest("phase1a-verifier-check-order-v1"),
        matcher_policy_digest=_digest("phase1a-verifier-no-matcher"),
        vintage_policy_digest=_digest("phase1a-verifier-no-vintage"),
        policy_digests={"report": _digest("phase1a-verification-report-v1")},
    ).seal()


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def run_verification(
    evidence_manifest: Path,
    output: Path,
    *,
    repository_root: Path,
    created_at: datetime | None = None,
) -> int:
    output = output.resolve()
    repository_root = repository_root.resolve()
    if output.parent.exists():
        raise FileExistsError("verification output directory already exists")
    manifest_path = evidence_manifest.resolve(strict=True)
    manifest_bytes = manifest_path.read_bytes()
    manifest = _read_object(manifest_path, "evidence manifest")
    if manifest.get("evidence_class") == "REAL_API" and (
        manifest_path == repository_root or manifest_path.is_relative_to(repository_root)
    ):
        raise Phase1aVerificationError("repository fixtures cannot be formal evidence manifests")
    git_commit = _git_commit(repository_root)
    checks: list[VerificationCheck] = []
    checks.append(_check("manifest-contract", lambda: _manifest_contract(manifest)))
    checks.append(_check("evidence-class-real-api", lambda: _evidence_class(manifest)))
    checks.append(_check("implementation-commit-bound", lambda: _git_binding(manifest, git_commit)))

    inputs: dict[str, str] = {"evidence-manifest": _sha256_bytes(manifest_bytes)}
    probe_evidence: dict[str, frozenset[tuple[str, str]]] = {}
    try:
        probe_evidence, probe_inputs = _qualification_probe_integrity(manifest, repository_root)
        inputs.update(probe_inputs)
        checks.append(
            VerificationCheck(
                "qualification-probe-integrity",
                "PASS",
                {
                    "identity_count": len(probe_evidence),
                    "probe_count": sum(len(items) for items in probe_evidence.values()),
                },
            )
        )
    except Exception as error:
        checks.append(
            VerificationCheck(
                "qualification-probe-integrity",
                "FAIL",
                {"error_type": type(error).__name__, "reason": "evidence validation failed"},
            )
        )
    qualifications: dict[str, QualificationBinding] = {}
    try:
        qualifications, qualification_inputs = _qualification_bindings(
            manifest, repository_root, probe_evidence
        )
        inputs.update(qualification_inputs)
        checks.append(
            VerificationCheck(
                "qualification-binding",
                "PASS",
                {
                    "qualification_count": len(qualifications),
                    "capabilities": sorted(
                        item.report.identity.capability.value for item in qualifications.values()
                    ),
                },
            )
        )
    except Exception as error:
        checks.append(
            VerificationCheck(
                "qualification-binding",
                "FAIL",
                {"error_type": type(error).__name__, "reason": "evidence validation failed"},
            )
        )

    capture_ids: frozenset[str] = frozenset()
    captured_capabilities: frozenset[ProviderCapability] = frozenset()
    try:
        capture_ids, captured_capabilities, capture_inputs = _capture_integrity(
            manifest, repository_root, qualifications
        )
        inputs.update(capture_inputs)
        checks.append(
            VerificationCheck(
                "capture-integrity",
                "PASS",
                {
                    "capture_count": len(capture_ids),
                    "capabilities": sorted(item.value for item in captured_capabilities),
                },
            )
        )
    except Exception as error:
        checks.append(
            VerificationCheck(
                "capture-integrity",
                "FAIL",
                {"error_type": type(error).__name__, "reason": "evidence validation failed"},
            )
        )

    try:
        reconciliation_inputs = _reconciliation_integrity(manifest, repository_root, capture_ids)
        inputs.update(reconciliation_inputs)
        checks.append(
            VerificationCheck(
                "reconciliation-integrity",
                "PASS",
                {"reconciliation_count": len(reconciliation_inputs)},
            )
        )
    except Exception as error:
        checks.append(
            VerificationCheck(
                "reconciliation-integrity",
                "FAIL",
                {"error_type": type(error).__name__, "reason": "evidence validation failed"},
            )
        )

    checks.append(
        _check(
            "required-capabilities",
            lambda: _required_capabilities(manifest, captured_capabilities),
        )
    )
    checks.append(_check("repository-policy-clean", lambda: _repository_policy(repository_root)))
    run_manifest = _verification_manifest(git_commit, inputs)
    passed = all(check.status == "PASS" for check in checks)
    exit_code = 0 if passed else 1
    report = {
        "phase": "phase-1a",
        "git_commit": git_commit,
        "evidence_manifest_digest": inputs["evidence-manifest"],
        "run_manifest_digest": run_manifest.manifest_digest,
        "sealed_input_digests": sorted(run_manifest.input_digests.values()),
        "commands": [{"argv": _COMMAND, "exit_code": exit_code}],
        "checks": [asdict(check) for check in checks],
        "created_at": _iso_z(created_at or datetime.now(UTC)),
    }
    output.parent.mkdir(parents=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    repository_root = Path(__file__).resolve().parents[2]
    return run_verification(
        arguments.evidence_manifest,
        arguments.output,
        repository_root=repository_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())

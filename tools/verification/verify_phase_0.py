"""Generate the machine-readable Phase 0 legacy quarantine verification report."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from astraquant_api.config import RuntimeConfig
from astraquant_api.formal_admission import FormalAdmissionService
from astraquant_data.evidence import (
    EvidenceRef,
    EvidenceRole,
    FormalAdmissionError,
)
from astraquant_domain.run_manifest import RunClass, RunManifest, UnsealedRunManifestError
from tools.repository_policy import (
    find_forbidden_content,
    find_forbidden_paths,
    tracked_files,
)

_AUTHORITY_ID = "phase0-verifier-test-authority"
_COMMAND = ["uv", "run", "python", "tools/verification/verify_phase_0.py"]


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    id: str
    status: str
    details: dict[str, object]


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


def _git_commit(repository_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    commit = completed.stdout.strip()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError("git HEAD must be a canonical 40-character SHA")
    return commit


def _run_manifest(
    run_class: RunClass,
    roots: tuple[EvidenceRef, ...],
    *,
    sealed: bool = True,
) -> RunManifest:
    input_digests = {
        root.artifact_id or f"missing:{index}": root.content_digest
        for index, root in enumerate(roots)
    }
    manifest = RunManifest(
        run_class=run_class,
        code_digest=_digest("phase0-negative-case-code"),
        environment_digest=_digest("phase0-negative-case-environment"),
        input_digests=input_digests,
        config_digest=_digest("phase0-negative-case-config"),
        randomness_digest=_digest("phase0-negative-case-randomness"),
        event_order_policy_digest=_digest("phase0-negative-case-event-order"),
        matcher_policy_digest=_digest("phase0-negative-case-matcher"),
        vintage_policy_digest=_digest("phase0-negative-case-vintage"),
        policy_digests={"admission": _digest("phase0-negative-case-admission")},
    )
    return manifest.seal() if sealed else manifest


def _verification_manifest(git_commit: str) -> RunManifest:
    return RunManifest(
        run_class=RunClass.TEST,
        code_digest=_digest(f"git-commit:{git_commit}"),
        environment_digest=_digest("phase0-verifier-python-3.12-uv"),
        input_digests={
            "git-tree": _digest(f"git-tree:{git_commit}"),
            "verification-policy": _digest("phase0-legacy-quarantine-policy-v1"),
        },
        config_digest=_digest("phase0-verifier-config-v1"),
        randomness_digest=_digest("phase0-verifier-no-randomness"),
        event_order_policy_digest=_digest("phase0-verifier-check-order-v1"),
        matcher_policy_digest=_digest("phase0-verifier-no-matcher"),
        vintage_policy_digest=_digest("phase0-verifier-no-vintage"),
        policy_digests={"report": _digest("phase0-verification-report-v1")},
    ).seal()


def _expect_rejected(
    check_id: str,
    expected_error: type[Exception],
    expected_message: str,
    operation: Callable[[], object],
) -> VerificationCheck:
    try:
        operation()
    except expected_error as error:
        if expected_message not in str(error):
            return VerificationCheck(
                id=check_id,
                status="FAIL",
                details={
                    "reason": "unexpected error message",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
            )
        return VerificationCheck(
            id=check_id,
            status="PASS",
            details={"error_type": type(error).__name__, "message": str(error)},
        )
    except Exception as error:
        return VerificationCheck(
            id=check_id,
            status="FAIL",
            details={"error_type": type(error).__name__, "message": str(error)},
        )
    return VerificationCheck(
        id=check_id,
        status="FAIL",
        details={"reason": "formal admission unexpectedly succeeded"},
    )


def _admission_checks() -> list[VerificationCheck]:
    service = FormalAdmissionService(approved_authority_ids={_AUTHORITY_ID})

    renamed_fixture = EvidenceRef.fixture(
        "renamed-real-api.parquet",
        _digest("renamed-fixture"),
    )
    unknown_parent = EvidenceRef.from_manifest_metadata(
        artifact_id="unknown-parent-v2",
        digest=_digest("unknown-parent"),
        manifest_schema_version=2,
        evidence_class="UNKNOWN_CLASS",
        role=EvidenceRole.MARKET.value,
        parents=(),
        approval_id=None,
        sealed=True,
    )
    unknown_derived = EvidenceRef.derived(
        artifact_id="derived-with-unknown-parent-v2",
        digest=_digest("derived-with-unknown-parent"),
        parents=(unknown_parent,),
    )
    approved_market = EvidenceRef.real_api_market(
        artifact_id="synthetic-contract-object-v2",
        approval_id=_AUTHORITY_ID,
        digest=_digest("synthetic-contract-object"),
    )
    mixed_derived = EvidenceRef.derived(
        artifact_id="derived-with-mixed-parents-v2",
        digest=_digest("derived-with-mixed-parents"),
        parents=(approved_market, renamed_fixture),
    )
    latest = EvidenceRef.real_api_market(
        artifact_id="latest",
        approval_id=_AUTHORITY_ID,
        digest=_digest("mutable-latest-contract-object"),
    )

    checks = [
        _expect_rejected(
            "renamed-fixture-rejected",
            FormalAdmissionError,
            "TEST_ONLY",
            lambda: service.admit_run(
                _run_manifest(RunClass.FORMAL, (renamed_fixture,)),
                evidence_roots=(renamed_fixture,),
            ),
        ),
        _expect_rejected(
            "unknown-ancestor-rejected",
            FormalAdmissionError,
            "LEGACY_UNVERIFIED",
            lambda: service.admit_run(
                _run_manifest(RunClass.FORMAL, (unknown_derived,)),
                evidence_roots=(unknown_derived,),
            ),
        ),
        _expect_rejected(
            "mixed-ancestor-rejected",
            FormalAdmissionError,
            "TEST_ONLY",
            lambda: service.admit_run(
                _run_manifest(RunClass.FORMAL, (mixed_derived,)),
                evidence_roots=(mixed_derived,),
            ),
        ),
        _expect_rejected(
            "unsealed-run-rejected",
            UnsealedRunManifestError,
            "SEALED",
            lambda: service.admit_run(
                _run_manifest(RunClass.FORMAL, (approved_market,), sealed=False),
                evidence_roots=(approved_market,),
            ),
        ),
        _expect_rejected(
            "mutable-latest-rejected",
            FormalAdmissionError,
            "mutable alias",
            lambda: service.admit_run(
                _run_manifest(RunClass.FORMAL, (latest,)),
                evidence_roots=(latest,),
            ),
        ),
    ]

    selection = service.select_formal_model()
    model_passed = (
        selection.decision.value == "HOLD"
        and not selection.allow_new_orders
        and selection.model_id is None
    )
    checks.append(
        VerificationCheck(
            id="legacy-model-hold",
            status="PASS" if model_passed else "FAIL",
            details={
                "decision": selection.decision.value,
                "allow_new_orders": selection.allow_new_orders,
                "model_id": selection.model_id,
                "reason": selection.reason,
            },
        )
    )
    return checks


def _formal_roots_check(repository_root: Path) -> VerificationCheck:
    temp_parent = repository_root / ".astraquant" / "test-tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="phase0-verifier-", dir=temp_parent) as directory:
        state_dir = Path(directory) / "state"
        config = RuntimeConfig(session_token="x" * 43, state_dir=state_dir)
        config.prepare_directories()
        roots = (
            config.legacy_data_root,
            config.formal_qualification_root,
            config.formal_capture_root,
            config.formal_publication_root,
            config.formal_verification_root,
        )
        canonical = tuple(path.resolve() for path in roots)
        separated = len(set(canonical)) == len(canonical) and all(
            first not in second.parents and second not in first.parents
            for index, first in enumerate(canonical)
            for second in canonical[index + 1 :]
        )
        qualification_is_formal = (
            config.formal_qualification_root.parent == config.formal_root
            and config.formal_qualification_root != state_dir / "qualification"
        )
    return VerificationCheck(
        id="formal-roots-separated",
        status="PASS" if separated and qualification_is_formal else "FAIL",
        details={
            "root_names": [
                "legacy_data",
                "formal_qualification",
                "formal_capture",
                "formal_publication",
                "formal_verification",
            ],
            "qualification_under_formal_root": qualification_is_formal,
        },
    )


def _repository_policy_check(repository_root: Path) -> VerificationCheck:
    paths = tracked_files()
    file_sizes = {
        path: (repository_root / path).stat().st_size
        for path in paths
        if (repository_root / path).is_file()
    }
    forbidden = find_forbidden_paths(paths, file_sizes=file_sizes)
    contents: dict[str, str] = {}
    for path in paths:
        candidate = repository_root / path
        if not candidate.is_file() or candidate.stat().st_size > 1_000_000:
            continue
        try:
            contents[path] = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    forbidden.extend(find_forbidden_content(contents))
    forbidden = list(dict.fromkeys(forbidden))
    return VerificationCheck(
        id="repository-policy-clean",
        status="PASS" if not forbidden else "FAIL",
        details={"tracked_file_count": len(paths), "forbidden_paths": forbidden},
    )


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def run_verification(
    output: Path,
    *,
    repository_root: Path,
    created_at: datetime | None = None,
) -> int:
    output = output.resolve()
    repository_root = repository_root.resolve()
    if output.parent.exists():
        raise FileExistsError("verification output directory already exists")

    git_commit = _git_commit(repository_root)
    manifest = _verification_manifest(git_commit)
    checks = [
        *_admission_checks(),
        _formal_roots_check(repository_root),
        _repository_policy_check(repository_root),
    ]
    passed = all(check.status == "PASS" for check in checks)
    exit_code = 0 if passed else 1
    report = {
        "phase": "phase-0",
        "git_commit": git_commit,
        "run_manifest_digest": manifest.manifest_digest,
        "sealed_input_digests": sorted(manifest.input_digests.values()),
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
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    repository_root = Path(__file__).resolve().parents[2]
    return run_verification(arguments.output, repository_root=repository_root)


if __name__ == "__main__":
    raise SystemExit(main())

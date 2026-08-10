from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.verification.verify_phase_0 import run_verification

EXPECTED_CHECKS = {
    "renamed-fixture-rejected",
    "unknown-ancestor-rejected",
    "mixed-ancestor-rejected",
    "unsealed-run-rejected",
    "mutable-latest-rejected",
    "legacy-model-hold",
    "formal-roots-separated",
    "repository-policy-clean",
}


def test_phase_0_verifier_writes_a_complete_non_sentinel_report(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "run-id" / "verification.json"

    exit_code = run_verification(
        output,
        repository_root=repository_root,
        created_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["phase"] == "phase-0"
    assert re.fullmatch(r"[0-9a-f]{40}", report["git_commit"])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", report["run_manifest_digest"])
    assert report["run_manifest_digest"] != f"sha256:{'0' * 64}"
    assert report["sealed_input_digests"]
    assert all(
        re.fullmatch(r"sha256:[0-9a-f]{64}", digest) and digest != f"sha256:{'0' * 64}"
        for digest in report["sealed_input_digests"]
    )
    assert {check["id"] for check in report["checks"]} == EXPECTED_CHECKS
    assert {check["status"] for check in report["checks"]} == {"PASS"}
    legacy_model = next(check for check in report["checks"] if check["id"] == "legacy-model-hold")
    assert legacy_model["details"]["allow_new_orders"] is False
    assert legacy_model["details"]["model_id"] is None
    assert report["commands"] == [
        {
            "argv": ["uv", "run", "python", "tools/verification/verify_phase_0.py"],
            "exit_code": 0,
        }
    ]
    assert report["created_at"] == "2026-08-10T12:00:00Z"


def test_phase_0_verifier_refuses_to_reuse_an_output_directory(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "run-id" / "verification.json"
    output.parent.mkdir(parents=True)

    with pytest.raises(
        FileExistsError,
        match="verification output directory already exists",
    ):
        run_verification(
            output,
            repository_root=repository_root,
            created_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        )


def test_phase_0_verifier_runs_through_its_documented_script_entrypoint(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "cli-run" / "verification.json"

    completed = subprocess.run(
        [
            sys.executable,
            "tools/verification/verify_phase_0.py",
            "--output",
            str(output),
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.is_file()

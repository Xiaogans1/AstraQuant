import os
import re
import subprocess
from pathlib import Path


def test_verify_script_defines_scopes_unique_temp_and_fail_fast_commands() -> None:
    script = Path("scripts/verify.ps1").read_text(encoding="utf-8")

    assert '[ValidateSet("Python", "Desktop", "Rust", "All")]' in script
    assert '[guid]::NewGuid().ToString("n")' in script
    assert "--basetemp" in script
    assert "Invoke-Checked" in script
    assert "if ($exitCode -ne 0)" in script

    normalized = re.sub(r"\s+", " ", script)
    for invocation in (
        '-FilePath "uv" -ArgumentList @("run", "pytest", "-q"',
        '-FilePath "uv" -ArgumentList @("run", "ruff", "check", ".")',
        '-FilePath "uv" -ArgumentList @("run", "ruff", "format", "--check", ".")',
        '-FilePath "uv" -ArgumentList @("run", "mypy")',
        '-FilePath "uv" -ArgumentList @("run", "python", "tools/repository_policy.py")',
        '-FilePath "pnpm" -ArgumentList @("--dir", "apps/desktop", "test")',
        '-FilePath "pnpm" -ArgumentList @("--dir", "apps/desktop", "check")',
        '-FilePath "pnpm" -ArgumentList @("--dir", "apps/desktop", "build")',
        '-FilePath "cargo" -ArgumentList @("fmt"',
        '-FilePath "cargo" -ArgumentList @("clippy"',
        '-FilePath "cargo" -ArgumentList @("test"',
    ):
        assert invocation in normalized


def test_ci_uses_pinned_toolchains_and_only_the_shared_verifier() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "windows-latest" in workflow
    assert "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09" in workflow
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in workflow
    assert "astral-sh/setup-uv@94527f2e458b27549849d47d273a16bec83a01e9" in workflow
    assert "actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444" in workflow
    assert "dtolnay/rust-toolchain@6c977a6ca4077a0ceb28ffbe03f59d46e9ac8772" in workflow
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in workflow
    assert "python-version: '3.12'" in workflow
    assert "version: '0.11.32'" in workflow
    assert "node-version: '24'" in workflow
    assert "package-manager-cache: false" in workflow
    assert "pnpm@11.9.0" in workflow
    assert "toolchain: 1.96.0" in workflow
    assert "./scripts/verify.ps1 -Scope All" in workflow
    assert workflow.count("./scripts/verify.ps1") == 1
    assert "include-hidden-files: true" in workflow
    for forbidden_duplicate in (
        "uv run pytest",
        "uv run ruff",
        "uv run mypy",
        "pnpm --dir apps/desktop test",
        "cargo test",
    ):
        assert forbidden_duplicate not in workflow


def test_verify_script_allows_native_stderr_when_exit_code_is_zero(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "pnpm.cmd").write_text(
        "@echo off\r\necho harmless native stderr 1>&2\r\nexit /b 0\r\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/verify.ps1",
            "-Scope",
            "Desktop",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "harmless native stderr" in output
    assert "NativeCommandError" not in output

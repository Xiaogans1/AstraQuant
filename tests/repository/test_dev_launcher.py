import json
from pathlib import Path


def test_windows_dev_launcher_prepares_dependencies_and_starts_tauri() -> None:
    script = Path("scripts/dev.ps1").read_text(encoding="utf-8")

    assert "uv sync --locked --all-packages" in script
    assert "Invoke-Pnpm install --frozen-lockfile" in script
    assert "npm --prefix apps/desktop run tauri -- dev" in script
    assert "Get-Command corepack" in script
    assert "Required development command is missing: pnpm" not in script
    assert "Start-Process" not in script


def test_tauri_development_commands_do_not_require_global_pnpm() -> None:
    config = json.loads(Path("apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))

    assert config["build"]["beforeDevCommand"] == "npm run dev"
    assert config["build"]["beforeBuildCommand"] == "npm run build"


def test_root_launcher_finds_the_active_development_worktree() -> None:
    script = Path("start.ps1").read_text(encoding="utf-8")

    assert ".worktrees" in script
    assert "phase-1-desktop-platform" in script
    assert "scripts\\dev.ps1" in script

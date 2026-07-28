from pathlib import Path


def test_windows_dev_launcher_prepares_dependencies_and_starts_tauri() -> None:
    script = Path("scripts/dev.ps1").read_text(encoding="utf-8")

    assert "uv sync --locked --all-packages" in script
    assert "Invoke-Pnpm install --frozen-lockfile" in script
    assert "Invoke-Pnpm dev" in script
    assert "Get-Command corepack" in script
    assert "Required development command is missing: pnpm" not in script
    assert "Start-Process" not in script

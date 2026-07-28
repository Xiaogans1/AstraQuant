from pathlib import Path


def test_windows_dev_launcher_prepares_dependencies_and_starts_tauri() -> None:
    script = Path("scripts/dev.ps1").read_text(encoding="utf-8")

    assert "uv sync --locked --all-packages" in script
    assert "pnpm install --frozen-lockfile" in script
    assert "pnpm dev" in script
    assert "Start-Process" not in script

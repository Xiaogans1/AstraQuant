from pathlib import Path


def test_rust_runtime_tests_build_their_own_managed_environment() -> None:
    manifest = Path("apps/desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    runtime = Path("apps/desktop/src-tauri/src/runtime.rs").read_text(encoding="utf-8")

    assert "[dev-dependencies]" in manifest
    assert 'tempfile = "3.23"' in manifest
    assert "fn managed_project_root()" in runtime
    assert "runtime_launch_spec(&project_root())" not in runtime

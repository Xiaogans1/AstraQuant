import inspect
from pathlib import Path

from astraquant_api.data_worker import run_data_import_worker


def test_rust_runtime_tests_build_their_own_managed_environment() -> None:
    manifest = Path("apps/desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    runtime = Path("apps/desktop/src-tauri/src/runtime.rs").read_text(encoding="utf-8")

    assert "[dev-dependencies]" in manifest
    assert 'tempfile = "3.23"' in manifest
    assert "fn managed_project_root()" in runtime
    assert "runtime_launch_spec(&project_root())" not in runtime


def test_data_worker_has_no_database_writer_capability() -> None:
    source = Path("packages/api/src/astraquant_api/data_worker.py").read_text(encoding="utf-8")
    parameters = inspect.signature(run_data_import_worker).parameters

    assert "astraquant_api.database" not in source
    assert "DataCatalogRepository" not in source
    assert "sqlalchemy" not in source.casefold()
    assert "database_url" not in source
    assert "state_dir_value" not in parameters
    assert "legacy_data_root_value" in parameters

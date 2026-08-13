from __future__ import annotations

from pathlib import Path

import pytest
from astraquant_kronos_runner import __main__ as cli
from astraquant_kronos_runner.runner import KronosBackend

from tests.fakes import RecordingBackend


def test_cli_passes_only_explicit_paths_to_backend_and_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = tmp_path / "request.json"
    output = tmp_path / "response.json"
    root = tmp_path / "run-root"
    upstream = tmp_path / "Kronos"
    request.write_text("{}", encoding="utf-8")
    backend = RecordingBackend()
    observed: dict[str, object] = {}

    def backend_factory(
        request_path: Path, *, root: Path, upstream_root: Path
    ) -> KronosBackend:
        observed["factory"] = (request_path, root, upstream_root)
        return backend

    def fake_run(
        request_path: Path, output_path: Path, *, root: Path, backend: KronosBackend
    ) -> None:
        observed["run"] = (request_path, output_path, root, backend)

    monkeypatch.setattr(cli, "run_request", fake_run)
    status = cli.main(
        [
            "--request",
            str(request),
            "--output",
            str(output),
            "--root",
            str(root),
            "--upstream-root",
            str(upstream),
        ],
        backend_factory=backend_factory,
    )

    assert status == 0
    assert observed == {
        "factory": (request, root, upstream),
        "run": (request, output, root, backend),
    }

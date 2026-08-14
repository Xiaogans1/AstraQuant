from __future__ import annotations

from pathlib import Path

from tests.data.test_stage_b_v2_stockmixer_export import _sources

from tools.research.build_stage_b_v2_stockmixer_request import main


def test_cli_builds_exact_temporal_panel(tmp_path: Path) -> None:
    raw, materialization = _sources(tmp_path / "source")
    output = tmp_path / "output"

    assert (
        main(
            [
                str(raw),
                str(materialization),
                "--output-root",
                str(output),
            ]
        )
        == 0
    )
    assert (output / "manifest.json").is_file()
    assert (output / "temporal-panel.parquet").is_file()
    assert (output / "rows.parquet").is_file()


def test_cli_fails_closed_without_exact_source(tmp_path: Path) -> None:
    output = tmp_path / "output"

    assert (
        main(
            [
                str(tmp_path / "missing-raw"),
                str(tmp_path / "missing-materialization"),
                "--output-root",
                str(output),
            ]
        )
        == 1
    )
    assert not output.exists()

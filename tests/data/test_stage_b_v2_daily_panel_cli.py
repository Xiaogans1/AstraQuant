from __future__ import annotations

import json
from pathlib import Path

from astraquant_data.daily_panel import DailyPanelSource
from tools.research.build_stage_b_v2_daily_panel import main

from .factories import make_bar
from .test_daily_panel import _sources


def _request(
    path: Path,
    sources: tuple[DailyPanelSource, DailyPanelSource, DailyPanelSource],
) -> Path:
    first, second, benchmark = sources
    sessions = [make_bar(day=day).event_time.isoformat() for day in (24, 25, 26)]
    payload = {
        "schema_version": "astraquant.stage-b-v2-daily-panel-request/v1",
        "benchmark": {
            "dataset_id": benchmark.dataset_id,
            "instrument_id": benchmark.instrument_id,
            "snapshot_id": benchmark.snapshot_id,
        },
        "sources": [
            {
                "dataset_id": source.dataset_id,
                "instrument_id": source.instrument_id,
                "snapshot_id": source.snapshot_id,
            }
            for source in (second, first)
        ],
        "universe": {
            "snapshot_digest": f"sha256:{'f' * 64}",
            "members_by_time": [
                {
                    "decision_time": session,
                    "members": [first.instrument_id, second.instrument_id],
                }
                for session in sessions
            ],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_daily_panel_cli_is_repeatable_and_records_exact_inputs(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    sources = _sources(data_root)
    request = _request(tmp_path / "request.json", sources)

    first = tmp_path / "first"
    second = tmp_path / "second"
    assert main([str(request), "--data-root", str(data_root), "--output-root", str(first)]) == 0
    assert main([str(request), "--data-root", str(data_root), "--output-root", str(second)]) == 0

    first_manifest = first / "panel.json"
    assert first_manifest.read_bytes() == (second / "panel.json").read_bytes()
    payload = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "astraquant.stage-b-v2-daily-panel/v1"
    assert payload["instrument_count"] == 2
    assert payload["session_count"] == 4
    assert payload["content_digest"].startswith("sha256:")
    assert payload["request"]["sources"][0]["instrument_id"] == "000001.SZSE"


def test_daily_panel_cli_rejects_latest_without_writing_output(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    sources = _sources(data_root)
    request = _request(tmp_path / "request.json", sources)
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["sources"][0]["snapshot_id"] = "latest"
    request.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "invalid-output"

    assert main([str(request), "--data-root", str(data_root), "--output-root", str(output)]) == 2
    assert not output.exists()

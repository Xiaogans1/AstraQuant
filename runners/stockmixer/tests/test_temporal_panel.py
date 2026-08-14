from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch
from astraquant_stockmixer_runner.contracts import canonical_digest
from astraquant_stockmixer_runner.temporal_panel import (
    build_temporal_batch,
    load_temporal_panel,
)

TEMPORAL_COLUMNS = (
    "open_relative",
    "high_relative",
    "low_relative",
    "close_relative",
    "log_volume_change",
    "log_turnover_change",
)


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _panel(root: Path) -> Path:
    root.mkdir()
    start = datetime(2020, 1, 2, 7, tzinfo=UTC)
    panel_rows = []
    for session in range(4):
        timestamp = start + timedelta(days=session)
        for instrument_index, instrument_id in enumerate(("AAA.SSE", "BBB.SSE")):
            feature_mask = not (session == 1 and instrument_index == 1)
            context_mask = session >= 2
            panel_rows.append(
                {
                    "slot_time": timestamp,
                    "instrument_id": instrument_id,
                    "event_time": timestamp if feature_mask else None,
                    "feature_mask": feature_mask,
                    "context_mask": context_mask,
                    "presence_mask": context_mask,
                    "tradable_mask": context_mask and feature_mask,
                    **{
                        name: float(session + instrument_index + column_index / 10)
                        if feature_mask
                        else 0.0
                        for column_index, name in enumerate(TEMPORAL_COLUMNS)
                    },
                    "market_return_1": float(session) if context_mask else 0.0,
                    "volatility_20": 0.02 if context_mask else 0.0,
                }
            )
    panel_path = root / "temporal-panel.parquet"
    pq.write_table(pa.Table.from_pylist(panel_rows), panel_path)
    rows = []
    row_id = 0
    for session in (2, 3):
        timestamp = start + timedelta(days=session)
        for instrument_index, instrument_id in enumerate(("AAA.SSE", "BBB.SSE")):
            rows.append(
                {
                    "row_id": row_id,
                    "decision_time": timestamp,
                    "instrument_id": instrument_id,
                    "horizon_sessions": 1,
                    "cross_sectional_rank": float(instrument_index),
                    "training_eligible": True,
                }
            )
            row_id += 1
    rows_path = root / "rows.parquet"
    pq.write_table(pa.Table.from_pylist(rows), rows_path)
    body = {
        "schema_version": "astraquant.stage-b-v2-stockmixer-panel/v1",
        "source_raw_export_digest": "sha256:" + "1" * 64,
        "source_materialization_digest": "sha256:" + "2" * 64,
        "horizons": [1],
        "lookback": 2,
        "price_transform": "PREVIOUS_CLOSE_RELATIVE_V1",
        "volume_transform": "LOG1P_DIFFERENCE_V1",
        "context_visibility": "DECISION_TIME_ONLY",
        "temporal_columns": list(TEMPORAL_COLUMNS),
        "context_columns": ["market_return_1", "volatility_20"],
        "instrument_count": 2,
        "session_count": 4,
        "panel_row_count": 8,
        "row_count": 4,
        "temporal_panel_file": {
            "path": "temporal-panel.parquet",
            "digest": _file_digest(panel_path),
            "row_count": 8,
        },
        "rows_file": {"path": "rows.parquet", "digest": _file_digest(rows_path)},
    }
    manifest = {"content_digest": canonical_digest(body), **body}
    (root / "manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root / "manifest.json"


def test_loads_canonical_panel_and_builds_dynamic_session_batch(tmp_path: Path) -> None:
    panel = load_temporal_panel(_panel(tmp_path / "panel"))

    assert panel.instrument_ids == ("AAA.SSE", "BBB.SSE")
    assert panel.temporal_features.shape == (4, 2, 6)
    assert panel.context_features.shape == (4, 2, 2)
    batch = build_temporal_batch(panel, row_ids=(2, 3))
    assert batch.temporal_features.shape == (1, 2, 2, 6)
    assert batch.current_context.shape == (1, 2, 2)
    assert batch.row_ids.tolist() == [[2, 3]]
    assert batch.label_mask.tolist() == [[True, True]]
    assert batch.presence_mask.tolist() == [[True, True]]
    assert torch.isfinite(batch.temporal_features).all()


def test_rejects_tampered_panel_and_incomplete_session_selection(tmp_path: Path) -> None:
    manifest = _panel(tmp_path / "panel")
    with (manifest.parent / "temporal-panel.parquet").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="panel digest"):
        load_temporal_panel(manifest)

    valid = load_temporal_panel(_panel(tmp_path / "valid"))
    with pytest.raises(ValueError, match="complete decision-time cross-section"):
        build_temporal_batch(valid, row_ids=(2,))

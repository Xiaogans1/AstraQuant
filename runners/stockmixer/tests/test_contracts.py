from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from astraquant_stockmixer_runner.contracts import (
    STOCKMIXER_REQUEST_SCHEMA,
    STOCKMIXER_UPSTREAM_COMMIT,
    canonical_digest,
    load_request,
)

_DECISION = datetime(2026, 8, 7, 7, tzinfo=UTC)


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _rows() -> list[dict[str, object]]:
    values = []
    for sequence_index in range(2):
        slot_time = _DECISION - timedelta(days=1 - sequence_index)
        for instrument_id, present in (("AAA.SSE", True), ("BBB.SSE", False)):
            feature = present
            values.append(
                {
                    "slot_time": slot_time,
                    "instrument_id": instrument_id,
                    "event_time": slot_time if feature else None,
                    "feature_mask": feature,
                    "presence_mask": True,
                    "tradable_mask": present,
                    "label_mask": present,
                    "label": 0.01 if present else 0.0,
                    "open": 10.0 if feature else 0.0,
                    "high": 10.2 if feature else 0.0,
                    "low": 9.8 if feature else 0.0,
                    "close": 10.1 if feature else 0.0,
                    "volume": 100000.0 if feature else 0.0,
                }
            )
    return values


def _schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("slot_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=True),
            pa.field("feature_mask", pa.bool_(), nullable=False),
            pa.field("presence_mask", pa.bool_(), nullable=False),
            pa.field("tradable_mask", pa.bool_(), nullable=False),
            pa.field("label_mask", pa.bool_(), nullable=False),
            pa.field("label", pa.float64(), nullable=False),
            pa.field("open", pa.float64(), nullable=False),
            pa.field("high", pa.float64(), nullable=False),
            pa.field("low", pa.float64(), nullable=False),
            pa.field("close", pa.float64(), nullable=False),
            pa.field("volume", pa.float64(), nullable=False),
        ],
        metadata={b"schema_version": STOCKMIXER_REQUEST_SCHEMA.encode("ascii")},
    )


def _write_request(root: Path, *, rows: list[dict[str, object]] | None = None) -> Path:
    root.mkdir()
    panel = root / "panel.parquet"
    pq.write_table(pa.Table.from_pylist(rows or _rows(), schema=_schema()), panel)
    body = {
        "schema_version": STOCKMIXER_REQUEST_SCHEMA,
        "upstream_commit": STOCKMIXER_UPSTREAM_COMMIT,
        "provider_id": "eastmoney",
        "sources": [
            {
                "dataset_id": "dataset-aaa",
                "instrument_id": "AAA.SSE",
                "source_snapshot_id": f"sha256:{'a' * 64}",
            },
            {
                "dataset_id": "dataset-bbb",
                "instrument_id": "BBB.SSE",
                "source_snapshot_id": f"sha256:{'b' * 64}",
            },
        ],
        "universe": {
            "id": "two-stock",
            "snapshot_id": f"sha256:{'c' * 64}",
            "timeline_digest": f"sha256:{'d' * 64}",
        },
        "folds_digest": f"sha256:{'e' * 64}",
        "panel_file": {"path": "panel.parquet", "digest": _file_digest(panel)},
        "input_columns": ["open", "high", "low", "close", "volume"],
        "lookback": 2,
        "label_name": "future_return",
        "samples": [
            {
                "fold_id": "fold-01",
                "segment": "test",
                "sample_id": 0,
                "decision_time": _DECISION.isoformat(),
                "members": ["AAA.SSE", "BBB.SSE"],
                "window_times": [
                    (_DECISION - timedelta(days=1)).isoformat(),
                    _DECISION.isoformat(),
                ],
            }
        ],
    }
    request = {"content_digest": canonical_digest(body), **body}
    path = root / "request.json"
    path.write_text(json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def test_loads_sealed_request_and_typed_panel(tmp_path: Path) -> None:
    request = load_request(_write_request(tmp_path / "valid"))

    assert request.lookback == 2
    assert request.instrument_ids == ("AAA.SSE", "BBB.SSE")
    assert request.sample_count == 1
    assert request.table.num_rows == 4


def test_rejects_wrong_upstream_and_changed_panel(tmp_path: Path) -> None:
    path = _write_request(tmp_path / "wrong-upstream")
    value = json.loads(path.read_text())
    value["upstream_commit"] = "0" * 40
    body = {key: item for key, item in value.items() if key != "content_digest"}
    value["content_digest"] = canonical_digest(body)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="upstream commit"):
        load_request(path)

    changed = _write_request(tmp_path / "changed-panel")
    with (changed.parent / "panel.parquet").open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="panel digest"):
        load_request(changed)


def test_rejects_future_bar_and_unmasked_zero_placeholder(tmp_path: Path) -> None:
    future_rows = _rows()
    future_rows[0]["event_time"] = future_rows[0]["slot_time"] + timedelta(seconds=1)  # type: ignore[operator]
    with pytest.raises(ValueError, match="does not match slot_time"):
        load_request(_write_request(tmp_path / "future", rows=future_rows))

    invalid_missing = _rows()
    invalid_missing[-1]["close"] = 1.0
    with pytest.raises(ValueError, match="masked features must be zero"):
        load_request(_write_request(tmp_path / "invalid-missing", rows=invalid_missing))


def test_rejects_noncanonical_rows_and_inconsistent_sample_masks(tmp_path: Path) -> None:
    noncanonical = _rows()
    noncanonical[0], noncanonical[-1] = noncanonical[-1], noncanonical[0]
    with pytest.raises(ValueError, match="canonical order"):
        load_request(_write_request(tmp_path / "noncanonical", rows=noncanonical))

    inconsistent = _rows()
    inconsistent[3]["presence_mask"] = False
    with pytest.raises(ValueError, match="membership"):
        load_request(_write_request(tmp_path / "inconsistent", rows=inconsistent))


def test_rejects_tradable_sample_without_current_feature(tmp_path: Path) -> None:
    invalid = _rows()
    invalid[2]["feature_mask"] = False
    invalid[2]["event_time"] = None
    for name in ("open", "high", "low", "close", "volume"):
        invalid[2][name] = 0.0
    with pytest.raises(ValueError, match="tradable_mask requires a real feature"):
        load_request(_write_request(tmp_path / "missing-current", rows=invalid))

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from astraquant_kronos_runner.contracts import (
    KRONOS_MODEL_REVISION,
    KRONOS_REQUEST_SCHEMA,
    KRONOS_TOKENIZER_REVISION,
    KRONOS_UPSTREAM_COMMIT,
    canonical_digest,
)
from astraquant_kronos_runner.runner import run_request

from tests.fakes import NonFiniteBackend, RecordingBackend


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _prepare(root: Path) -> Path:
    for directory, content in (("model", b"model"), ("tokenizer", b"tokenizer")):
        path = root / "weights" / directory / "model.safetensors"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    start = datetime(2026, 8, 7, 6, 45, tzinfo=UTC)
    rows = []
    request_rows = []
    for row_id in (7, 8):
        decision = start + timedelta(minutes=row_id)
        request_rows.append(
            {
                "fold_id": "fold-01",
                "row_id": row_id,
                "instrument_id": "512800.SSE",
                "decision_time": decision.isoformat(),
                "forecast_times": [
                    (decision + timedelta(minutes=index)).isoformat() for index in (1, 2)
                ],
            }
        )
        for sequence in range(3):
            event_time = decision - timedelta(minutes=2 - sequence)
            rows.append(
                {
                    "fold_id": "fold-01",
                    "row_id": row_id,
                    "instrument_id": "512800.SSE",
                    "decision_time": decision,
                    "sequence_index": sequence,
                    "event_time": event_time,
                    "open": 10.0 + sequence / 10,
                    "high": 10.2 + sequence / 10,
                    "low": 9.8 + sequence / 10,
                    "close": 10.1 + sequence / 10,
                    "volume": 100000.0,
                    "amount": 1000000.0,
                }
            )
    schema = pa.schema(
        [
            pa.field("fold_id", pa.string(), nullable=False),
            pa.field("row_id", pa.int64(), nullable=False),
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("decision_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("sequence_index", pa.int16(), nullable=False),
            pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=False),
            *(
                pa.field(name, pa.float64(), nullable=False)
                for name in ("open", "high", "low", "close", "volume", "amount")
            ),
        ],
        metadata={b"schema_version": KRONOS_REQUEST_SCHEMA.encode("ascii")},
    )
    windows = root / "export" / "windows.parquet"
    windows.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema), windows, compression="zstd", version="2.6"
    )
    body = {
        "schema_version": KRONOS_REQUEST_SCHEMA,
        "upstream_commit": KRONOS_UPSTREAM_COMMIT,
        "provider_id": "eastmoney",
        "sources": [
            {
                "dataset_id": "dataset",
                "instrument_id": "512800.SSE",
                "source_snapshot_id": f"sha256:{'1' * 64}",
            }
        ],
        "windows_file": {"path": "windows.parquet", "digest": _digest(windows.read_bytes())},
        "folds_digest": f"sha256:{'2' * 64}",
        "calendar_snapshot_id": f"sha256:{'3' * 64}",
        "rows": request_rows,
        "input_columns": ["open", "high", "low", "close", "volume", "amount"],
        "model": {
            "id": "NeoQuasar/Kronos-base",
            "revision": KRONOS_MODEL_REVISION,
            "weights": {"path": "weights/model/model.safetensors", "digest": _digest(b"model")},
        },
        "tokenizer": {
            "id": "NeoQuasar/Kronos-Tokenizer-base",
            "revision": KRONOS_TOKENIZER_REVISION,
            "weights": {
                "path": "weights/tokenizer/model.safetensors",
                "digest": _digest(b"tokenizer"),
            },
        },
        "device_policy": {"preferred": "AUTO", "allow_cpu_fallback": True},
        "seed": 7,
        "context_length": 3,
        "prediction_length": 2,
        "sampling": {"temperature": 1.0, "top_k": 0, "top_p": 0.9, "sample_count": 5},
    }
    request = {"content_digest": canonical_digest(body), **body}
    path = root / "export" / "request.json"
    path.write_text(json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def test_runs_all_rows_repeatably_and_aggregates_paths(tmp_path: Path) -> None:
    request = _prepare(tmp_path)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_backend = RecordingBackend()
    second_backend = RecordingBackend()

    run_request(request, first, root=tmp_path, backend=first_backend)
    run_request(request, second, root=tmp_path, backend=second_backend)

    assert first.read_bytes() == second.read_bytes()
    response = json.loads(first.read_text())
    assert [item["row_id"] for item in response["forecasts"]] == [7, 8]
    assert first_backend.seeds == second_backend.seeds
    assert len(set(first_backend.seeds)) == 2
    forecast = response["forecasts"][0]
    assert forecast["expected_return"] == pytest.approx(0)
    assert forecast["terminal_return_p10"] == pytest.approx(-0.016)
    assert forecast["terminal_return_p90"] == pytest.approx(0.016)
    assert forecast["up_path_fraction"] == pytest.approx(0.4)
    assert forecast["uncertainty_width"] == pytest.approx(0.032)
    assert forecast["predicted_volatility"] > 0


def test_backend_or_windows_failure_does_not_publish_response(tmp_path: Path) -> None:
    request = _prepare(tmp_path)
    output = tmp_path / "response.json"
    with pytest.raises(ValueError, match="finite"):
        run_request(request, output, root=tmp_path, backend=NonFiniteBackend())
    assert not output.exists()

    windows = request.parent / "windows.parquet"
    windows.write_bytes(windows.read_bytes() + b"drift")
    with pytest.raises(ValueError, match="windows digest"):
        run_request(request, output, root=tmp_path, backend=RecordingBackend())
    assert not output.exists()

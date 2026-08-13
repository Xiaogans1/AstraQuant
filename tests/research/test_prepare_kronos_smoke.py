from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from tools.research.prepare_kronos_smoke import prepare_smoke_request


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path) -> Path:
    snapshot_id = "b" * 64
    snapshot = root / "dataset" / "snapshots" / snapshot_id
    data = snapshot / "trading_date=2026-08-07" / "part-0.parquet"
    data.parent.mkdir(parents=True)
    start = datetime(2026, 8, 7, 6, 50, tzinfo=UTC)
    rows = [
        {
            "instrument_id": "512800.SSE",
            "event_time": start + timedelta(minutes=index),
            "available_time": start + timedelta(minutes=index + 1),
            "open": Decimal("0.8000"),
            "high": Decimal("0.8020"),
            "low": Decimal("0.7990"),
            "close": Decimal("0.8010"),
            "volume": Decimal("100000"),
            "turnover": Decimal("80000"),
        }
        for index in range(5)
    ]
    pq.write_table(pa.Table.from_pylist(rows), data)
    manifest = {
        "schema_version": 1,
        "dataset_id": "cn-equity-512800-sse-1m-none",
        "snapshot_id": snapshot_id,
        "provider": {"id": "eastmoney", "interface": "bridge", "version": "1"},
        "adjustment": "none",
        "quality": {"publishable": True, "issues": []},
        "files": [
            {
                "path": data.relative_to(snapshot).as_posix(),
                "rows": len(rows),
                "sha256": _digest(data),
            }
        ],
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return snapshot


def _weights(root: Path, artifact: str, revision: str, content: bytes) -> None:
    directory = root / ".astraquant" / "models" / "kronos" / artifact / revision
    directory.mkdir(parents=True)
    (directory / "config.json").write_text("{}", encoding="utf-8")
    weights = directory / "model.safetensors"
    weights.write_bytes(content)
    manifest = {
        "schema_version": "astraquant.kronos-local-artifact/v1",
        "repo_id": "NeoQuasar/" + artifact,
        "revision": revision,
        "files": {
            "config.json": "sha256:" + _digest(directory / "config.json"),
            "model.safetensors": "sha256:" + _digest(weights),
        },
    }
    (directory / "artifact-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_builds_cuda_only_smoke_from_verified_eastmoney_bar_availability(
    tmp_path: Path,
) -> None:
    from tools.research.prepare_kronos_weights import (
        KRONOS_MODEL_REVISION,
        KRONOS_TOKENIZER_REVISION,
    )

    snapshot = _snapshot(tmp_path)
    _weights(tmp_path, "Kronos-base", KRONOS_MODEL_REVISION, b"model")
    _weights(
        tmp_path,
        "Kronos-Tokenizer-base",
        KRONOS_TOKENIZER_REVISION,
        b"tokenizer",
    )
    forecasts = [
        datetime(2026, 8, 10, 1, 31 + index, tzinfo=UTC) for index in range(2)
    ]

    result = prepare_smoke_request(
        root=tmp_path,
        snapshot_root=snapshot,
        output_root=tmp_path / "smoke",
        forecast_times=forecasts,
        context_length=4,
        sample_count=3,
    )

    request = json.loads(result.request_path.read_text())
    assert request["provider_id"] == "eastmoney"
    assert request["sources"] == [
        {
            "dataset_id": "cn-equity-512800-sse-1m-none",
            "instrument_id": "512800.SSE",
            "source_snapshot_id": "sha256:" + "b" * 64,
        }
    ]
    assert request["device_policy"] == {
        "preferred": "CUDA",
        "allow_cpu_fallback": False,
    }
    assert request["sampling"]["sample_count"] == 3
    assert request["rows"][0]["decision_time"] == "2026-08-07T06:55:00+00:00"
    window = pq.read_table(result.windows_path).to_pylist()
    assert window[-1]["event_time"] == datetime(2026, 8, 7, 6, 54, tzinfo=UTC)
    assert window[-1]["event_time"] < window[-1]["decision_time"]
    sidecar = json.loads((result.output_root / "smoke-manifest.json").read_text())
    assert sidecar["run_class"] == "SMOKE_ONLY"
    assert sidecar["performance_claim_allowed"] is False

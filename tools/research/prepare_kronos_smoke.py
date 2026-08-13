"""Build one CUDA-only, non-evaluative Kronos request from exact Eastmoney bars."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from tools.research.prepare_kronos_weights import (
    KRONOS_MODEL_ID,
    KRONOS_MODEL_REVISION,
    KRONOS_TOKENIZER_ID,
    KRONOS_TOKENIZER_REVISION,
    PreparedArtifact,
    prepare_artifact,
)

KRONOS_UPSTREAM_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
KRONOS_REQUEST_SCHEMA = "astraquant.kronos-request/v1"


@dataclass(frozen=True)
class SmokeRequest:
    output_root: Path
    request_path: Path
    windows_path: Path


def prepare_smoke_request(
    *,
    root: Path,
    snapshot_root: Path,
    output_root: Path,
    forecast_times: Sequence[datetime],
    context_length: int = 128,
    sample_count: int = 3,
) -> SmokeRequest:
    workspace = root.resolve()
    snapshot = snapshot_root.resolve()
    output = output_root.resolve()
    if output.exists():
        raise ValueError("Kronos smoke output_root must not already exist")
    if context_length < 2 or context_length > 512 or sample_count < 1:
        raise ValueError("Kronos smoke context or sample count is invalid")
    manifest_path = snapshot / "manifest.json"
    manifest = _object(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
    _validate_snapshot(manifest, snapshot)
    file_value = _select_file(manifest, context_length)
    parquet_path = snapshot / str(file_value["path"])
    if _digest(parquet_path, prefix=False) != file_value["sha256"]:
        raise ValueError("Eastmoney snapshot parquet digest mismatch")
    rows = pq.read_table(parquet_path).to_pylist()
    context = rows[-context_length:]
    if len(context) != context_length:
        raise ValueError("Eastmoney snapshot has insufficient smoke context")
    context.sort(key=lambda row: row["event_time"])
    instruments = {str(row["instrument_id"]) for row in context}
    if len(instruments) != 1:
        raise ValueError("Kronos smoke file must contain exactly one instrument")
    instrument_id = instruments.pop()
    decision_time = _aware(context[-1]["available_time"], "last available_time")
    if any(
        _aware(row["event_time"], "event_time") > decision_time
        or _aware(row["available_time"], "available_time") > decision_time
        for row in context
    ):
        raise ValueError("Kronos smoke context is not available at decision time")
    forecasts = tuple(_aware(value, "forecast_time") for value in forecast_times)
    if (
        not forecasts
        or any(value <= decision_time for value in forecasts)
        or list(forecasts) != sorted(set(forecasts))
    ):
        raise ValueError("Kronos smoke forecast times must be unique, ordered and future")

    model = _existing_artifact(
        root=workspace, repo_id=KRONOS_MODEL_ID, revision=KRONOS_MODEL_REVISION
    )
    tokenizer = _existing_artifact(
        root=workspace,
        repo_id=KRONOS_TOKENIZER_ID,
        revision=KRONOS_TOKENIZER_REVISION,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=output.parent, prefix=f".{output.name}-staging-", ignore_cleanup_errors=True
    ) as staging_name:
        staging = Path(staging_name)
        windows_path = staging / "windows.parquet"
        window_rows = [
            {
                "fold_id": "smoke-fold",
                "row_id": 0,
                "instrument_id": instrument_id,
                "decision_time": decision_time,
                "sequence_index": index,
                "event_time": _aware(row["event_time"], "event_time"),
                "open": _finite(row["open"], "open"),
                "high": _finite(row["high"], "high"),
                "low": _finite(row["low"], "low"),
                "close": _finite(row["close"], "close"),
                "volume": _finite(row["volume"], "volume"),
                "amount": _finite(row["turnover"], "turnover"),
            }
            for index, row in enumerate(context)
        ]
        pq.write_table(
            pa.Table.from_pylist(window_rows, schema=_window_schema()),
            windows_path,
            compression="zstd",
            version="2.6",
        )
        row_identity = {
            "fold_id": "smoke-fold",
            "row_id": 0,
            "instrument_id": instrument_id,
            "decision_time": decision_time.isoformat(),
            "forecast_times": [value.isoformat() for value in forecasts],
        }
        body: dict[str, object] = {
            "schema_version": KRONOS_REQUEST_SCHEMA,
            "upstream_commit": KRONOS_UPSTREAM_COMMIT,
            "provider_id": "eastmoney",
            "sources": [
                {
                    "dataset_id": manifest["dataset_id"],
                    "instrument_id": instrument_id,
                    "source_snapshot_id": "sha256:" + str(manifest["snapshot_id"]),
                }
            ],
            "windows_file": {
                "path": "windows.parquet",
                "digest": _digest(windows_path),
            },
            "folds_digest": _canonical_digest(
                {"run_class": "SMOKE_ONLY", "row": row_identity}
            ),
            "calendar_snapshot_id": _canonical_digest(
                {
                    "basis": "SMOKE_ONLY_EXPLICIT_TIMES",
                    "forecast_times": row_identity["forecast_times"],
                }
            ),
            "rows": [row_identity],
            "input_columns": ["open", "high", "low", "close", "volume", "amount"],
            "model": _artifact_value(model, KRONOS_MODEL_ID, KRONOS_MODEL_REVISION, workspace),
            "tokenizer": _artifact_value(
                tokenizer, KRONOS_TOKENIZER_ID, KRONOS_TOKENIZER_REVISION, workspace
            ),
            "device_policy": {"preferred": "CUDA", "allow_cpu_fallback": False},
            "seed": 20260813,
            "context_length": context_length,
            "prediction_length": len(forecasts),
            "sampling": {
                "temperature": 1.0,
                "top_k": 0,
                "top_p": 0.9,
                "sample_count": sample_count,
            },
        }
        request = {"content_digest": _canonical_digest(body), **body}
        (staging / "request.json").write_text(
            json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        sidecar = {
            "schema_version": "astraquant.kronos-smoke/v1",
            "run_class": "SMOKE_ONLY",
            "performance_claim_allowed": False,
            "source_manifest_digest": _digest(manifest_path),
            "request_content_digest": request["content_digest"],
        }
        (staging / "smoke-manifest.json").write_text(
            json.dumps(sidecar, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        staging.replace(output)
    return SmokeRequest(
        output_root=output,
        request_path=output / "request.json",
        windows_path=output / "windows.parquet",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a real-data Kronos CUDA smoke")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--forecast-time", action="append", required=True)
    parser.add_argument("--context-length", type=int, default=128)
    parser.add_argument("--sample-count", type=int, default=3)
    arguments = parser.parse_args(argv)
    result = prepare_smoke_request(
        root=arguments.root,
        snapshot_root=arguments.snapshot_root,
        output_root=arguments.output_root,
        forecast_times=[datetime.fromisoformat(value) for value in arguments.forecast_time],
        context_length=arguments.context_length,
        sample_count=arguments.sample_count,
    )
    print(result.request_path)
    return 0


def _existing_artifact(
    *, root: Path, repo_id: str, revision: str
) -> PreparedArtifact:
    def no_download(**kwargs: object) -> Path:
        raise ValueError("Kronos smoke never downloads weights")

    return prepare_artifact(
        repo_id=repo_id, revision=revision, root=root, downloader=no_download
    )


def _artifact_value(artifact: Any, repo_id: str, revision: str, root: Path) -> dict[str, object]:
    weights = artifact.directory / "model.safetensors"
    return {
        "id": repo_id,
        "revision": revision,
        "weights": {
            "path": weights.relative_to(root).as_posix(),
            "digest": artifact.weights_digest,
        },
    }


def _validate_snapshot(manifest: dict[str, Any], snapshot: Path) -> None:
    provider = _object(manifest.get("provider"), "provider")
    quality = _object(manifest.get("quality"), "quality")
    snapshot_id = str(manifest.get("snapshot_id", ""))
    if (
        manifest.get("schema_version") != 1
        or provider.get("id") != "eastmoney"
        or manifest.get("adjustment") != "none"
        or quality.get("publishable") is not True
        or len(snapshot_id) != 64
        or any(character not in "0123456789abcdef" for character in snapshot_id)
        or snapshot.name != snapshot_id
    ):
        raise ValueError("snapshot is not an exact publishable Eastmoney artifact")


def _select_file(manifest: dict[str, Any], context_length: int) -> dict[str, Any]:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("Eastmoney snapshot files are invalid")
    for value in reversed(files):
        item = _object(value, "snapshot file")
        if isinstance(item.get("rows"), int) and item["rows"] >= context_length:
            return item
    raise ValueError("no exact Eastmoney file contains the required context")


def _window_schema() -> pa.Schema:
    return pa.schema(
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


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _digest(path: Path, *, prefix: bool = True) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    return "sha256:" + value if prefix else value


def _aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _finite(value: object, name: str) -> float:
    number = float(value)  # type: ignore[arg-type]
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return number


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

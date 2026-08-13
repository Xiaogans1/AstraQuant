"""Fail-closed orchestration for an injected Kronos prediction backend."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .contracts import (
    KRONOS_RESPONSE_SCHEMA,
    canonical_digest,
    validate_request,
    validate_response,
)
from .forecast import summarize_paths


class KronosBackend(Protocol):
    def environment_identity(self) -> dict[str, str]: ...

    def predict_paths(
        self,
        *,
        window: Sequence[dict[str, object]],
        forecast_times: Sequence[datetime],
        seed: int,
        temperature: float,
        top_k: int,
        top_p: float,
        sample_count: int,
    ) -> Sequence[Sequence[float]]: ...


def run_request(
    request_path: Path,
    output_path: Path,
    *,
    root: Path,
    backend: KronosBackend,
) -> dict[str, object]:
    if output_path.exists():
        raise ValueError("Kronos response output must not already exist")
    request = validate_request(_read_json(request_path), root=root)
    windows = _load_windows(request_path.parent, request)
    grouped = _group_windows(windows, request)
    sampling = _object(request["sampling"], "sampling")
    global_seed = _integer(request["seed"], "seed")
    temperature = _number(sampling["temperature"], "temperature")
    top_k = _integer(sampling["top_k"], "top_k")
    top_p = _number(sampling["top_p"], "top_p")
    sample_count = _integer(sampling["sample_count"], "sample_count")
    prediction_length = _integer(request["prediction_length"], "prediction_length")
    forecasts = []
    for value in _array(request["rows"], "rows"):
        row = _object(value, "row")
        key = _row_key(row)
        window = grouped[key]
        forecast_times = tuple(
            datetime.fromisoformat(str(item).replace("Z", "+00:00"))
            for item in _array(row["forecast_times"], "forecast_times")
        )
        paths = backend.predict_paths(
            window=window,
            forecast_times=forecast_times,
            seed=_row_seed(global_seed, key),
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            sample_count=sample_count,
        )
        summary = summarize_paths(
            last_close=_number(window[-1]["close"], "last close"),
            paths=paths,
            sample_count=sample_count,
            prediction_length=prediction_length,
        )
        forecasts.append(
            {
                "fold_id": key[0],
                "row_id": key[1],
                "instrument_id": key[2],
                "decision_time": key[3],
                **summary,
            }
        )
    model = _object(request["model"], "model")
    tokenizer = _object(request["tokenizer"], "tokenizer")
    body: dict[str, object] = {
        "schema_version": KRONOS_RESPONSE_SCHEMA,
        "request_content_digest": request["content_digest"],
        "upstream_commit": request["upstream_commit"],
        "model": _response_artifact(model),
        "tokenizer": _response_artifact(tokenizer),
        "environment": backend.environment_identity(),
        "forecasts": forecasts,
    }
    response = {"content_digest": canonical_digest(body), **body}
    validate_response(response, request=request)
    encoded = (
        json.dumps(
            response,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    if temporary.exists():
        raise ValueError("Kronos response temporary output already exists")
    try:
        temporary.write_bytes(encoded)
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return response


def _load_windows(request_root: Path, request: dict[str, object]) -> list[dict[str, object]]:
    file_identity = _object(request["windows_file"], "windows_file")
    path = request_root / str(file_identity["path"])
    if not path.is_file() or _file_digest(path) != file_identity["digest"]:
        raise ValueError("Kronos windows digest mismatch")
    table = pq.read_table(path)
    if table.schema != _window_schema():
        raise ValueError("Kronos windows schema mismatch")
    return cast(list[dict[str, object]], table.to_pylist())


def _group_windows(
    windows: list[dict[str, object]], request: dict[str, object]
) -> dict[tuple[str, int, str, str], list[dict[str, object]]]:
    grouped: dict[tuple[str, int, str, str], list[dict[str, object]]] = {}
    for row in windows:
        decision = _aware(row["decision_time"], "decision_time")
        key = (
            str(row["fold_id"]),
            _integer(row["row_id"], "row_id"),
            str(row["instrument_id"]),
            decision.isoformat(),
        )
        grouped.setdefault(key, []).append(row)
    expected = [_row_key(_object(value, "row")) for value in _array(request["rows"], "rows")]
    if list(grouped) != expected:
        raise ValueError("Kronos windows row coverage or order mismatch")
    context_length = _integer(request["context_length"], "context_length")
    for key, rows in grouped.items():
        decision = datetime.fromisoformat(key[3].replace("Z", "+00:00"))
        if (
            len(rows) != context_length
            or [_integer(row["sequence_index"], "sequence_index") for row in rows]
            != list(range(context_length))
            or any(_aware(row["event_time"], "event_time") > decision for row in rows)
            or _aware(rows[-1]["event_time"], "event_time") != decision
        ):
            raise ValueError("Kronos windows context or time boundary mismatch")
    return grouped


def _row_key(row: dict[str, object]) -> tuple[str, int, str, str]:
    return (
        str(row["fold_id"]),
        _integer(row["row_id"], "row_id"),
        str(row["instrument_id"]),
        str(row["decision_time"]),
    )


def _row_seed(global_seed: int, key: tuple[str, int, str, str]) -> int:
    encoded = json.dumps([global_seed, *key], separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")


def _response_artifact(value: dict[str, object]) -> dict[str, object]:
    weights = _object(value["weights"], "weights")
    return {
        "id": value["id"],
        "revision": value["revision"],
        "weights_digest": weights["digest"],
    }


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
        metadata={b"schema_version": b"astraquant.kronos-request/v1"},
    )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def _aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value

"""Fail-closed request and panel contracts for the StockMixer runner."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

STOCKMIXER_REQUEST_SCHEMA = "astraquant.stockmixer-request/v1"
STOCKMIXER_UPSTREAM_COMMIT = "cce13598afd3ff33ae317700a85ae08db0554652"
STOCKMIXER_INPUT_COLUMNS = ("open", "high", "low", "close", "volume")

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUEST_KEYS = {
    "content_digest",
    "schema_version",
    "upstream_commit",
    "provider_id",
    "sources",
    "universe",
    "folds_digest",
    "panel_file",
    "samples_file",
    "sample_count",
    "input_columns",
    "lookback",
    "label_name",
}
_FEATURES = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class StockMixerRequest:
    content_digest: str
    lookback: int
    label_name: str
    instrument_ids: tuple[str, ...]
    sample_count: int
    table: pa.Table
    samples: pa.Table


def canonical_digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("canonical JSON must contain finite JSON values") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def load_request(request_path: Path) -> StockMixerRequest:
    request = _object(json.loads(request_path.read_text(encoding="utf-8")), "request")
    if set(request) != _REQUEST_KEYS:
        raise ValueError("request fields mismatch")
    if request["schema_version"] != STOCKMIXER_REQUEST_SCHEMA:
        raise ValueError("request schema_version mismatch")
    if request["upstream_commit"] != STOCKMIXER_UPSTREAM_COMMIT:
        raise ValueError("request upstream commit mismatch")
    if request["provider_id"] != "eastmoney":
        raise ValueError("request provider_id must be eastmoney")
    supplied = _digest(request["content_digest"], "content_digest")
    body = {key: value for key, value in request.items() if key != "content_digest"}
    if canonical_digest(body) != supplied:
        raise ValueError("request content_digest mismatch")
    _digest(request["folds_digest"], "folds_digest")
    lookback = _integer(request["lookback"], "lookback", minimum=1)
    label_name = _text(request["label_name"], "label_name")
    if request["input_columns"] != list(STOCKMIXER_INPUT_COLUMNS):
        raise ValueError("request input_columns mismatch")

    sources = _array(request["sources"], "sources")
    instrument_ids = []
    for index, value in enumerate(sources):
        source = _object(value, f"source {index}")
        if set(source) != {"dataset_id", "instrument_id", "source_snapshot_id"}:
            raise ValueError("source fields mismatch")
        _text(source["dataset_id"], "source dataset_id")
        instrument_ids.append(_text(source["instrument_id"], "source instrument_id"))
        _digest(source["source_snapshot_id"], "source snapshot")
    if not instrument_ids or instrument_ids != sorted(set(instrument_ids)):
        raise ValueError("source instruments must be non-empty, unique and canonical")

    universe = _object(request["universe"], "universe")
    if set(universe) != {"id", "snapshot_id", "timeline_digest"}:
        raise ValueError("universe fields mismatch")
    _text(universe["id"], "universe id")
    _digest(universe["snapshot_id"], "universe snapshot")
    _digest(universe["timeline_digest"], "universe timeline")

    panel_file = _object(request["panel_file"], "panel_file")
    if set(panel_file) != {"path", "digest"} or panel_file["path"] != "panel.parquet":
        raise ValueError("panel_file fields or path mismatch")
    expected_panel_digest = _digest(panel_file["digest"], "panel digest")
    panel_path = request_path.parent / "panel.parquet"
    if not panel_path.is_file() or _file_digest(panel_path) != expected_panel_digest:
        raise ValueError("StockMixer panel digest mismatch")
    table = pq.read_table(panel_path)
    if table.schema != _panel_schema():
        raise ValueError("StockMixer panel schema mismatch")
    slot_times = _validate_rows(
        cast(list[dict[str, object]], table.to_pylist()),
        instruments=tuple(instrument_ids),
    )

    sample_count = _integer(request["sample_count"], "sample_count", minimum=1)
    samples_file = _object(request["samples_file"], "samples_file")
    if set(samples_file) != {"path", "digest"} or samples_file["path"] != "samples.parquet":
        raise ValueError("samples_file fields or path mismatch")
    expected_samples_digest = _digest(samples_file["digest"], "samples digest")
    samples_path = request_path.parent / "samples.parquet"
    if not samples_path.is_file() or _file_digest(samples_path) != expected_samples_digest:
        raise ValueError("StockMixer samples digest mismatch")
    samples_table = pq.read_table(samples_path)
    if samples_table.schema != _samples_schema():
        raise ValueError("StockMixer samples schema mismatch")
    _validate_samples(
        cast(list[dict[str, object]], samples_table.to_pylist()),
        sample_count=sample_count,
        slot_times=slot_times,
        lookback=lookback,
    )
    return StockMixerRequest(
        content_digest=supplied,
        lookback=lookback,
        label_name=label_name,
        instrument_ids=tuple(instrument_ids),
        sample_count=sample_count,
        table=table,
        samples=samples_table,
    )


def _validate_rows(
    rows: list[dict[str, object]],
    *,
    instruments: tuple[str, ...],
) -> tuple[datetime, ...]:
    if not rows or len(rows) % len(instruments):
        raise ValueError("StockMixer panel row coverage mismatch")
    actual_keys: list[tuple[datetime, str]] = []
    identities: set[tuple[datetime, str]] = set()
    for row in rows:
        slot_time = _aware(row["slot_time"], "row slot_time")
        instrument = _text(row["instrument_id"], "row instrument_id")
        identity = (slot_time, instrument)
        if identity in identities:
            raise ValueError("StockMixer panel contains duplicate row identities")
        identities.add(identity)
        if instrument not in instruments:
            raise ValueError("StockMixer panel row is outside request coverage")
        actual_keys.append(identity)

        event_time = row["event_time"]
        feature_mask = _boolean(row["feature_mask"], "feature_mask")
        presence_mask = _boolean(row["presence_mask"], "presence_mask")
        tradable_mask = _boolean(row["tradable_mask"], "tradable_mask")
        label_mask = _boolean(row["label_mask"], "label_mask")
        features = [_number(row[name], name) for name in _FEATURES]
        label = _number(row["label"], "label")
        if feature_mask:
            if not isinstance(event_time, datetime):
                raise ValueError("unmasked features require event_time")
            if _aware(event_time, "event_time") != slot_time:
                raise ValueError("panel event_time does not match slot_time")
        elif event_time is not None or any(value != 0.0 for value in features):
            raise ValueError("masked features must be zero with null event_time")
        if tradable_mask and not (presence_mask and feature_mask):
            raise ValueError("tradable_mask requires a real feature and universe presence")
        if label_mask and not tradable_mask:
            raise ValueError("label_mask requires a tradable sample")
        if not label_mask and label != 0.0:
            raise ValueError("masked label must be zero")
    if actual_keys != sorted(actual_keys):
        raise ValueError("StockMixer panel rows must use canonical order")
    slot_times = tuple(sorted({key[0] for key in identities}))
    expected_keys = {(slot, instrument) for slot in slot_times for instrument in instruments}
    if identities != expected_keys:
        raise ValueError("StockMixer panel time and instrument coverage mismatch")
    return slot_times


def _validate_samples(
    rows: list[dict[str, object]],
    *,
    sample_count: int,
    slot_times: tuple[datetime, ...],
    lookback: int,
) -> None:
    if len(rows) != sample_count:
        raise ValueError("StockMixer samples row coverage mismatch")
    keys: list[tuple[str, datetime, str]] = []
    for expected_id, row in enumerate(rows):
        fold_id = _text(row["fold_id"], "sample fold_id")
        segment = _text(row["segment"], "sample segment")
        if segment not in {"train", "test"}:
            raise ValueError("sample segment mismatch")
        sample_id = _integer(row["sample_id"], "sample_id", minimum=0)
        if sample_id != expected_id:
            raise ValueError("sample_id must be contiguous and canonical")
        decision_time = _aware(row["decision_time"], "sample decision_time")
        start = _integer(row["window_start_index"], "window_start_index", minimum=0)
        end = _integer(row["window_end_index"], "window_end_index", minimum=1)
        if end - start != lookback or end > len(slot_times):
            raise ValueError("sample window indices do not match lookback")
        if slot_times[end - 1] != decision_time:
            raise ValueError("sample window does not end at decision_time")
        keys.append((fold_id, decision_time, segment))
    if keys != sorted(keys):
        raise ValueError("samples must use canonical order")


def _panel_schema() -> pa.Schema:
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
            *(pa.field(name, pa.float64(), nullable=False) for name in _FEATURES),
        ],
        metadata={b"schema_version": STOCKMIXER_REQUEST_SCHEMA.encode("ascii")},
    )


def _samples_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("fold_id", pa.string(), nullable=False),
            pa.field("segment", pa.string(), nullable=False),
            pa.field("sample_id", pa.int64(), nullable=False),
            pa.field("decision_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("window_start_index", pa.int32(), nullable=False),
            pa.field("window_end_index", pa.int32(), nullable=False),
        ],
        metadata={b"schema_version": STOCKMIXER_REQUEST_SCHEMA.encode("ascii")},
    )


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty text")
    return value


def _digest(value: object, name: str) -> str:
    text = _text(value, name)
    if not _DIGEST.fullmatch(text) or text == f"sha256:{'0' * 64}":
        raise ValueError(f"{name} must be an exact SHA-256 digest")
    return text


def _integer(
    value: object,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} is below its minimum")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} is above its maximum")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _timestamp(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    return _aware(parsed, name)


def _aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value

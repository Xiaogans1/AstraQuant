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
    "input_columns",
    "lookback",
    "label_name",
    "samples",
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

    sample_values = _array(request["samples"], "samples")
    if not sample_values:
        raise ValueError("samples must not be empty")
    samples: list[tuple[str, str, int, datetime, tuple[str, ...]]] = []
    for index, value in enumerate(sample_values):
        sample = _object(value, f"sample {index}")
        if set(sample) != {"fold_id", "segment", "sample_id", "decision_time", "members"}:
            raise ValueError("sample fields mismatch")
        segment = _text(sample["segment"], "sample segment")
        if segment not in {"train", "test"}:
            raise ValueError("sample segment mismatch")
        members = tuple(
            _text(item, "sample member")
            for item in _array(sample["members"], "members")
        )
        if members != tuple(sorted(set(members))) or not set(members).issubset(instrument_ids):
            raise ValueError("sample members must be canonical source instruments")
        samples.append(
            (
                _text(sample["fold_id"], "sample fold_id"),
                segment,
                _integer(sample["sample_id"], "sample_id", minimum=0),
                _timestamp(sample["decision_time"], "sample decision_time"),
                members,
            )
        )
    if samples != sorted(samples, key=lambda item: (item[0], item[3], item[1])):
        raise ValueError("samples must use canonical order")
    if [item[2] for item in samples] != list(range(len(samples))):
        raise ValueError("sample_id must be contiguous and canonical")

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
    _validate_rows(
        cast(list[dict[str, object]], table.to_pylist()),
        samples=samples,
        instruments=tuple(instrument_ids),
        lookback=lookback,
    )
    return StockMixerRequest(
        content_digest=supplied,
        lookback=lookback,
        label_name=label_name,
        instrument_ids=tuple(instrument_ids),
        sample_count=len(samples),
        table=table,
    )


def _validate_rows(
    rows: list[dict[str, object]],
    *,
    samples: list[tuple[str, str, int, datetime, tuple[str, ...]]],
    instruments: tuple[str, ...],
    lookback: int,
) -> None:
    expected_count = len(samples) * len(instruments) * lookback
    if len(rows) != expected_count:
        raise ValueError("StockMixer panel row coverage mismatch")
    sample_by_id = {item[2]: item for item in samples}
    actual_keys: list[tuple[str, datetime, str, int]] = []
    identities: set[tuple[str, int, str, int]] = set()
    groups: dict[tuple[str, int, str], list[dict[str, object]]] = {}
    for row in rows:
        fold_id = _text(row["fold_id"], "row fold_id")
        segment = _text(row["segment"], "row segment")
        sample_id = _integer(row["sample_id"], "row sample_id", minimum=0)
        decision_time = _aware(row["decision_time"], "row decision_time")
        instrument = _text(row["instrument_id"], "row instrument_id")
        sequence_index = _integer(
            row["sequence_index"], "row sequence_index", minimum=0, maximum=lookback - 1
        )
        identity = (fold_id, sample_id, instrument, sequence_index)
        if identity in identities:
            raise ValueError("StockMixer panel contains duplicate row identities")
        identities.add(identity)
        groups.setdefault((fold_id, sample_id, instrument), []).append(row)
        sample = sample_by_id.get(sample_id)
        if (
            sample is None
            or fold_id != sample[0]
            or segment != sample[1]
            or decision_time != sample[3]
            or instrument not in instruments
        ):
            raise ValueError("StockMixer panel row does not match request samples")
        actual_keys.append((fold_id, decision_time, instrument, sequence_index))

        event_time = row["event_time"]
        feature_mask = _boolean(row["feature_mask"], "feature_mask")
        presence_mask = _boolean(row["presence_mask"], "presence_mask")
        tradable_mask = _boolean(row["tradable_mask"], "tradable_mask")
        label_mask = _boolean(row["label_mask"], "label_mask")
        members = sample[4]
        if presence_mask != (instrument in members):
            raise ValueError("presence_mask does not match sealed universe membership")
        features = [_number(row[name], name) for name in _FEATURES]
        label = _number(row["label"], "label")
        if feature_mask:
            if not isinstance(event_time, datetime):
                raise ValueError("unmasked features require event_time")
            if _aware(event_time, "event_time") > decision_time:
                raise ValueError("panel event_time is after decision_time")
        elif event_time is not None or any(value != 0.0 for value in features):
            raise ValueError("masked features must be zero with null event_time")
        if tradable_mask and not presence_mask:
            raise ValueError("tradable_mask requires universe presence")
        if label_mask and not tradable_mask:
            raise ValueError("label_mask requires a tradable sample")
        if not label_mask and label != 0.0:
            raise ValueError("masked label must be zero")
    if actual_keys != sorted(actual_keys):
        raise ValueError("StockMixer panel rows must use canonical order")
    for values in groups.values():
        if len(values) != lookback:
            raise ValueError("StockMixer panel lookback coverage mismatch")
        sample_values = {
            (
                row["presence_mask"],
                row["tradable_mask"],
                row["label_mask"],
                row["label"],
            )
            for row in values
        }
        if len(sample_values) != 1:
            raise ValueError("sample masks and label must be constant across lookback")
        current = values[-1]
        if current["tradable_mask"] is True and current["feature_mask"] is not True:
            raise ValueError("tradable sample requires current feature")


def _panel_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("fold_id", pa.string(), nullable=False),
            pa.field("segment", pa.string(), nullable=False),
            pa.field("sample_id", pa.int64(), nullable=False),
            pa.field("decision_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("sequence_index", pa.int16(), nullable=False),
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

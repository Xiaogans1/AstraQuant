"""Strict loading and lazy window batches for the Stage B v2 temporal panel."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import torch
from torch import Tensor

from .contracts import canonical_digest

PANEL_SCHEMA = "astraquant.stage-b-v2-stockmixer-panel/v1"
TEMPORAL_COLUMNS = (
    "open_relative",
    "high_relative",
    "low_relative",
    "close_relative",
    "log_volume_change",
    "log_turnover_change",
)


@dataclass(frozen=True, slots=True)
class TemporalPanel:
    manifest_path: Path
    content_digest: str
    source_raw_export_digest: str
    source_materialization_digest: str
    horizons: tuple[int, ...]
    lookback: int
    instrument_ids: tuple[str, ...]
    sessions: tuple[datetime, ...]
    context_columns: tuple[str, ...]
    temporal_features: np.ndarray
    context_features: np.ndarray
    feature_mask: np.ndarray
    context_mask: np.ndarray
    presence_mask: np.ndarray
    tradable_mask: np.ndarray
    row_ids: np.ndarray
    row_decision_time_us: np.ndarray
    row_instrument_ids: pa.ChunkedArray
    row_horizons: np.ndarray
    labels: np.ndarray
    training_eligible: np.ndarray
    session_index_us: dict[int, int]
    instrument_index: dict[str, int]
    row_count_by_decision_horizon: dict[tuple[int, int], int]


@dataclass(frozen=True, slots=True)
class TemporalBatch:
    temporal_features: Tensor
    current_context: Tensor
    feature_mask: Tensor
    context_mask: Tensor
    presence_mask: Tensor
    tradable_mask: Tensor
    labels: Tensor
    label_mask: Tensor
    training_eligible: Tensor
    row_ids: Tensor
    decision_time_us: Tensor


def load_temporal_panel(manifest_path: Path) -> TemporalPanel:
    """Load a sealed panel and validate identities before tensor allocation."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != PANEL_SCHEMA:
        raise ValueError("StockMixer v2 panel manifest schema mismatch")
    body = {key: item for key, item in manifest.items() if key != "content_digest"}
    if manifest.get("content_digest") != canonical_digest(body):
        raise ValueError("StockMixer v2 panel manifest digest mismatch")
    instrument_count = _positive_integer(manifest, "instrument_count")
    session_count = _positive_integer(manifest, "session_count")
    panel_row_count = _positive_integer(manifest, "panel_row_count")
    row_count = _positive_integer(manifest, "row_count")
    if panel_row_count != instrument_count * session_count:
        raise ValueError("StockMixer v2 panel row coverage mismatch")
    lookback = _positive_integer(manifest, "lookback")
    horizons = _horizons(manifest)
    context_columns = _columns(manifest, "context_columns")
    if _columns(manifest, "temporal_columns") != TEMPORAL_COLUMNS:
        raise ValueError("StockMixer v2 temporal columns mismatch")
    if (
        manifest.get("price_transform") != "PREVIOUS_CLOSE_RELATIVE_V1"
        or manifest.get("volume_transform") != "LOG1P_DIFFERENCE_V1"
        or manifest.get("context_visibility") != "DECISION_TIME_ONLY"
    ):
        raise ValueError("StockMixer v2 transform policy mismatch")

    panel_path = _sealed_file(
        manifest_path.parent,
        manifest.get("temporal_panel_file"),
        "temporal-panel.parquet",
        "panel",
        expected_rows=panel_row_count,
    )
    rows_path = _sealed_file(
        manifest_path.parent,
        manifest.get("rows_file"),
        "rows.parquet",
        "rows",
    )
    table = pq.read_table(panel_path)
    expected_columns = [
        "slot_time",
        "instrument_id",
        "event_time",
        "feature_mask",
        "context_mask",
        "presence_mask",
        "tradable_mask",
        *TEMPORAL_COLUMNS,
        *context_columns,
    ]
    if table.column_names != expected_columns or table.num_rows != panel_row_count:
        raise ValueError("StockMixer v2 panel table schema mismatch")
    instrument_ids, sessions = _canonical_panel_axis(
        table,
        instrument_count=instrument_count,
        session_count=session_count,
    )
    feature_mask = _bool_matrix(table, "feature_mask", session_count, instrument_count)
    context_mask = _bool_matrix(table, "context_mask", session_count, instrument_count)
    presence_mask = _bool_matrix(table, "presence_mask", session_count, instrument_count)
    tradable_mask = _bool_matrix(table, "tradable_mask", session_count, instrument_count)
    if not np.array_equal(context_mask, presence_mask):
        raise ValueError("StockMixer v2 presence and context masks mismatch")
    if np.any(tradable_mask & ~(presence_mask & feature_mask)):
        raise ValueError("StockMixer v2 tradable mask exceeds visible features")
    temporal = _float_cube(
        table,
        TEMPORAL_COLUMNS,
        session_count,
        instrument_count,
    )
    context = _float_cube(table, context_columns, session_count, instrument_count)
    if np.any(temporal[~feature_mask] != 0) or np.any(context[~context_mask] != 0):
        raise ValueError("StockMixer v2 masked values must be zero")
    event_null = np.asarray(table["event_time"].is_null().to_numpy(), dtype=np.bool_).reshape(
        session_count, instrument_count
    )
    if not np.array_equal(~event_null, feature_mask):
        raise ValueError("StockMixer v2 event_time mask mismatch")
    comparable = pc.fill_null(pc.equal(table["event_time"], table["slot_time"]), False)
    comparable_values = np.asarray(comparable.to_numpy(), dtype=np.bool_).reshape(
        session_count, instrument_count
    )
    if np.any(feature_mask & ~comparable_values):
        raise ValueError("StockMixer v2 event_time is after or different from slot_time")

    rows = pq.read_table(rows_path)
    expected_row_columns = [
        "row_id",
        "decision_time",
        "instrument_id",
        "horizon_sessions",
        "cross_sectional_rank",
        "training_eligible",
    ]
    if rows.column_names != expected_row_columns or rows.num_rows != row_count:
        raise ValueError("StockMixer v2 label rows schema mismatch")
    row_ids = np.asarray(rows["row_id"].to_numpy(), dtype=np.int64)
    if not np.array_equal(row_ids, np.arange(len(row_ids), dtype=np.int64)):
        raise ValueError("StockMixer v2 row identifiers must be contiguous and canonical")
    decision_time_us = np.asarray(rows["decision_time"].to_numpy(), dtype="datetime64[us]").astype(
        np.int64
    )
    row_instrument_ids = rows["instrument_id"]
    panel_instrument_index = {value: index for index, value in enumerate(instrument_ids)}
    observed_instruments = set(cast(list[str], pc.unique(row_instrument_ids).to_pylist()))
    if not observed_instruments or not observed_instruments.issubset(panel_instrument_index):
        raise ValueError("StockMixer v2 label instrument is outside panel coverage")
    row_horizons = np.asarray(rows["horizon_sessions"].to_numpy(), dtype=np.int16)
    labels = np.asarray(rows["cross_sectional_rank"].to_numpy(), dtype=np.float32)
    eligible = np.asarray(rows["training_eligible"].to_numpy(), dtype=np.bool_)
    if not np.isfinite(labels).all() or set(int(value) for value in row_horizons) != set(horizons):
        raise ValueError("StockMixer v2 label values or horizons mismatch")
    session_time_us = np.asarray(
        [round(timestamp.timestamp() * 1_000_000) for timestamp in sessions],
        dtype=np.int64,
    )
    if not np.isin(np.unique(decision_time_us), session_time_us).all():
        raise ValueError("StockMixer v2 label decision time is outside panel coverage")
    time_decreases = decision_time_us[1:] < decision_time_us[:-1]
    horizon_decreases = (decision_time_us[1:] == decision_time_us[:-1]) & (
        row_horizons[1:] < row_horizons[:-1]
    )
    if np.any(time_decreases | horizon_decreases):
        raise ValueError("StockMixer v2 label rows are not time-horizon canonical")
    same_group = (decision_time_us[1:] == decision_time_us[:-1]) & (
        row_horizons[1:] == row_horizons[:-1]
    )
    starts = np.flatnonzero(np.concatenate(([True], ~same_group)))
    ends = np.concatenate((starts[1:], [len(row_ids)]))
    row_count_by_group = {
        (int(decision_time_us[start]), int(row_horizons[start])): int(end - start)
        for start, end in zip(starts, ends, strict=True)
    }
    return TemporalPanel(
        manifest_path=manifest_path.resolve(),
        content_digest=cast(str, manifest["content_digest"]),
        source_raw_export_digest=cast(str, manifest["source_raw_export_digest"]),
        source_materialization_digest=cast(str, manifest["source_materialization_digest"]),
        horizons=horizons,
        lookback=lookback,
        instrument_ids=instrument_ids,
        sessions=sessions,
        context_columns=context_columns,
        temporal_features=temporal,
        context_features=context,
        feature_mask=feature_mask,
        context_mask=context_mask,
        presence_mask=presence_mask,
        tradable_mask=tradable_mask,
        row_ids=row_ids,
        row_decision_time_us=decision_time_us,
        row_instrument_ids=row_instrument_ids,
        row_horizons=row_horizons,
        labels=labels,
        training_eligible=eligible,
        session_index_us={int(value): index for index, value in enumerate(session_time_us)},
        instrument_index=panel_instrument_index,
        row_count_by_decision_horizon=row_count_by_group,
    )


def build_temporal_batch(panel: TemporalPanel, *, row_ids: tuple[int, ...]) -> TemporalBatch:
    """Build full decision-time cross-sections for the requested label rows."""

    if not row_ids or len(set(row_ids)) != len(row_ids):
        raise ValueError("StockMixer v2 batch row_ids must be non-empty and unique")
    selected: dict[tuple[int, int], set[int]] = {}
    for row_id in row_ids:
        if row_id < 0 or row_id >= len(panel.row_ids):
            raise ValueError("StockMixer v2 batch row_id is unknown")
        key = (
            int(panel.row_decision_time_us[row_id]),
            int(panel.row_horizons[row_id]),
        )
        selected.setdefault(key, set()).add(row_id)
    for key, values in selected.items():
        if len(values) != panel.row_count_by_decision_horizon[key]:
            raise ValueError("StockMixer v2 batch requires a complete decision-time cross-section")
    keys = sorted(selected)
    temporal_batches = []
    feature_batches = []
    current_context = []
    context_masks = []
    presence_masks = []
    tradable_masks = []
    labels = []
    label_masks = []
    eligibility = []
    row_id_matrices = []
    decision_time_us = []
    stock_count = len(panel.instrument_ids)
    for decision_time_us_value, horizon in keys:
        endpoint = panel.session_index_us[decision_time_us_value]
        start = endpoint + 1 - panel.lookback
        if start < 0:
            raise ValueError("StockMixer v2 decision time has insufficient lookback")
        temporal_batches.append(panel.temporal_features[start : endpoint + 1].transpose(1, 0, 2))
        feature_batches.append(panel.feature_mask[start : endpoint + 1].transpose(1, 0))
        current_context.append(panel.context_features[endpoint])
        context_masks.append(panel.context_mask[endpoint])
        presence_masks.append(panel.presence_mask[endpoint])
        tradable_masks.append(panel.tradable_mask[endpoint])
        label_values = np.zeros(stock_count, dtype=np.float32)
        label_mask_values = np.zeros(stock_count, dtype=np.bool_)
        eligibility_values = np.zeros(stock_count, dtype=np.bool_)
        row_id_values = np.full(stock_count, -1, dtype=np.int64)
        for row_id in selected[(decision_time_us_value, horizon)]:
            instrument_id = cast(str, panel.row_instrument_ids[row_id].as_py())
            stock_index = panel.instrument_index[instrument_id]
            if label_mask_values[stock_index]:
                raise ValueError("StockMixer v2 batch contains duplicate label instruments")
            label_values[stock_index] = panel.labels[row_id]
            label_mask_values[stock_index] = True
            eligibility_values[stock_index] = panel.training_eligible[row_id]
            row_id_values[stock_index] = row_id
        labels.append(label_values)
        label_masks.append(label_mask_values)
        eligibility.append(eligibility_values)
        row_id_matrices.append(row_id_values)
        decision_time_us.append(decision_time_us_value)
    return TemporalBatch(
        temporal_features=torch.from_numpy(np.stack(temporal_batches)),
        current_context=torch.from_numpy(np.stack(current_context)),
        feature_mask=torch.from_numpy(np.stack(feature_batches)),
        context_mask=torch.from_numpy(np.stack(context_masks)),
        presence_mask=torch.from_numpy(np.stack(presence_masks)),
        tradable_mask=torch.from_numpy(np.stack(tradable_masks)),
        labels=torch.from_numpy(np.stack(labels)),
        label_mask=torch.from_numpy(np.stack(label_masks)),
        training_eligible=torch.from_numpy(np.stack(eligibility)),
        row_ids=torch.from_numpy(np.stack(row_id_matrices)),
        decision_time_us=torch.tensor(decision_time_us, dtype=torch.int64),
    )


def _canonical_panel_axis(
    table: Any,
    *,
    instrument_count: int,
    session_count: int,
) -> tuple[tuple[str, ...], tuple[datetime, ...]]:
    encoded = cast(
        pa.DictionaryArray,
        pc.dictionary_encode(table["instrument_id"]).combine_chunks(),
    )
    instruments = tuple(cast(list[str], encoded.dictionary.to_pylist()))
    if instruments != tuple(sorted(set(instruments))):
        raise ValueError("StockMixer v2 panel instruments are not canonical")
    encoded_indices = np.asarray(encoded.indices.to_numpy(), dtype=np.int32).reshape(
        session_count, instrument_count
    )
    expected_indices = np.arange(instrument_count, dtype=np.int32)
    if not np.all(encoded_indices == expected_indices):
        raise ValueError("StockMixer v2 panel instrument coverage mismatch")
    slot_time_us = (
        np.asarray(table["slot_time"].to_numpy(), dtype="datetime64[us]")
        .astype(np.int64)
        .reshape(session_count, instrument_count)
    )
    if not np.all(slot_time_us == slot_time_us[:, :1]):
        raise ValueError("StockMixer v2 panel session coverage mismatch")
    session_values = slot_time_us[:, 0]
    if np.any(session_values[1:] <= session_values[:-1]):
        raise ValueError("StockMixer v2 panel sessions are not canonical")
    session_offsets = pa.array(
        np.arange(0, session_count * instrument_count, instrument_count),
        type=pa.int64(),
    )
    sessions = tuple(cast(list[datetime], table["slot_time"].take(session_offsets).to_pylist()))
    return instruments, sessions


def _float_cube(
    table: Any,
    columns: tuple[str, ...],
    session_count: int,
    instrument_count: int,
) -> np.ndarray:
    values = np.stack(
        [np.asarray(table[name].to_numpy(), dtype=np.float32) for name in columns],
        axis=-1,
    ).reshape(session_count, instrument_count, len(columns))
    if not np.isfinite(values).all():
        raise ValueError("StockMixer v2 panel contains non-finite values")
    return values


def _bool_matrix(table: Any, name: str, sessions: int, instruments: int) -> np.ndarray:
    return np.asarray(table[name].to_numpy(), dtype=np.bool_).reshape(sessions, instruments)


def _sealed_file(
    root: Path,
    value: object,
    expected_path: str,
    label: str,
    *,
    expected_rows: int | None = None,
) -> Path:
    if not isinstance(value, dict) or value.get("path") != expected_path:
        raise ValueError(f"StockMixer v2 {label} file schema mismatch")
    if expected_rows is not None and value.get("row_count") != expected_rows:
        raise ValueError(f"StockMixer v2 {label} row count mismatch")
    path = root / expected_path
    if not path.is_file() or value.get("digest") != _file_digest(path):
        raise ValueError(f"StockMixer v2 {label} digest mismatch")
    return path


def _columns(value: dict[str, Any], key: str) -> tuple[str, ...]:
    raw = value.get(key)
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(item, str) or not item for item in raw)
        or len(set(raw)) != len(raw)
    ):
        raise ValueError(f"StockMixer v2 {key} schema mismatch")
    return tuple(raw)


def _horizons(value: dict[str, Any]) -> tuple[int, ...]:
    raw = value.get("horizons")
    if (
        not isinstance(raw, list)
        or raw != sorted(set(raw))
        or any(item not in {1, 5, 10} for item in raw)
    ):
        raise ValueError("StockMixer v2 horizons schema mismatch")
    return tuple(raw)


def _positive_integer(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError(f"StockMixer v2 {key} must be a positive integer")
    return raw


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"

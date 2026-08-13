"""Deterministic dynamic-universe panels for the isolated StockMixer runner."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.market_bars import MarketBar
from astraquant_domain.run_manifest import canonical_json_bytes

STOCKMIXER_REQUEST_SCHEMA = "astraquant.stockmixer-request/v1"
STOCKMIXER_UPSTREAM_COMMIT = "cce13598afd3ff33ae317700a85ae08db0554652"
STOCKMIXER_INPUT_COLUMNS = ("open", "high", "low", "close", "volume")

_DIGEST = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")


class ObservationLike(Protocol):
    @property
    def instrument_id(self) -> str: ...

    @property
    def local_row_id(self) -> int: ...

    @property
    def timestamp(self) -> datetime: ...


class InstrumentLike(Protocol):
    @property
    def instrument_id(self) -> str: ...

    @property
    def rows(self) -> Sequence[dict[str, float | int]]: ...

    @property
    def raw_bars(self) -> Sequence[MarketBar]: ...

    @property
    def row_bar_indices(self) -> Sequence[int]: ...


class PanelLike(Protocol):
    @property
    def instruments(self) -> Sequence[InstrumentLike]: ...

    @property
    def rows(self) -> Sequence[dict[str, float | int]]: ...

    @property
    def observations(self) -> Sequence[ObservationLike]: ...


class FoldLike(Protocol):
    @property
    def fold_id(self) -> str: ...

    @property
    def train_indices(self) -> Sequence[int]: ...

    @property
    def test_indices(self) -> Sequence[int]: ...


@dataclass(frozen=True, slots=True)
class StockMixerSource:
    dataset_id: str
    instrument_id: str
    source_snapshot_id: str


@dataclass(frozen=True, slots=True)
class UniverseMembership:
    universe_id: str
    universe_snapshot_id: str
    members_by_time: Mapping[datetime, frozenset[str]]


@dataclass(frozen=True, slots=True)
class StockMixerExport:
    content_digest: str
    request_path: Path
    panel_path: Path
    samples_path: Path
    sample_count: int


def export_stockmixer_request(
    *,
    output_root: Path,
    panel: PanelLike,
    folds: Sequence[FoldLike],
    sources: Sequence[StockMixerSource],
    universe: UniverseMembership,
    lookback: int,
    label_name: str,
) -> StockMixerExport:
    """Atomically export a sealed, time-aligned dynamic-universe request."""
    root = output_root.resolve()
    if root.exists():
        raise ValueError("StockMixer export output_root must not already exist")
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback <= 0:
        raise ValueError("StockMixer lookback must be a positive integer")
    if not label_name.strip():
        raise ValueError("StockMixer label_name must not be empty")

    instruments = _validate_panel(panel)
    instrument_ids = tuple(sorted(instruments))
    exact_sources = _validate_sources(sources, instrument_ids)
    timeline, memberships, universe_value = _validate_universe(universe, instrument_ids)
    exact_folds, fold_value = _validate_folds(panel, folds)
    bars_by_instrument = {
        instrument_id: _bars_by_time(instruments[instrument_id])
        for instrument_id in instrument_ids
    }
    labels = _labels_by_identity(panel, instruments, label_name)
    timeline_index = {timestamp: index for index, timestamp in enumerate(timeline)}

    sample_specs: list[tuple[str, str, datetime]] = []
    for fold in exact_folds:
        for segment, indices in (("train", fold.train_indices), ("test", fold.test_indices)):
            decision_times = sorted({panel.observations[index].timestamp for index in indices})
            for decision_time in decision_times:
                position = timeline_index.get(decision_time)
                if position is None:
                    raise ValueError("fold decision timestamp is absent from universe timeline")
                if position + 1 >= lookback:
                    sample_specs.append((fold.fold_id, segment, decision_time))
    sample_specs.sort(key=lambda item: (item[0], item[2], item[1]))
    if not sample_specs:
        raise ValueError("StockMixer export has no eligible samples")

    required_slot_times = tuple(
        sorted(
            {
                slot_time
                for _, _, decision_time in sample_specs
                for slot_time in timeline[
                    timeline_index[decision_time] + 1 - lookback : timeline_index[decision_time] + 1
                ]
            }
        )
    )
    rows: list[dict[str, object]] = []
    for slot_time in required_slot_times:
        current_members = memberships[slot_time]
        for instrument_id in instrument_ids:
            bar = bars_by_instrument[instrument_id].get(slot_time)
            presence = instrument_id in current_members
            feature_mask = presence and bar is not None
            tradable = feature_mask and bar is not None and bar.volume > 0
            raw_label = labels.get((instrument_id, slot_time))
            label_mask = tradable and raw_label is not None
            label = raw_label if label_mask and raw_label is not None else 0.0
            if feature_mask and bar is not None:
                if bar.timestamp != slot_time:
                    raise ValueError("StockMixer bar does not match its market time slot")
                feature_values = {
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                }
                event_time: datetime | None = bar.timestamp
            else:
                feature_values = {name: 0.0 for name in STOCKMIXER_INPUT_COLUMNS}
                event_time = None
            rows.append(
                {
                    "slot_time": slot_time,
                    "instrument_id": instrument_id,
                    "event_time": event_time,
                    "feature_mask": feature_mask,
                    "presence_mask": presence,
                    "tradable_mask": tradable,
                    "label_mask": label_mask,
                    "label": label,
                    **feature_values,
                }
            )

    slot_indices = {timestamp: index for index, timestamp in enumerate(required_slot_times)}
    sample_rows: list[dict[str, object]] = []
    for sample_id, (fold_id, segment, decision_time) in enumerate(sample_specs):
        position = timeline_index[decision_time]
        window_times = timeline[position + 1 - lookback : position + 1]
        start_index = slot_indices[window_times[0]]
        end_index = slot_indices[window_times[-1]] + 1
        if end_index - start_index != lookback:
            raise ValueError("StockMixer sample window is not contiguous in panel slots")
        sample_rows.append(
            {
                "fold_id": fold_id,
                "segment": segment,
                "sample_id": sample_id,
                "decision_time": decision_time,
                "window_start_index": start_index,
                "window_end_index": end_index,
            }
        )

    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=root.parent,
        prefix=f".{root.name}-staging-",
        ignore_cleanup_errors=True,
    ) as staging_name:
        staging = Path(staging_name)
        staged_panel = staging / "panel.parquet"
        staged_samples = staging / "samples.parquet"
        pq.write_table(
            pa.Table.from_pylist(rows, schema=_panel_schema()),
            staged_panel,
            compression="zstd",
            version="2.6",
        )
        panel_digest = _file_digest(staged_panel)
        pq.write_table(
            pa.Table.from_pylist(sample_rows, schema=_samples_schema()),
            staged_samples,
            compression="zstd",
            version="2.6",
        )
        samples_digest = _file_digest(staged_samples)
        body: dict[str, object] = {
            "schema_version": STOCKMIXER_REQUEST_SCHEMA,
            "upstream_commit": STOCKMIXER_UPSTREAM_COMMIT,
            "provider_id": "eastmoney",
            "sources": [
                {
                    "dataset_id": source.dataset_id,
                    "instrument_id": source.instrument_id,
                    "source_snapshot_id": source.source_snapshot_id,
                }
                for source in exact_sources
            ],
            "universe": universe_value,
            "folds_digest": _object_digest(fold_value),
            "panel_file": {"path": "panel.parquet", "digest": panel_digest},
            "samples_file": {"path": "samples.parquet", "digest": samples_digest},
            "sample_count": len(sample_rows),
            "input_columns": list(STOCKMIXER_INPUT_COLUMNS),
            "lookback": lookback,
            "label_name": label_name,
        }
        content_digest = _object_digest(body)
        (staging / "request.json").write_text(
            json.dumps(
                {"content_digest": content_digest, **body},
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        staging.replace(root)

    return StockMixerExport(
        content_digest=content_digest,
        request_path=root / "request.json",
        panel_path=root / "panel.parquet",
        samples_path=root / "samples.parquet",
        sample_count=len(sample_specs),
    )


def _validate_panel(panel: PanelLike) -> dict[str, InstrumentLike]:
    exact = tuple(panel.instruments)
    identifiers = tuple(item.instrument_id for item in exact)
    if (
        not identifiers
        or any(not value for value in identifiers)
        or len(set(identifiers)) != len(identifiers)
    ):
        raise ValueError("StockMixer panel instruments must be non-empty and unique")
    if len(panel.rows) != len(panel.observations):
        raise ValueError("StockMixer panel rows and observations must align")
    instruments = {item.instrument_id: item for item in exact}
    for instrument in exact:
        if len(instrument.rows) != len(instrument.row_bar_indices):
            raise ValueError("StockMixer instrument rows and bar mapping must align")
        if len({bar.timestamp for bar in instrument.raw_bars}) != len(instrument.raw_bars):
            raise ValueError("StockMixer raw bars must have unique timestamps")
    for observation in panel.observations:
        matched = instruments.get(observation.instrument_id)
        if matched is None or observation.local_row_id < 0:
            raise ValueError("StockMixer observation instrument or row identity is invalid")
        if observation.local_row_id >= len(matched.row_bar_indices):
            raise ValueError("StockMixer observation local row is out of range")
        bar_index = matched.row_bar_indices[observation.local_row_id]
        if bar_index < 0 or bar_index >= len(matched.raw_bars):
            raise ValueError("StockMixer observation bar mapping is out of range")
        if matched.raw_bars[bar_index].timestamp != observation.timestamp:
            raise ValueError("StockMixer observation decision time does not match its bar")
    return instruments


def _validate_sources(
    sources: Sequence[StockMixerSource], instrument_ids: tuple[str, ...]
) -> tuple[StockMixerSource, ...]:
    exact = tuple(sources)
    if len(exact) != len(instrument_ids):
        raise ValueError("StockMixer sources must match panel instruments exactly")
    normalized = []
    for source in exact:
        if not source.dataset_id or not source.instrument_id:
            raise ValueError("StockMixer sources require dataset and instrument identities")
        normalized.append(
            StockMixerSource(
                dataset_id=source.dataset_id,
                instrument_id=source.instrument_id,
                source_snapshot_id=_exact_digest(
                    source.source_snapshot_id, "StockMixer source snapshot"
                ),
            )
        )
    if sorted(source.instrument_id for source in normalized) != list(instrument_ids):
        raise ValueError("StockMixer sources must match panel instruments exactly")
    return tuple(sorted(normalized, key=lambda item: item.instrument_id))


def _validate_universe(
    universe: UniverseMembership, instrument_ids: tuple[str, ...]
) -> tuple[tuple[datetime, ...], dict[datetime, frozenset[str]], dict[str, object]]:
    if not universe.universe_id.strip():
        raise ValueError("StockMixer universe_id must not be empty")
    snapshot_id = _exact_digest(
        universe.universe_snapshot_id, "StockMixer universe snapshot"
    )
    if not universe.members_by_time:
        raise ValueError("StockMixer universe timeline must not be empty")
    allowed = set(instrument_ids)
    memberships: dict[datetime, frozenset[str]] = {}
    for timestamp, members in universe.members_by_time.items():
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("StockMixer universe timestamps must be timezone-aware")
        exact_members = frozenset(members)
        if not exact_members.issubset(allowed):
            raise ValueError("StockMixer universe contains instruments without sources")
        memberships[timestamp] = exact_members
    timeline = tuple(sorted(memberships))
    ever_present = set().union(*(memberships[timestamp] for timestamp in timeline))
    missing = allowed - ever_present
    if missing:
        raise ValueError(
            "StockMixer universe never includes panel instruments: " + ", ".join(sorted(missing))
        )
    return (
        timeline,
        memberships,
        {
            "id": universe.universe_id,
            "snapshot_id": snapshot_id,
            "timeline_digest": _object_digest(
                [
                    {
                        "decision_time": timestamp.isoformat(),
                        "members": sorted(memberships[timestamp]),
                    }
                    for timestamp in timeline
                ]
            ),
        },
    )


def _validate_folds(
    panel: PanelLike, folds: Sequence[FoldLike]
) -> tuple[tuple[FoldLike, ...], list[dict[str, object]]]:
    exact = tuple(folds)
    if not exact or len({fold.fold_id for fold in exact}) != len(exact):
        raise ValueError("StockMixer folds must be non-empty and uniquely named")
    values: list[dict[str, object]] = []
    all_by_time: dict[datetime, set[int]] = {}
    for index, observation in enumerate(panel.observations):
        all_by_time.setdefault(observation.timestamp, set()).add(index)
    for fold in exact:
        train = tuple(fold.train_indices)
        test = tuple(fold.test_indices)
        combined = (*train, *test)
        if (
            not fold.fold_id
            or not train
            or not test
            or len(set(train)) != len(train)
            or len(set(test)) != len(test)
            or set(train) & set(test)
            or min(combined) < 0
            or max(combined) >= len(panel.observations)
        ):
            raise ValueError(f"invalid StockMixer fold: {fold.fold_id}")
        train_times = {panel.observations[index].timestamp for index in train}
        test_times = {panel.observations[index].timestamp for index in test}
        if train_times & test_times:
            raise ValueError("StockMixer fold splits the same decision timestamp")
        for timestamp in train_times:
            if {index for index in train if panel.observations[index].timestamp == timestamp} != (
                all_by_time[timestamp]
            ):
                raise ValueError("StockMixer fold omits rows from a train decision timestamp")
        for timestamp in test_times:
            if {index for index in test if panel.observations[index].timestamp == timestamp} != (
                all_by_time[timestamp]
            ):
                raise ValueError("StockMixer fold omits rows from a test decision timestamp")
        if max(train_times) >= min(test_times):
            raise ValueError("StockMixer fold train timestamps must precede test timestamps")
        values.append(
            {
                "fold_id": fold.fold_id,
                "train_indices": list(train),
                "test_indices": list(test),
            }
        )
    return tuple(sorted(exact, key=lambda item: item.fold_id)), values


def _bars_by_time(instrument: InstrumentLike) -> dict[datetime, MarketBar]:
    return {bar.timestamp: bar for bar in instrument.raw_bars}


def _labels_by_identity(
    panel: PanelLike,
    instruments: Mapping[str, InstrumentLike],
    label_name: str,
) -> dict[tuple[str, datetime], float]:
    labels: dict[tuple[str, datetime], float] = {}
    for observation in panel.observations:
        instrument = instruments[observation.instrument_id]
        row = instrument.rows[observation.local_row_id]
        value = row.get(label_name)
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise ValueError(f"StockMixer label {label_name} must be finite and numeric")
        identity = (observation.instrument_id, observation.timestamp)
        if identity in labels:
            raise ValueError("StockMixer labels contain duplicate instrument timestamps")
        labels[identity] = float(value)
    return labels


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
            *(
                pa.field(name, pa.float64(), nullable=False)
                for name in STOCKMIXER_INPUT_COLUMNS
            ),
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


def _exact_digest(value: str, name: str) -> str:
    match = _DIGEST.fullmatch(value)
    if match is None or set(match.group(1)) == {"0"}:
        raise ValueError(f"{name} must be an exact non-sentinel SHA-256 identity")
    return f"sha256:{match.group(1)}"


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _object_digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

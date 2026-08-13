"""Deterministic, look-ahead-safe OHLCVA windows for the Kronos runner."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.market_bars import MarketBar
from astraquant_domain.run_manifest import canonical_json_bytes

KRONOS_REQUEST_SCHEMA = "astraquant.kronos-request/v1"
KRONOS_UPSTREAM_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
KRONOS_MODEL_ID = "NeoQuasar/Kronos-base"
KRONOS_MODEL_REVISION = "2b554741eca47781b64468546e77fef3e85130e6"
KRONOS_TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
KRONOS_TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"
KRONOS_INPUT_COLUMNS = ("open", "high", "low", "close", "volume", "amount")

_DIGEST = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


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


class ForecastCalendarLike(Protocol):
    @property
    def calendar_snapshot_id(self) -> str: ...

    def future_times(
        self, *, instrument_id: str, decision_time: datetime, count: int
    ) -> Sequence[datetime]: ...


@dataclass(frozen=True, slots=True)
class KronosSource:
    dataset_id: str
    instrument_id: str
    source_snapshot_id: str


@dataclass(frozen=True, slots=True)
class KronosArtifact:
    artifact_id: str
    revision: str
    weights_path: str
    weights_digest: str


@dataclass(frozen=True, slots=True)
class KronosExport:
    content_digest: str
    request_path: Path
    windows_path: Path
    eligible_row_ids: tuple[int, ...]


def export_kronos_request(
    *,
    output_root: Path,
    panel: PanelLike,
    folds: Sequence[FoldLike],
    sources: Sequence[KronosSource],
    model: KronosArtifact,
    tokenizer: KronosArtifact,
    context_length: int,
    prediction_length: int,
    seed: int,
    temperature: float,
    top_k: int,
    top_p: float,
    sample_count: int,
    calendar: ForecastCalendarLike,
) -> KronosExport:
    """Atomically export eligible test windows and a sealed Kronos request."""
    root = output_root.resolve()
    if root.exists():
        raise ValueError("Kronos export output_root must not already exist")
    exact_sources = _validate_sources(sources, panel)
    exact_folds, fold_values = _validate_folds(folds, row_count=len(panel.rows))
    _validate_artifact(
        model,
        name="model",
        expected_id=KRONOS_MODEL_ID,
        expected_revision=KRONOS_MODEL_REVISION,
    )
    _validate_artifact(
        tokenizer,
        name="tokenizer",
        expected_id=KRONOS_TOKENIZER_ID,
        expected_revision=KRONOS_TOKENIZER_REVISION,
    )
    _positive_integer(context_length, "context_length", maximum=512)
    _positive_integer(prediction_length, "prediction_length")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be positive and finite")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 0:
        raise ValueError("top_k must be a non-negative integer")
    if not math.isfinite(top_p) or not 0 < top_p <= 1:
        raise ValueError("top_p must be in (0, 1]")
    _positive_integer(sample_count, "sample_count")
    calendar_snapshot_id = _exact_digest(
        calendar.calendar_snapshot_id, "calendar_snapshot_id"
    )

    instrument_by_id = {item.instrument_id: item for item in panel.instruments}
    window_rows: list[dict[str, object]] = []
    request_rows: list[dict[str, object]] = []
    eligible_row_ids: list[int] = []
    for fold in exact_folds:
        for row_id in fold.test_indices:
            observation = panel.observations[row_id]
            instrument = instrument_by_id[observation.instrument_id]
            if observation.local_row_id >= len(instrument.row_bar_indices):
                raise ValueError("panel local row mapping is out of range")
            bar_index = instrument.row_bar_indices[observation.local_row_id]
            if bar_index < 0 or bar_index >= len(instrument.raw_bars):
                raise ValueError("panel raw bar mapping is out of range")
            if bar_index + 1 < context_length:
                continue
            current = instrument.raw_bars[bar_index]
            if current.timestamp != observation.timestamp:
                raise ValueError("panel decision time does not match its current raw bar")
            window = tuple(instrument.raw_bars[bar_index + 1 - context_length : bar_index + 1])
            if any(item.timestamp > observation.timestamp for item in window):
                raise ValueError("Kronos window contains data after decision time")
            forecast_times = tuple(
                calendar.future_times(
                    instrument_id=observation.instrument_id,
                    decision_time=observation.timestamp,
                    count=prediction_length,
                )
            )
            if (
                len(forecast_times) != prediction_length
                or any(
                    item.tzinfo is None
                    or item.utcoffset() is None
                    or item <= observation.timestamp
                    for item in forecast_times
                )
                or any(
                    previous >= current
                    for previous, current in pairwise(forecast_times)
                )
            ):
                raise ValueError("calendar forecast times must be aware, future and increasing")
            identity = {
                "fold_id": fold.fold_id,
                "row_id": row_id,
                "instrument_id": observation.instrument_id,
                "decision_time": observation.timestamp.isoformat(),
                "forecast_times": [item.isoformat() for item in forecast_times],
            }
            request_rows.append(identity)
            eligible_row_ids.append(row_id)
            window_rows.extend(
                {
                    "fold_id": fold.fold_id,
                    "row_id": row_id,
                    "instrument_id": observation.instrument_id,
                    "decision_time": observation.timestamp,
                    "sequence_index": sequence_index,
                    "event_time": bar.timestamp,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                    "amount": float(bar.turnover),
                }
                for sequence_index, bar in enumerate(window)
            )
    if not request_rows:
        raise ValueError("Kronos export has no eligible test rows")

    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=root.parent,
        prefix=f".{root.name}-staging-",
        ignore_cleanup_errors=True,
    ) as staging_name:
        staging = Path(staging_name)
        staged_windows = staging / "windows.parquet"
        pq.write_table(
            _window_table(window_rows),
            staged_windows,
            compression="zstd",
            version="2.6",
        )
        windows_digest = _file_digest(staged_windows)
        body: dict[str, object] = {
            "schema_version": KRONOS_REQUEST_SCHEMA,
            "upstream_commit": KRONOS_UPSTREAM_COMMIT,
            "provider_id": "eastmoney",
            "sources": [
                {
                    "dataset_id": item.dataset_id,
                    "instrument_id": item.instrument_id,
                    "source_snapshot_id": item.source_snapshot_id,
                }
                for item in exact_sources
            ],
            "windows_file": {"path": "windows.parquet", "digest": windows_digest},
            "folds_digest": _object_digest(fold_values),
            "calendar_snapshot_id": calendar_snapshot_id,
            "rows": request_rows,
            "input_columns": list(KRONOS_INPUT_COLUMNS),
            "model": _artifact_value(model),
            "tokenizer": _artifact_value(tokenizer),
            "device_policy": {"preferred": "AUTO", "allow_cpu_fallback": True},
            "seed": seed,
            "context_length": context_length,
            "prediction_length": prediction_length,
            "sampling": {
                "temperature": temperature,
                "top_k": top_k,
                "top_p": top_p,
                "sample_count": sample_count,
            },
        }
        content_digest = _object_digest(body)
        (staging / "request.json").write_text(
            json.dumps(
                {"content_digest": content_digest, **body},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        staging.replace(root)

    return KronosExport(
        content_digest=content_digest,
        request_path=root / "request.json",
        windows_path=root / "windows.parquet",
        eligible_row_ids=tuple(eligible_row_ids),
    )


def _validate_sources(
    sources: Sequence[KronosSource], panel: PanelLike
) -> tuple[KronosSource, ...]:
    exact = tuple(sources)
    panel_ids = {item.instrument_id for item in panel.instruments}
    if not exact or {item.instrument_id for item in exact} != panel_ids:
        raise ValueError("Kronos sources must match panel instruments exactly")
    if len({item.instrument_id for item in exact}) != len(exact):
        raise ValueError("Kronos sources must have unique instruments")
    normalized = []
    for item in exact:
        if not item.dataset_id or not item.instrument_id:
            raise ValueError("Kronos sources require dataset and instrument identities")
        normalized.append(replace_source_digest(item))
    return tuple(sorted(normalized, key=lambda item: item.instrument_id))


def replace_source_digest(source: KronosSource) -> KronosSource:
    match = _DIGEST.fullmatch(source.source_snapshot_id)
    if match is None or set(match.group(1)) == {"0"}:
        raise ValueError("source snapshot must be an exact non-sentinel SHA-256 identity")
    return KronosSource(
        dataset_id=source.dataset_id,
        instrument_id=source.instrument_id,
        source_snapshot_id=f"sha256:{match.group(1)}",
    )


def _validate_folds(
    folds: Sequence[FoldLike], *, row_count: int
) -> tuple[tuple[FoldLike, ...], list[dict[str, object]]]:
    exact = tuple(folds)
    if not exact or len({fold.fold_id for fold in exact}) != len(exact):
        raise ValueError("Kronos folds must be non-empty and uniquely named")
    values: list[dict[str, object]] = []
    for fold in exact:
        train = tuple(fold.train_indices)
        test = tuple(fold.test_indices)
        indices = (*train, *test)
        if (
            not fold.fold_id
            or not train
            or not test
            or len(set(train)) != len(train)
            or len(set(test)) != len(test)
            or set(train) & set(test)
            or min(indices) < 0
            or max(indices) >= row_count
            or max(train) >= min(test)
        ):
            raise ValueError(f"invalid Kronos fold: {fold.fold_id}")
        values.append(
            {
                "fold_id": fold.fold_id,
                "train_indices": list(train),
                "test_indices": list(test),
            }
        )
    return exact, values


def _validate_artifact(
    artifact: KronosArtifact,
    *,
    name: str,
    expected_id: str,
    expected_revision: str,
) -> None:
    if artifact.artifact_id != expected_id:
        raise ValueError(f"Kronos {name} id mismatch")
    if not _COMMIT.fullmatch(artifact.revision) or artifact.revision != expected_revision:
        raise ValueError(f"Kronos {name} revision mismatch")
    weights_path = Path(artifact.weights_path)
    if not artifact.weights_path or weights_path.is_absolute() or ".." in weights_path.parts:
        raise ValueError(f"Kronos {name} weights path must be safe and relative")
    _exact_digest(artifact.weights_digest, f"Kronos {name} weights digest")


def _artifact_value(artifact: KronosArtifact) -> dict[str, object]:
    return {
        "id": artifact.artifact_id,
        "revision": artifact.revision,
        "weights": {
            "path": artifact.weights_path,
            "digest": _exact_digest(artifact.weights_digest, "artifact digest"),
        },
    }


def _positive_integer(value: object, name: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must not exceed {maximum}")
    return value


def _exact_digest(value: str, name: str) -> str:
    match = _DIGEST.fullmatch(value)
    if match is None or set(match.group(1)) == {"0"}:
        raise ValueError(f"{name} must be an exact non-sentinel SHA-256 identity")
    return f"sha256:{match.group(1)}"


def _window_table(rows: list[dict[str, object]]) -> pa.Table:
    schema = pa.schema(
        [
            pa.field("fold_id", pa.string(), nullable=False),
            pa.field("row_id", pa.int64(), nullable=False),
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("decision_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("sequence_index", pa.int16(), nullable=False),
            pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("open", pa.float64(), nullable=False),
            pa.field("high", pa.float64(), nullable=False),
            pa.field("low", pa.float64(), nullable=False),
            pa.field("close", pa.float64(), nullable=False),
            pa.field("volume", pa.float64(), nullable=False),
            pa.field("amount", pa.float64(), nullable=False),
        ],
        metadata={b"schema_version": KRONOS_REQUEST_SCHEMA.encode("ascii")},
    )
    return pa.Table.from_pylist(rows, schema=schema)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _object_digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

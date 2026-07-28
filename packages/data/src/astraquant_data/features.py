"""Immutable, reproducible FeatureFrame snapshot storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import uuid4

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_domain import Bar, FeatureFrame, FeatureRow, InstrumentId

_IDENTITY_COLUMNS = frozenset({"instrument_id", "event_time", "available_time"})
BASELINE_FEATURE_VERSION = "returns-volume-v1"


def build_baseline_features(
    bars: Sequence[Bar],
    decision_time: datetime,
) -> FeatureFrame:
    """Build deterministic daily return and volume-change features as of a cutoff."""

    cutoff = _require_aware("decision_time", decision_time)
    latest_rows: dict[tuple[str, str, datetime], Bar] = {}
    for bar in bars:
        if bar.event_time > cutoff or bar.available_time > cutoff:
            continue
        key = (str(bar.instrument_id), bar.frequency.value, bar.event_time)
        previous_revision = latest_rows.get(key)
        if previous_revision is None or bar.available_time > previous_revision.available_time:
            latest_rows[key] = bar

    by_instrument: dict[str, list[Bar]] = {}
    for bar in latest_rows.values():
        by_instrument.setdefault(str(bar.instrument_id), []).append(bar)

    feature_rows: list[FeatureRow] = []
    for instrument_id in sorted(by_instrument):
        instrument_bars = sorted(
            by_instrument[instrument_id],
            key=lambda bar: (bar.event_time, bar.available_time),
        )
        for previous, current in pairwise(instrument_bars):
            close_return = (
                None if previous.close == 0 else float(current.close / previous.close - 1)
            )
            volume_change = (
                None if previous.volume == 0 else float(current.volume / previous.volume - 1)
            )
            feature_rows.append(
                FeatureRow(
                    instrument_id=current.instrument_id,
                    event_time=current.event_time,
                    available_time=max(
                        previous.available_time,
                        current.available_time,
                    ),
                    values={
                        "return_1d": close_return,
                        "volume_change_1d": volume_change,
                    },
                )
            )

    return FeatureFrame(
        decision_time=cutoff,
        definition_version=BASELINE_FEATURE_VERSION,
        rows=tuple(feature_rows),
    )


class PublishedFeatureSnapshot:
    def __init__(
        self,
        *,
        snapshot_id: str,
        snapshot_path: Path,
        manifest_path: Path,
        parquet_path: Path,
    ) -> None:
        self.snapshot_id = snapshot_id
        self.snapshot_path = snapshot_path
        self.manifest_path = manifest_path
        self.parquet_path = parquet_path


class FeatureSnapshotStore:
    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root.resolve()
        self._staging_root = self._data_root / ".staging"
        self._snapshots_root = self._data_root / "features" / "snapshots"
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._snapshots_root.mkdir(parents=True, exist_ok=True)

    def publish(
        self,
        frame: FeatureFrame,
        *,
        input_snapshot_ids: Sequence[str],
        code_revision: str,
        parameters: Mapping[str, object],
    ) -> PublishedFeatureSnapshot:
        revision = code_revision.strip()
        if not revision or "dirty" in revision.lower():
            raise ValueError("code_revision must identify a clean source revision")
        inputs = sorted(set(input_snapshot_ids))
        if not inputs or any(not item.strip() for item in inputs):
            raise ValueError("input_snapshot_ids must not be empty")
        if not frame.rows:
            raise ValueError("cannot publish an empty FeatureFrame")
        feature_names = tuple(frame.rows[0].values)
        if _IDENTITY_COLUMNS & set(feature_names):
            raise ValueError("feature names collide with identity columns")

        staging = self._staging_root / str(uuid4())
        staging.mkdir()
        try:
            parquet_path = staging / "features.parquet"
            pq.write_table(
                _frame_to_table(frame, feature_names),
                parquet_path,
                compression="zstd",
                version="2.6",
            )
            _fsync_file(parquet_path)
            body: dict[str, Any] = {
                "schema_version": 1,
                "kind": "feature_frame",
                "definition_version": frame.definition_version,
                "feature_names": list(feature_names),
                "decision_time": frame.decision_time.astimezone(UTC).isoformat(),
                "input_snapshot_ids": inputs,
                "code_revision": revision,
                "parameters": dict(sorted(parameters.items())),
                "row_count": len(frame.rows),
                "file": {
                    "path": "features.parquet",
                    "sha256": _sha256_file(parquet_path),
                },
            }
            snapshot_id = hashlib.sha256(_canonical_json(body)).hexdigest()
            manifest = {"snapshot_id": snapshot_id, **body}
            manifest_path = staging / "manifest.json"
            manifest_path.write_bytes(_canonical_json(manifest) + b"\n")
            _fsync_file(manifest_path)

            target = self._snapshots_root / snapshot_id
            if target.exists():
                existing = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
                if existing != manifest:
                    raise RuntimeError("feature snapshot hash collision")
                shutil.rmtree(staging)
            else:
                os.replace(staging, target)
            return PublishedFeatureSnapshot(
                snapshot_id=snapshot_id,
                snapshot_path=target,
                manifest_path=target / "manifest.json",
                parquet_path=target / "features.parquet",
            )
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def load(
        self,
        manifest_path: Path,
        *,
        decision_time: datetime,
    ) -> FeatureFrame:
        cutoff = _require_aware("decision_time", decision_time)
        approved_manifest = manifest_path.resolve()
        _require_inside(approved_manifest, self._data_root)
        manifest: dict[str, Any] = json.loads(approved_manifest.read_text(encoding="utf-8"))
        snapshot_id = manifest.pop("snapshot_id")
        if hashlib.sha256(_canonical_json(manifest)).hexdigest() != snapshot_id:
            raise ValueError("feature manifest hash does not match its content")
        parquet_path = (approved_manifest.parent / manifest["file"]["path"]).resolve()
        _require_inside(parquet_path, approved_manifest.parent)
        if _sha256_file(parquet_path) != manifest["file"]["sha256"]:
            raise ValueError("feature Parquet hash does not match its manifest")

        table = pq.ParquetFile(parquet_path).read()
        feature_names = tuple(manifest["feature_names"])
        rows = tuple(
            row for row in _table_to_rows(table, feature_names) if row.available_time <= cutoff
        )
        return FeatureFrame(
            decision_time=cutoff,
            definition_version=manifest["definition_version"],
            rows=rows,
        )


def _frame_to_table(frame: FeatureFrame, feature_names: tuple[str, ...]) -> pa.Table:
    schema = pa.schema(
        [
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("available_time", pa.timestamp("us", tz="UTC"), nullable=False),
            *(pa.field(name, pa.float64()) for name in feature_names),
        ]
    )
    rows = sorted(
        frame.rows,
        key=lambda row: (
            str(row.instrument_id),
            row.event_time,
            row.available_time,
        ),
    )
    return pa.Table.from_pylist(
        [
            {
                "instrument_id": str(row.instrument_id),
                "event_time": row.event_time.astimezone(UTC),
                "available_time": row.available_time.astimezone(UTC),
                **row.values,
            }
            for row in rows
        ],
        schema=schema,
    )


def _table_to_rows(
    table: pa.Table,
    feature_names: tuple[str, ...],
) -> tuple[FeatureRow, ...]:
    return tuple(
        FeatureRow(
            instrument_id=InstrumentId.parse(item["instrument_id"]),
            event_time=item["event_time"],
            available_time=item["available_time"],
            values={name: item[name] for name in feature_names},
        )
        for item in table.to_pylist()
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb+") as handle:
        os.fsync(handle.fileno())


def _require_aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_inside(path: Path, root: Path) -> None:
    if not path.is_relative_to(root):
        raise ValueError("feature snapshot path must be inside the data root")

"""Read recorded research datasets (immutable Parquet snapshots)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.arrow_schema import table_to_bars
from astraquant_data.manifests import SnapshotManifest
from astraquant_data.market_bars import MarketBar
from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    dataset_id: str
    instrument_id: str
    bar_count: int
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class ExactDatasetSnapshot:
    dataset_id: str
    snapshot_id: str
    provider_id: str
    instrument_id: str
    frequency: str
    adjustment: str
    bars: tuple[MarketBar, ...]


_DATASET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")


def dataset_id_for(instrument_id: InstrumentId) -> str:
    return f"cn-equity-{str(instrument_id).lower().replace('.', '-')}-1m-none"


def market_bars_to_domain(
    instrument_id: InstrumentId,
    rows: Sequence[MarketBar],
) -> list[Bar]:
    return [
        Bar(
            instrument_id=instrument_id,
            frequency=BarFrequency.MINUTE,
            trading_date=row.timestamp.date(),
            event_time=row.timestamp,
            available_time=row.timestamp + timedelta(minutes=1),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            turnover=row.turnover,
            open_interest=None,
            settlement=None,
            adjustment=Adjustment.NONE,
            availability_estimated=False,
        )
        for row in rows
    ]


def publish_dataset(
    data_root: Path,
    *,
    instrument_id: InstrumentId,
    bars: Sequence[Bar],
    provider: dict[str, str],
) -> DatasetInfo:
    store = ParquetSnapshotStore(data_root)
    dataset_id = dataset_id_for(instrument_id)
    store.publish_bars(
        dataset_id=dataset_id,
        bars=list(bars),
        provider=provider,
        calendar_version="eastmoney",
        availability_policy="bar_end",
    )
    return DatasetInfo(
        dataset_id=dataset_id,
        instrument_id=str(instrument_id),
        bar_count=len(bars),
        start=min(bar.event_time for bar in bars),
        end=max(bar.event_time for bar in bars),
    )


def _to_market_bar(bar: Bar) -> MarketBar:
    return MarketBar(
        timestamp=bar.event_time,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        turnover=bar.turnover if bar.turnover is not None else bar.open,
        previous_close=bar.open,
    )


def load_dataset_bars(
    data_root: Path,
    dataset_id: str,
    *,
    snapshot_id: str | None = None,
) -> tuple[list[MarketBar], str]:
    """Load one exact snapshot, or the newest snapshot for legacy callers."""
    snapshots_root, manifest_path, manifest = _selected_dataset_manifest(
        data_root,
        dataset_id,
        snapshot_id=snapshot_id,
    )
    files = [item["path"] for item in manifest["files"]]
    bars: list[MarketBar] = []
    instrument_id = ""
    for relative in files:
        path = snapshots_root / manifest_path.parent.name / relative
        with pq.ParquetFile(path) as handle:
            table = handle.read()
        if not instrument_id and table.column_names and "instrument_id" in table.column_names:
            instrument_id = str(table.column("instrument_id")[0].as_py())
        for bar in table_to_bars(table):
            bars.append(_to_market_bar(bar))
    return sorted(bars, key=lambda item: item.timestamp), instrument_id


def load_dataset_provenance(
    data_root: Path,
    dataset_id: str,
    *,
    snapshot_id: str | None = None,
) -> tuple[str, str]:
    """Return the selected snapshot and provider identities used by research tools."""

    _, _, manifest = _selected_dataset_manifest(data_root, dataset_id, snapshot_id=snapshot_id)
    provider = manifest.get("provider")
    if not isinstance(provider, dict) or not isinstance(provider.get("id"), str):
        raise ValueError(f"dataset {dataset_id} has no provider identity")
    snapshot_id = manifest.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError(f"dataset {dataset_id} has no snapshot identity")
    return snapshot_id, provider["id"]


def load_exact_dataset_snapshot(
    data_root: Path,
    dataset_id: str,
    *,
    snapshot_id: str,
) -> ExactDatasetSnapshot:
    """Load and hash-verify one exact immutable legacy dataset snapshot."""

    if not _DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise ValueError("dataset_id must be canonical")
    exact_snapshot_id = snapshot_id.removeprefix("sha256:")
    if (
        len(exact_snapshot_id) != 64
        or any(character not in "0123456789abcdef" for character in exact_snapshot_id)
        or set(exact_snapshot_id) == {"0"}
    ):
        raise ValueError("snapshot_id must be an exact non-sentinel SHA-256 identity")
    snapshot_root = (
        data_root.resolve()
        / "datasets"
        / dataset_id
        / "snapshots"
        / exact_snapshot_id
    )
    manifest_path = snapshot_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"snapshot {exact_snapshot_id} not found for dataset {dataset_id}")
    manifest = SnapshotManifest.from_path(manifest_path)
    if manifest.dataset_id != dataset_id or manifest.snapshot_id != exact_snapshot_id:
        raise ValueError("exact snapshot manifest identity mismatch")

    bars: list[Bar] = []
    observed_rows = 0
    for file in manifest.files:
        path = (snapshot_root / file.path).resolve()
        if not path.is_relative_to(snapshot_root.resolve()) or not path.is_file():
            raise ValueError("snapshot file path is invalid")
        if _sha256(path) != file.sha256:
            raise ValueError(f"snapshot file digest mismatch: {file.path}")
        with pq.ParquetFile(path) as handle:
            if handle.metadata.num_rows != file.rows:
                raise ValueError(f"snapshot file row count mismatch: {file.path}")
            table = handle.read()
        exact_bars = table_to_bars(table)
        observed_rows += len(exact_bars)
        bars.extend(exact_bars)
    if observed_rows != manifest.row_count or not bars:
        raise ValueError("snapshot row count does not match manifest")
    instrument_ids = {str(bar.instrument_id) for bar in bars}
    frequencies = {bar.frequency.value for bar in bars}
    adjustments = {bar.adjustment.value for bar in bars}
    if len(instrument_ids) != 1 or len(frequencies) != 1 or len(adjustments) != 1:
        raise ValueError("exact research snapshot must contain one instrument series")
    ordered = tuple(sorted((_to_market_bar(bar) for bar in bars), key=lambda bar: bar.timestamp))
    if len({bar.timestamp for bar in ordered}) != len(ordered):
        raise ValueError("exact research snapshot contains duplicate timestamps")
    provider_id = manifest.provider.get("id", "")
    if not provider_id:
        raise ValueError("exact research snapshot has no provider identity")
    return ExactDatasetSnapshot(
        dataset_id=dataset_id,
        snapshot_id=exact_snapshot_id,
        provider_id=provider_id,
        instrument_id=next(iter(instrument_ids)),
        frequency=next(iter(frequencies)),
        adjustment=next(iter(adjustments)),
        bars=ordered,
    )


def _selected_dataset_manifest(
    data_root: Path,
    dataset_id: str,
    *,
    snapshot_id: str | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    snapshots_root = data_root / "datasets" / dataset_id / "snapshots"
    if snapshot_id is None:
        manifests = sorted(snapshots_root.glob("*/manifest.json"))
        if not manifests:
            raise ValueError(f"no snapshots found for dataset {dataset_id}")
        manifest_path = manifests[-1]
    else:
        if (
            len(snapshot_id) != 64
            or any(character not in "0123456789abcdef" for character in snapshot_id)
            or set(snapshot_id) == {"0"}
        ):
            raise ValueError("snapshot_id must be a non-sentinel SHA-256 identity")
        manifest_path = snapshots_root / snapshot_id / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"snapshot {snapshot_id} not found for dataset {dataset_id}")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"dataset {dataset_id} manifest must be an object")
    if snapshot_id is not None and value.get("snapshot_id") != snapshot_id:
        raise ValueError(f"snapshot manifest identity mismatch for dataset {dataset_id}")
    return snapshots_root, manifest_path, value


def list_datasets(data_root: Path) -> list[DatasetInfo]:
    datasets_root = data_root / "datasets"
    if not datasets_root.exists():
        return []
    result: list[DatasetInfo] = []
    for dataset_id in sorted(dataset_id.name for dataset_id in datasets_root.iterdir()):
        snapshots_root = datasets_root / dataset_id / "snapshots"
        manifests = sorted(snapshots_root.glob("*/manifest.json"))
        if not manifests:
            continue
        manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
        instrument_id = _instrument_from_manifest(manifests[-1].parent)
        result.append(
            DatasetInfo(
                dataset_id=dataset_id,
                instrument_id=instrument_id,
                bar_count=int(manifest.get("row_count", 0)),
                start=datetime.fromisoformat(manifest["min_event_time"]),
                end=datetime.fromisoformat(manifest["max_event_time"]),
            )
        )
    return result


def _instrument_from_manifest(snapshot_dir: Path) -> str:
    for relative in ("market=cn",):
        for partition in (snapshot_dir / relative).glob("*"):
            for frequency_dir in partition.glob("*"):
                for trading_date_dir in frequency_dir.glob("*"):
                    part_files = list(trading_date_dir.glob("part-*.parquet"))
                    if not part_files:
                        continue
                    with pq.ParquetFile(part_files[0]) as handle:
                        table = handle.read()
                    if "instrument_id" in table.column_names:
                        return str(table.column("instrument_id")[0].as_py())
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

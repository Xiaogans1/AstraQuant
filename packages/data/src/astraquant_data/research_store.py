"""Read recorded research datasets (immutable Parquet snapshots)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.arrow_schema import table_to_bars
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


def load_dataset_bars(data_root: Path, dataset_id: str) -> tuple[list[MarketBar], str]:
    """Load the newest recorded snapshot of a dataset as MarketBar rows."""
    snapshots_root, manifest_path, manifest = _selected_dataset_manifest(data_root, dataset_id)
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


def load_dataset_provenance(data_root: Path, dataset_id: str) -> tuple[str, str]:
    """Return the selected snapshot and provider identities used by research tools."""

    _, _, manifest = _selected_dataset_manifest(data_root, dataset_id)
    provider = manifest.get("provider")
    if not isinstance(provider, dict) or not isinstance(provider.get("id"), str):
        raise ValueError(f"dataset {dataset_id} has no provider identity")
    snapshot_id = manifest.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError(f"dataset {dataset_id} has no snapshot identity")
    return snapshot_id, provider["id"]


def _selected_dataset_manifest(
    data_root: Path,
    dataset_id: str,
) -> tuple[Path, Path, dict[str, Any]]:
    snapshots_root = data_root / "datasets" / dataset_id / "snapshots"
    manifests = sorted(snapshots_root.glob("*/manifest.json"))
    if not manifests:
        raise ValueError(f"no snapshots found for dataset {dataset_id}")
    manifest_path = manifests[-1]
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"dataset {dataset_id} manifest must be an object")
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

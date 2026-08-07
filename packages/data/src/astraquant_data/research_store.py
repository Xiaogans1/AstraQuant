"""Read recorded research datasets (immutable Parquet snapshots)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.arrow_schema import table_to_bars
from astraquant_data.market_bars import MarketBar
from astraquant_domain import Bar


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    dataset_id: str
    instrument_id: str
    bar_count: int
    start: datetime
    end: datetime


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
    snapshots_root = data_root / "datasets" / dataset_id / "snapshots"
    manifests = sorted(snapshots_root.glob("*/manifest.json"))
    if not manifests:
        raise ValueError(f"no snapshots found for dataset {dataset_id}")
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    files = [item["path"] for item in manifest["files"]]
    bars: list[MarketBar] = []
    instrument_id = ""
    for relative in files:
        path = snapshots_root / manifests[-1].parent.name / relative
        with pq.ParquetFile(path) as handle:
            table = handle.read()
        if not instrument_id and table.column_names and "instrument_id" in table.column_names:
            instrument_id = str(table.column("instrument_id")[0].as_py())
        for bar in table_to_bars(table):
            bars.append(_to_market_bar(bar))
    return sorted(bars, key=lambda item: item.timestamp), instrument_id


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

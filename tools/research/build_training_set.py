"""Export labeled training rows from recorded Parquet snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.arrow_schema import table_to_bars
from astraquant_data.market_bars import MarketBar
from astraquant_quant.research_features import build_training_rows

_HORIZON = 5
_THRESHOLD = Decimal("0.005")


def load_market_bars(data_root: Path, dataset_id: str) -> tuple[list[MarketBar], str]:
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


def _to_market_bar(bar: object) -> MarketBar:
    from astraquant_domain import Bar

    typed = bar if isinstance(bar, Bar) else None
    assert typed is not None
    return MarketBar(
        timestamp=typed.event_time,
        open=typed.open,
        high=typed.high,
        low=typed.low,
        close=typed.close,
        volume=typed.volume,
        turnover=typed.turnover if typed.turnover is not None else Decimal("0"),
        previous_close=typed.open,
    )


def build_features_json(
    data_root: Path,
    dataset_id: str,
    *,
    horizon: int,
    threshold: Decimal,
) -> dict[str, object]:
    bars, instrument_id = load_market_bars(data_root, dataset_id)
    if not bars:
        raise ValueError(f"dataset {dataset_id} has no bars")
    rows = build_training_rows(bars, horizon=horizon, threshold=threshold)
    return {
        "dataset_id": dataset_id,
        "instrument_id": instrument_id,
        "row_count": len(rows),
        "bar_count": len(bars),
        "date_range": (f"{bars[0].timestamp.date()}..{bars[-1].timestamp.date()}"),
        "built_at": datetime.now().isoformat(),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="build-training-set")
    parser.add_argument("dataset_id", help="dataset id like cn-equity-159516-szse-1m-none")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(".astraquant") / "data",
        help="data root (default .astraquant/data)",
    )
    parser.add_argument("--output", type=Path, default=None, help="output JSON path")
    args = parser.parse_args()
    try:
        payload = build_features_json(
            args.data_root,
            args.dataset_id,
            horizon=_HORIZON,
            threshold=_THRESHOLD,
        )
    except (ValueError, OSError) as error:
        print(f"build failed: {error}", file=sys.stderr)
        return 1
    output = args.output or (
        args.data_root.parent / "research" / f"features-{args.dataset_id}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {output} ({payload['row_count']} rows, {payload['date_range']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

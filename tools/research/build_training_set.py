"""Export labeled training rows from recorded Parquet snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from astraquant_data.research_store import load_dataset_bars, load_dataset_provenance
from astraquant_quant.research_features import build_training_bundle

_HORIZON = 5
_THRESHOLD = Decimal("0.005")


def build_features_json(
    data_root: Path,
    dataset_id: str,
    *,
    horizon: int,
    threshold: Decimal,
) -> dict[str, object]:
    bars, instrument_id = load_dataset_bars(data_root, dataset_id)
    if not bars:
        raise ValueError(f"dataset {dataset_id} has no bars")
    source_snapshot_id, provider_id = load_dataset_provenance(data_root, dataset_id)
    bundle = build_training_bundle(bars, horizon=horizon, threshold=threshold)
    return {
        "dataset_id": dataset_id,
        "source_snapshot_id": source_snapshot_id,
        "provider_id": provider_id,
        "instrument_id": instrument_id,
        "holding_bars": horizon,
        "label_price_contract": "NEXT_OPEN_TO_NEXT_OPEN",
        "row_count": len(bundle.rows),
        "bar_count": len(bars),
        "date_range": (f"{bars[0].timestamp.date()}..{bars[-1].timestamp.date()}"),
        "built_at": datetime.now().isoformat(),
        "rows": bundle.rows,
        "row_bar_indices": bundle.row_bar_indices,
        "raw_bars": [
            {
                "timestamp": bar.timestamp.isoformat(),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
                "vwap": float(bar.close if bar.volume == 0 else bar.turnover / bar.volume),
            }
            for bar in bundle.ordered_bars
        ],
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

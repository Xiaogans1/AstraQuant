"""Export one training payload for the pinned official Qlib Alpha158 runner."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from astraquant_data.exports.qlib_alpha158 import export_qlib_alpha158_request
from astraquant_data.market_bars import MarketBar
from astraquant_quant.baseline_matrix import expanding_walk_forward


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="export-qlib-alpha158")
    parser.add_argument("features_json", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--minimum-train-size", type=int, default=200)
    parser.add_argument("--test-size", type=int, default=50)
    parser.add_argument("--fold-count", type=int, default=3)
    parser.add_argument("--fee-rate", type=Decimal, default=Decimal("0.00025"))
    parser.add_argument("--prediction-threshold", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        payload = _read_payload(arguments.features_json)
        rows = _numeric_rows(payload.get("rows"))
        bars = _raw_bars(payload.get("raw_bars"))
        mapping = _integer_list(payload.get("row_bar_indices"), "row_bar_indices")
        folds = expanding_walk_forward(
            rows,
            minimum_train_size=arguments.minimum_train_size,
            test_size=arguments.test_size,
            fold_count=arguments.fold_count,
        )
        export_qlib_alpha158_request(
            output_root=arguments.output_root,
            dataset_id=_required_str(payload, "dataset_id"),
            source_snapshot_id=_required_str(payload, "source_snapshot_id"),
            provider_id=_required_str(payload, "provider_id"),
            rows=rows,
            folds=folds,
            fee_rate=arguments.fee_rate,
            prediction_threshold=arguments.prediction_threshold,
            seed=arguments.seed,
            raw_bars=bars,
            row_bar_indices=mapping,
        )
    except (OSError, ValueError, json.JSONDecodeError, ArithmeticError) as error:
        print(f"Alpha158 export failed: {error}", file=sys.stderr)
        return 1
    return 0


def _read_payload(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("training payload must be an object")
    return value


def _numeric_rows(value: object) -> list[dict[str, float | int]]:
    if not isinstance(value, list) or not value:
        raise ValueError("training payload rows must not be empty")
    rows: list[dict[str, float | int]] = []
    for raw in value:
        if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
            raise ValueError("training row must be an object")
        if any(
            isinstance(item, bool) or not isinstance(item, (int, float)) for item in raw.values()
        ):
            raise ValueError("training row values must be numeric")
        rows.append({str(key): item for key, item in raw.items()})
    return rows


def _raw_bars(value: object) -> list[MarketBar]:
    if not isinstance(value, list) or not value:
        raise ValueError("training payload raw_bars must not be empty")
    bars = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("raw bar must be an object")
        volume = Decimal(str(raw.get("volume")))
        vwap = Decimal(str(raw.get("vwap")))
        bars.append(
            MarketBar(
                timestamp=datetime.fromisoformat(_required_str(raw, "timestamp")),
                open=Decimal(str(raw.get("open"))),
                high=Decimal(str(raw.get("high"))),
                low=Decimal(str(raw.get("low"))),
                close=Decimal(str(raw.get("close"))),
                volume=volume,
                turnover=vwap * volume,
            )
        )
    return bars


def _integer_list(value: object, label: str) -> list[int]:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in value
    ):
        raise ValueError(f"{label} must be an integer list")
    return value


def _required_str(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"training payload requires {key}")
    return item


if __name__ == "__main__":
    raise SystemExit(main())

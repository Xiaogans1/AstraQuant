"""Run fair strategy baselines on one Eastmoney-derived training dataset."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from astraquant_quant.baseline_matrix import expanding_walk_forward, run_baseline_matrix


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-baseline-matrix")
    parser.add_argument("features_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-train-size", type=int, default=200)
    parser.add_argument("--test-size", type=int, default=50)
    parser.add_argument("--fold-count", type=int, default=3)
    parser.add_argument("--fee-rate", type=Decimal, default=Decimal("0.00025"))
    parser.add_argument("--prediction-threshold", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def _payload(path: Path) -> tuple[dict[str, object], list[dict[str, float | int]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ValueError("training payload must be an object")
    if raw.get("provider_id") != "eastmoney":
        raise ValueError("training payload must come from Eastmoney")
    for name in ("dataset_id", "source_snapshot_id"):
        if not isinstance(raw.get(name), str) or not str(raw[name]).strip():
            raise ValueError(f"training payload requires {name}")
    values = raw.get("rows")
    if not isinstance(values, list) or not values:
        raise ValueError("training payload rows must not be empty")
    rows: list[dict[str, float | int]] = []
    for value in values:
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise ValueError("training row must be an object")
        if any(
            isinstance(item, bool) or not isinstance(item, (int, float)) for item in value.values()
        ):
            raise ValueError("training row values must be numeric")
        rows.append({str(key): item for key, item in value.items()})
    return raw, rows


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        payload, rows = _payload(arguments.features_json)
        folds = expanding_walk_forward(
            rows,
            minimum_train_size=arguments.minimum_train_size,
            test_size=arguments.test_size,
            fold_count=arguments.fold_count,
        )
        report = run_baseline_matrix(
            rows,
            folds=folds,
            fee_rate=arguments.fee_rate,
            prediction_threshold=arguments.prediction_threshold,
            seed=arguments.seed,
        )
        output = {
            "schema_version": "astraquant.strategy-baseline-matrix/v1",
            "dataset_id": payload["dataset_id"],
            "source_snapshot_id": payload["source_snapshot_id"],
            "provider_id": "eastmoney",
            "status": report.status.value,
            "challenger": None if report.challenger is None else report.challenger.value,
            "seed": report.seed,
            "prediction_threshold": report.prediction_threshold,
            "fee_rate": str(report.fee_rate),
            "models": [
                {
                    "model": summary.model.value,
                    "auc": summary.auc,
                    "gross_return": summary.gross_return,
                    "net_return": summary.net_return,
                    "trades": summary.trades,
                    "positive_folds": summary.positive_folds,
                    "folds": [
                        {
                            "fold_id": fold.fold_id,
                            "test_rows": fold.test_rows,
                            "auc": fold.auc,
                            "gross_return": fold.gross_return,
                            "net_return": fold.net_return,
                            "trades": fold.trades,
                        }
                        for fold in summary.folds
                    ],
                }
                for summary in report.models
            ],
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"baseline matrix failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

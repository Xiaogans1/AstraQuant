"""Calibrate model buy/sell thresholds on held-out real data."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

import lightgbm as lgb

from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS as _FEATURE_COLUMNS
from tools.research.train_model import purged_train_test_split

_MIN_TRADES = 50
_FEE_RATE = Decimal("0.00025")
_CANDIDATE_BUY = (0.50, 0.55, 0.60, 0.65)
_CANDIDATE_SELL = (0.35, 0.40, 0.45, 0.50)


class CalibrationResult(TypedDict):
    rows: int
    train_rows: int
    test_rows: int
    results: list[dict[str, float]]
    recommended: dict[str, float | int]


def fit_model(
    train: list[dict[str, float | int]],
    test: list[dict[str, float | int]],
) -> tuple[list[float], list[int]]:
    model = lgb.LGBMClassifier(
        n_estimators=120,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=30,
        verbose=-1,
    )
    x_train = [[float(row[key]) for key in _FEATURE_COLUMNS] for row in train]
    y_train = [int(row["label"]) for row in train]
    x_test = [[float(row[key]) for key in _FEATURE_COLUMNS] for row in test]
    y_test = [int(row["label"]) for row in test]
    model.fit(x_train, y_train)
    proba = [float(row[1]) for row in model.predict_proba(x_test)]
    return proba, y_test


def threshold_metrics(
    proba: list[float],
    y_test: list[int],
    test: list[dict[str, float | int]],
    *,
    buy: float,
    sell: float,
    fee_rate: Decimal,
) -> dict[str, float]:
    trades_buy = sum(1 for value in proba if value >= buy)
    trades_sell = sum(1 for value in proba if value <= sell)
    gross = 0.0
    wins = 0
    for index, row in enumerate(test):
        if proba[index] >= buy:
            gross += float(row.get("future_return", 0.0))
            if float(row.get("future_return", 0.0)) > 0:
                wins += 1
    net = gross - float(fee_rate) * 2 * trades_buy
    return {
        "buy": buy,
        "sell": sell,
        "trades_buy": float(trades_buy),
        "trades_sell": float(trades_sell),
        "gross_return": gross,
        "net_return": net,
        "win_rate": (wins / trades_buy) if trades_buy else 0.0,
    }


def calibrate(
    rows: list[dict[str, float | int]],
    *,
    fee_rate: Decimal,
) -> CalibrationResult:
    train, test = purged_train_test_split(rows, test_ratio=0.3, embargo=5)
    proba, y_test = fit_model(train, test)
    results: list[dict[str, float]] = []
    for buy in _CANDIDATE_BUY:
        for sell in _CANDIDATE_SELL:
            results.append(
                threshold_metrics(
                    proba,
                    y_test,
                    test,
                    buy=buy,
                    sell=sell,
                    fee_rate=fee_rate,
                )
            )
    eligible = [item for item in results if item["trades_buy"] >= _MIN_TRADES]
    best = (
        max(eligible, key=lambda item: item["net_return"])
        if eligible
        else max(results, key=lambda item: item["net_return"])
    )
    return {
        "rows": len(rows),
        "train_rows": len(train),
        "test_rows": len(test),
        "results": results,
        "recommended": {
            "buy_threshold": best["buy"],
            "sell_threshold": best["sell"],
            "trades_buy": int(best["trades_buy"]),
            "net_return": best["net_return"],
            "win_rate": best["win_rate"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="calibrate-thresholds")
    parser.add_argument("features_json")
    parser.add_argument(
        "--output-params",
        type=Path,
        default=None,
        help="write recommended threshold params JSON here",
    )
    args = parser.parse_args()
    payload = json.loads(Path(args.features_json).read_text(encoding="utf-8"))
    result = calibrate(payload["rows"], fee_rate=_FEE_RATE)
    for item in result["results"]:
        mark = ""
        if (
            item["buy"] == result["recommended"]["buy_threshold"]
            and item["sell"] == result["recommended"]["sell_threshold"]
        ):
            mark = "  <== recommended"
        print(
            f"buy {item['buy']:.2f} sell {item['sell']:.2f} | "
            f"trades {int(item['trades_buy']):5d} | "
            f"gross {item['gross_return']:+.4f} | "
            f"net {item['net_return']:+.4f} | "
            f"win {item['win_rate']:.2f}{mark}"
        )
    print(json.dumps(result["recommended"], ensure_ascii=False))
    if args.output_params is not None:
        args.output_params.parent.mkdir(parents=True, exist_ok=True)
        args.output_params.write_text(
            json.dumps(result["recommended"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

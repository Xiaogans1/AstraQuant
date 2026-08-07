"""Train a LightGBM minute model with purged/embargo evaluation."""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path

import lightgbm as lgb

from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS as _FEATURE_COLUMNS


def purged_train_test_split(
    rows: list[dict[str, float | int]],
    *,
    test_ratio: float,
    embargo: int,
) -> tuple[list[dict[str, float | int]], list[dict[str, float | int]]]:
    """Split by time position; the embargo gap keeps labels from leaking across."""
    rows = [dict(row, _position=index) for index, row in enumerate(rows)]
    split_at = math.floor(len(rows) * (1 - test_ratio))
    return rows[:split_at], rows[split_at + embargo :]


def evaluate_model(
    train: list[dict[str, float | int]],
    test: list[dict[str, float | int]],
    *,
    fee_rate: Decimal,
) -> dict[str, float]:
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
    auc = _auc(y_test, proba)
    gross = 0.0
    trades = 0
    for index, row in enumerate(test):
        if proba[index] >= 0.6:
            trades += 1
            gross += float(row.get("future_return", 0.0))
    net = gross - float(fee_rate) * 2 * trades
    return {"auc": auc, "gross_return": gross, "net_return": net, "trades": trades}


def _auc(y_true: list[int], y_score: list[float]) -> float:
    pairs = sorted(zip(y_score, y_true, strict=True), key=lambda item: item[0])
    pos = sum(y_true)
    neg = len(y_true) - pos
    if pos == 0 or neg == 0:
        return 0.5
    rank_sum = sum(index + 1 for index, (_, y) in enumerate(pairs) if y == 1)
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m tools.research.train_model <features.json>")
        return 1
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    rows = payload["rows"]
    train, test = purged_train_test_split(rows, test_ratio=0.3, embargo=5)
    metrics = evaluate_model(train, test, fee_rate=Decimal("0.00025"))
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

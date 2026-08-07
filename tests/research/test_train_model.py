from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_quant.research_features import build_feature_rows, label_future_return
from tools.research.train_model import evaluate_model, purged_train_test_split


def _rows(count: int = 120) -> list[dict[str, float | int]]:
    closes = [Decimal(str(10 + math.sin(i / 5) * 0.5)) for i in range(count)]
    bars = [
        MarketBar(
            timestamp=datetime(2026, 8, 7, 1, 30, tzinfo=UTC) + timedelta(minutes=i),
            open=c,
            high=c + Decimal("0.01"),
            low=c - Decimal("0.01"),
            close=c,
            volume=Decimal("100"),
            turnover=c * 100,
            previous_close=Decimal("10"),
        )
        for i, c in enumerate(closes)
    ]
    features = build_feature_rows(bars)
    rows: list[dict[str, float | int]] = []
    for i, row in enumerate(features):
        index = i + 30
        label = label_future_return(bars, index=index, horizon=5, threshold=Decimal("0.005"))
        if label < 0:
            continue
        future = float((bars[index + 1].close - bars[index].close) / bars[index].close)
        rows.append({**row, "label": label, "future_return": future})
    return rows


def test_purged_split_keeps_embargo_between_train_and_test() -> None:
    rows = _rows()
    train, test = purged_train_test_split(rows, test_ratio=0.3, embargo=5)
    train_max = max(row["_position"] for row in train)
    test_min = min(row["_position"] for row in test)
    assert test_min - train_max > 5


def test_evaluate_model_reports_auc_and_cost_aware_return() -> None:
    rows = _rows()
    train, test = purged_train_test_split(rows, test_ratio=0.3, embargo=5)
    metrics = evaluate_model(train, test, fee_rate=Decimal("0.00025"))
    assert "auc" in metrics
    assert "net_return" in metrics
    assert "trades" in metrics
    assert isinstance(metrics["auc"], float)

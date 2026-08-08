from __future__ import annotations

import math
from decimal import Decimal

from tests.research.test_train_model import _rows

from tools.research.calibrate_thresholds import calibrate, threshold_metrics


def test_threshold_metrics_reports_trades_and_net() -> None:
    rows = _rows()
    train, test = __import__(
        "tools.research.train_model", fromlist=["purged_train_test_split"]
    ).purged_train_test_split(rows, test_ratio=0.3, embargo=5)
    from tools.research.calibrate_thresholds import fit_model

    proba, y_test = fit_model(train, test)
    metrics = threshold_metrics(
        proba,
        y_test,
        test,
        buy=0.5,
        sell=0.4,
        fee_rate=Decimal("0.00025"),
    )
    assert "trades_buy" in metrics
    assert "net_return" in metrics
    assert metrics["trades_buy"] >= 0
    assert math.isfinite(metrics["net_return"])


def test_calibrate_returns_recommended_thresholds() -> None:
    result = calibrate(_rows(), fee_rate=Decimal("0.00025"))
    assert "recommended" in result
    recommended = result["recommended"]
    assert isinstance(recommended["buy_threshold"], float)
    assert isinstance(recommended["sell_threshold"], float)
    assert 0.5 <= recommended["buy_threshold"] <= 0.65
    assert 0.35 <= recommended["sell_threshold"] <= 0.5
    assert isinstance(recommended["net_return"], float)
    assert result["test_rows"] > 0

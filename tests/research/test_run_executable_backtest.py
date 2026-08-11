from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS
from tools.research.export_qlib_alpha158 import main as export_main
from tools.research.run_executable_backtest import main as executable_main


def _training_payload(path: Path) -> list[dict[str, float | int]]:
    rows = [
        {
            **{name: (1.0 if row_id % 2 else -1.0) for name in MODEL_FEATURE_COLUMNS},
            "label": row_id % 2,
            "future_return": 0.01 if row_id % 2 else -0.01,
        }
        for row_id in range(60)
    ]
    path.write_text(
        json.dumps(
            {
                "dataset_id": "s1-fixture",
                "source_snapshot_id": "1" * 64,
                "provider_id": "eastmoney",
                "instrument_id": "159516.SZSE",
                "holding_bars": 1,
                "label_price_contract": "NEXT_OPEN_TO_NEXT_OPEN",
                "rows": rows,
                "row_bar_indices": list(range(30, 90)),
                "raw_bars": [
                    {
                        "timestamp": (
                            datetime(2026, 8, 3, 1, 30, tzinfo=UTC) + timedelta(minutes=bar_id)
                        ).isoformat(),
                        "open": 10.0 + bar_id / 100,
                        "high": 10.0 + bar_id / 100,
                        "low": 10.0 + bar_id / 100,
                        "close": 10.0 + bar_id / 100,
                        "volume": 100000.0,
                        "vwap": 10.0 + bar_id / 100,
                    }
                    for bar_id in range(100)
                ],
            }
        ),
        encoding="utf-8",
    )
    return rows


def test_ast10_and_alpha158_share_one_executable_backtest(tmp_path: Path) -> None:
    training_path = tmp_path / "training.json"
    rows = _training_payload(training_path)
    export_root = tmp_path / "export"
    assert (
        export_main(
            [
                str(training_path),
                "--output-root",
                str(export_root),
                "--minimum-train-size",
                "30",
                "--test-size",
                "10",
                "--fold-count",
                "2",
                "--prediction-threshold",
                "0.5",
                "--seed",
                "7",
            ]
        )
        == 0
    )
    request = json.loads((export_root / "request.json").read_text(encoding="utf-8"))
    response_path = tmp_path / "response.json"
    response_path.write_text(
        json.dumps(
            {
                "schema_version": "astraquant.qlib-alpha158-response/v1",
                "request_content_digest": request["content_digest"],
                "upstream_commit": request["upstream_commit"],
                "alpha158_config_digest": request["alpha158_config_digest"],
                "alpha158_feature_count": 158,
                "feature_set": "QLIB_ALPHA158",
                "model": "qlib.contrib.model.gbdt.LGBModel",
                "predictions": [
                    {
                        "fold_id": fold["fold_id"],
                        "row_id": row_id,
                        "probability": 0.9 if int(rows[row_id]["label"]) else 0.1,
                    }
                    for fold in request["folds"]
                    for row_id in fold["test_indices"]
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "result.json"

    assert (
        executable_main(
            [
                str(export_root / "request.json"),
                str(response_path),
                "--output",
                str(output),
                "--holding-bars",
                "1",
                "--instrument-kind",
                "ETF",
                "--initial-cash",
                "100000",
                "--slippage-bps",
                "2",
                "--participation-rate",
                "0.10",
            ]
        )
        == 0
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema_version"] == "astraquant.a-share-executable-backtest/v1"
    assert result["fidelity"] == "BAR_NEXT_OPEN_CONSERVATIVE"
    assert result["shared_contract"]["test_rows"] == 20
    assert result["shared_contract"]["instrument_kind"] == "ETF"
    assert result["shared_contract"]["minimum_commission"] == "0"
    assert set(result["models"]) == {
        "ASTRA10_LIGHTGBM",
        "QLIB_ALPHA158_LIGHTGBM",
    }
    assert result["models"]["ASTRA10_LIGHTGBM"]["executed_trades"] >= 0
    assert result["models"]["QLIB_ALPHA158_LIGHTGBM"]["total_stamp_duty"] == "0"
    assert set(result["alpha158_minus_astra10"]) == {
        "executed_trades",
        "max_drawdown",
        "net_return",
        "turnover",
    }

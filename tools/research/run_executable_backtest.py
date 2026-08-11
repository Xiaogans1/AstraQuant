"""Run ASTRA10 and Qlib Alpha158 through one A-share execution contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.market_bars import MarketBar
from astraquant_quant.baseline_matrix import BaselineModel, predict_fold_probabilities
from astraquant_quant.executable_backtest import (
    ExecutableBacktestReport,
    ExecutionPolicy,
    InstrumentKind,
    run_executable_backtest,
)
from tools.research.compare_alpha158 import _rows, _validate_request, _validate_response
from tools.research.compare_qlib_baseline import (
    _read_json,
    _request_folds,
    _required_number,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-executable-backtest")
    parser.add_argument("request_json", type=Path)
    parser.add_argument("alpha158_response_json", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--holding-bars", required=True, type=int)
    parser.add_argument(
        "--instrument-kind",
        required=True,
        choices=[item.value for item in InstrumentKind],
    )
    parser.add_argument("--initial-cash", type=Decimal, default=Decimal("100000"))
    parser.add_argument("--commission-rate", type=Decimal, default=Decimal("0.00025"))
    parser.add_argument("--minimum-commission", type=Decimal, default=Decimal("5"))
    parser.add_argument("--stamp-duty-rate", type=Decimal, default=Decimal("0.0005"))
    parser.add_argument("--transfer-fee-rate", type=Decimal, default=Decimal("0.00001"))
    parser.add_argument("--slippage-bps", type=Decimal, default=Decimal("2"))
    parser.add_argument("--participation-rate", type=Decimal, default=Decimal("0.10"))
    parser.add_argument("--lot-size", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        request = _read_json(arguments.request_json)
        response = _read_json(arguments.alpha158_response_json)
        _validate_request(request)
        _validate_response(response, request)
        rows = _rows(arguments.request_json.parent, request)
        bars = _bars(arguments.request_json.parent, request)
        mapping = _row_bar_indices(request, row_count=len(rows), bar_count=len(bars))
        folds = _request_folds(request)
        threshold = _required_number(request, "prediction_threshold")
        seed = _required_seed(request)
        alpha_predictions = _predictions(response)
        astra_predictions = predict_fold_probabilities(
            BaselineModel.LIGHTGBM,
            rows,
            folds=folds,
            seed=seed,
        )
        policy = ExecutionPolicy(
            initial_cash=arguments.initial_cash,
            commission_rate=arguments.commission_rate,
            minimum_commission=arguments.minimum_commission,
            stamp_duty_rate=arguments.stamp_duty_rate,
            transfer_fee_rate=arguments.transfer_fee_rate,
            slippage_bps=arguments.slippage_bps,
            participation_rate=arguments.participation_rate,
            lot_size=arguments.lot_size,
            instrument_kind=InstrumentKind(arguments.instrument_kind),
        )
        shared = {
            "rows": rows,
            "raw_bars": bars,
            "row_bar_indices": mapping,
            "folds": folds,
            "prediction_threshold": threshold,
            "holding_bars": arguments.holding_bars,
            "policy": policy,
        }
        astra = run_executable_backtest(predictions=astra_predictions, **shared)
        alpha = run_executable_backtest(predictions=alpha_predictions, **shared)
        astra_summary = _summary(astra)
        alpha_summary = _summary(alpha)
        output = {
            "schema_version": "astraquant.a-share-executable-backtest/v1",
            "fidelity": "BAR_NEXT_OPEN_CONSERVATIVE",
            "shared_contract": {
                "dataset_id": request["dataset_id"],
                "source_snapshot_id": request["source_snapshot_id"],
                "test_rows": sum(len(fold.test_indices) for fold in folds),
                "fold_count": len(folds),
                "prediction_threshold": threshold,
                "holding_bars": arguments.holding_bars,
                "instrument_kind": policy.instrument_kind.value,
                "initial_cash_per_fold": str(policy.initial_cash),
                "commission_rate": str(policy.commission_rate),
                "minimum_commission": str(policy.minimum_commission),
                "stamp_duty_rate": str(policy.stamp_duty_rate),
                "transfer_fee_rate": str(policy.transfer_fee_rate),
                "slippage_bps": str(policy.slippage_bps),
                "participation_rate": str(policy.participation_rate),
                "lot_size": policy.lot_size,
            },
            "models": {
                "ASTRA10_LIGHTGBM": astra_summary,
                "QLIB_ALPHA158_LIGHTGBM": alpha_summary,
            },
            "alpha158_minus_astra10": {
                "net_return": alpha.net_return - astra.net_return,
                "max_drawdown": alpha.max_drawdown - astra.max_drawdown,
                "turnover": alpha.turnover - astra.turnover,
                "executed_trades": alpha.executed_trades - astra.executed_trades,
            },
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError, ArithmeticError) as error:
        print(f"executable backtest failed: {error}", file=sys.stderr)
        return 1
    return 0


def _bars(root: Path, request: dict[str, Any]) -> list[MarketBar]:
    file = request.get("bars_file")
    if not isinstance(file, dict) or file.get("path") != "bars.parquet":
        raise ValueError("Alpha158 bars file schema mismatch")
    path = root / "bars.parquet"
    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    if file.get("digest") != digest:
        raise ValueError("Alpha158 bars digest mismatch")
    values = pq.read_table(path).to_pylist()
    bars = []
    for bar_id, value in enumerate(values):
        if value.pop("bar_id", None) != bar_id:
            raise ValueError("Alpha158 bar identity mismatch")
        timestamp = value.get("timestamp")
        if not isinstance(timestamp, datetime):
            raise ValueError("Alpha158 bar timestamp schema mismatch")
        volume = Decimal(str(value.get("volume")))
        vwap = Decimal(str(value.get("vwap")))
        bars.append(
            MarketBar(
                timestamp=timestamp,
                open=Decimal(str(value.get("open"))),
                high=Decimal(str(value.get("high"))),
                low=Decimal(str(value.get("low"))),
                close=Decimal(str(value.get("close"))),
                volume=volume,
                turnover=volume * vwap,
            )
        )
    if len(bars) != request.get("bar_count"):
        raise ValueError("Alpha158 bar count mismatch")
    return bars


def _row_bar_indices(
    request: dict[str, Any],
    *,
    row_count: int,
    bar_count: int,
) -> list[int]:
    value = request.get("row_bar_indices")
    if (
        not isinstance(value, list)
        or len(value) != row_count
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
        or any(item < 0 or item >= bar_count for item in value)
    ):
        raise ValueError("Alpha158 row-bar mapping schema mismatch")
    return value


def _predictions(response: dict[str, Any]) -> list[Mapping[str, object]]:
    value = response.get("predictions")
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Alpha158 response predictions schema mismatch")
    return value


def _required_seed(request: dict[str, Any]) -> int:
    value = request.get("seed")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("seed schema mismatch")
    return value


def _summary(report: ExecutableBacktestReport) -> dict[str, object]:
    return {
        "initial_equity": str(report.initial_equity),
        "ending_equity": str(report.ending_equity),
        "gross_return": report.gross_return,
        "net_return": report.net_return,
        "executed_trades": report.executed_trades,
        "selected_signals": report.selected_signals,
        "overlap_skips": report.overlap_skips,
        "capacity_skips": report.capacity_skips,
        "invalid_interval_skips": report.invalid_interval_skips,
        "win_rate": report.win_rate,
        "turnover": report.turnover,
        "max_drawdown": report.max_drawdown,
        "total_commission": str(report.total_commission),
        "total_stamp_duty": str(report.total_stamp_duty),
        "total_transfer_fee": str(report.total_transfer_fee),
        "slippage_cost": str(report.slippage_cost),
        "folds": [
            {
                "fold_id": fold.fold_id,
                "initial_equity": str(fold.initial_equity),
                "ending_equity": str(fold.ending_equity),
                "gross_return": fold.gross_return,
                "net_return": fold.net_return,
                "executed_trades": fold.executed_trades,
                "selected_signals": fold.selected_signals,
                "overlap_skips": fold.overlap_skips,
                "capacity_skips": fold.capacity_skips,
                "invalid_interval_skips": fold.invalid_interval_skips,
                "win_rate": fold.win_rate,
                "turnover": fold.turnover,
                "max_drawdown": fold.max_drawdown,
            }
            for fold in report.folds
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())

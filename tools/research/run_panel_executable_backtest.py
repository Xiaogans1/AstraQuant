"""Run shared walk-forward models across arbitrary Eastmoney ETF datasets."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from astraquant_data.market_bars import MarketBar
from astraquant_quant.baseline_matrix import BaselineModel
from astraquant_quant.executable_backtest import ExecutionPolicy, InstrumentKind
from astraquant_quant.panel_research import (
    PanelInstrumentData,
    build_panel,
    panel_walk_forward,
    run_panel_executable_model,
)
from tools.research.build_training_set import build_features_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-panel-executable-backtest")
    parser.add_argument("dataset_ids", nargs="+")
    parser.add_argument("--data-root", type=Path, default=Path(".astraquant/data"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-train-timestamps", type=int, default=6000)
    parser.add_argument("--test-timestamp-count", type=int, default=1500)
    parser.add_argument("--fold-count", type=int, default=3)
    parser.add_argument("--holding-bars", type=int, default=5)
    parser.add_argument("--prediction-threshold", type=float, default=0.5)
    parser.add_argument("--minimum-evidence-trades", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--initial-cash", type=Decimal, default=Decimal("100000"))
    parser.add_argument("--commission-rate", type=Decimal, default=Decimal("0.00025"))
    parser.add_argument("--minimum-commission", type=Decimal, default=Decimal("0"))
    parser.add_argument("--slippage-bps", type=Decimal, default=Decimal("2"))
    parser.add_argument("--participation-rate", type=Decimal, default=Decimal("0.10"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if len(set(arguments.dataset_ids)) != len(arguments.dataset_ids):
            raise ValueError("dataset IDs must be unique")
        if arguments.minimum_evidence_trades <= 0:
            raise ValueError("minimum evidence trades must be positive")
        payloads = [
            build_features_json(
                arguments.data_root,
                dataset_id,
                horizon=arguments.holding_bars,
                threshold=Decimal("0.005"),
            )
            for dataset_id in arguments.dataset_ids
        ]
        sources = []
        instruments = []
        for payload in payloads:
            if payload.get("provider_id") != "eastmoney":
                raise ValueError(f"dataset {payload.get('dataset_id')} is not Eastmoney evidence")
            sources.append(
                {
                    "dataset_id": payload["dataset_id"],
                    "source_snapshot_id": payload["source_snapshot_id"],
                    "provider_id": payload["provider_id"],
                    "instrument_id": payload["instrument_id"],
                    "bar_count": payload["bar_count"],
                    "row_count": payload["row_count"],
                    "date_range": payload["date_range"],
                }
            )
            instruments.append(_instrument(payload))
        panel = build_panel(instruments)
        folds = panel_walk_forward(
            panel,
            minimum_train_timestamps=arguments.minimum_train_timestamps,
            test_timestamp_count=arguments.test_timestamp_count,
            fold_count=arguments.fold_count,
            purge_timestamp_count=arguments.holding_bars + 1,
        )
        policy = ExecutionPolicy(
            initial_cash=arguments.initial_cash,
            commission_rate=arguments.commission_rate,
            minimum_commission=arguments.minimum_commission,
            stamp_duty_rate=Decimal("0"),
            transfer_fee_rate=Decimal("0"),
            slippage_bps=arguments.slippage_bps,
            participation_rate=arguments.participation_rate,
            lot_size=100,
            instrument_kind=InstrumentKind.ETF,
        )
        model_reports = {}
        test_rows = sum(len(fold.test_indices) for fold in folds)
        for model in BaselineModel:
            report = run_panel_executable_model(
                panel,
                folds=folds,
                model=model,
                seed=arguments.seed,
                prediction_threshold=arguments.prediction_threshold,
                holding_bars=arguments.holding_bars,
                policy=policy,
            )
            if report.executed_trades < arguments.minimum_evidence_trades:
                evidence_status = "INSUFFICIENT_EVIDENCE"
            elif report.net_return <= 0:
                evidence_status = "NO_NET_EDGE"
            else:
                evidence_status = "CANDIDATE"
            model_reports[model.value] = {
                **asdict(report),
                "test_rows": test_rows,
                "evidence_status": evidence_status,
            }
        output = {
            "schema_version": "astraquant.multi-etf-panel-executable/v1",
            "fidelity": "BAR_NEXT_OPEN_CONSERVATIVE",
            "sources": sorted(sources, key=lambda item: str(item["instrument_id"])),
            "shared_contract": {
                "fold_count": arguments.fold_count,
                "minimum_train_timestamps": arguments.minimum_train_timestamps,
                "test_timestamp_count": arguments.test_timestamp_count,
                "purge_timestamp_count": arguments.holding_bars + 1,
                "holding_bars": arguments.holding_bars,
                "prediction_threshold": arguments.prediction_threshold,
                "seed": arguments.seed,
                "minimum_evidence_trades": arguments.minimum_evidence_trades,
                "initial_cash_per_instrument_fold": str(policy.initial_cash),
                "commission_rate": str(policy.commission_rate),
                "minimum_commission": str(policy.minimum_commission),
                "slippage_bps": str(policy.slippage_bps),
                "participation_rate": str(policy.participation_rate),
                "lot_size": policy.lot_size,
            },
            "models": model_reports,
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
            + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError, ArithmeticError, json.JSONDecodeError) as error:
        print(f"panel executable backtest failed: {error}", file=sys.stderr)
        return 1
    return 0


def _instrument(payload: Mapping[str, object]) -> PanelInstrumentData:
    instrument_id = payload.get("instrument_id")
    rows = payload.get("rows")
    raw_bars = payload.get("raw_bars")
    mapping = payload.get("row_bar_indices")
    if not isinstance(instrument_id, str) or not instrument_id:
        raise ValueError("panel instrument identity is missing")
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        raise ValueError("panel rows schema mismatch")
    if not isinstance(raw_bars, list) or any(not isinstance(item, dict) for item in raw_bars):
        raise ValueError("panel raw bars schema mismatch")
    if not isinstance(mapping, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in mapping
    ):
        raise ValueError("panel row mapping schema mismatch")
    bars = tuple(_market_bar(item) for item in raw_bars)
    typed_rows: list[dict[str, float | int]] = []
    for row in rows:
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) for value in row.values()
        ):
            raise ValueError("panel model row values must be numeric")
        typed_rows.append(dict(row))
    return PanelInstrumentData(
        instrument_id=instrument_id,
        rows=tuple(typed_rows),
        raw_bars=bars,
        row_bar_indices=tuple(mapping),
    )


def _market_bar(value: Mapping[str, object]) -> MarketBar:
    timestamp = value.get("timestamp")
    if not isinstance(timestamp, str):
        raise ValueError("panel bar timestamp schema mismatch")
    volume = Decimal(str(value.get("volume")))
    vwap = Decimal(str(value.get("vwap")))
    return MarketBar(
        timestamp=datetime.fromisoformat(timestamp),
        open=Decimal(str(value.get("open"))),
        high=Decimal(str(value.get("high"))),
        low=Decimal(str(value.get("low"))),
        close=Decimal(str(value.get("close"))),
        volume=volume,
        turnover=volume * vwap,
    )


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())

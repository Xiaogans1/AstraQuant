"""Replay an approved model over a recorded dataset and report performance."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import lightgbm as lgb

from astraquant_data.market_bars import MarketBar
from astraquant_domain import InstrumentId
from astraquant_quant.replay import ReplayResult, replay_bars
from astraquant_quant.research_features import build_feature_rows
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS
from tools.research.build_training_set import load_market_bars


def make_predictor(artifact: Path) -> Callable[[list[MarketBar]], float]:
    booster = lgb.Booster(model_file=str(artifact))

    def predict(completed: list[MarketBar]) -> float:
        window = completed[-60:]
        features = build_feature_rows(window)
        if not features:
            return 0.0
        latest = features[-1]
        proba = booster.predict([[float(latest[key]) for key in MODEL_FEATURE_COLUMNS]])
        return float(proba[0])

    return predict


def filter_bars(
    bars: list[MarketBar],
    *,
    start_date: date | None,
    end_date: date | None,
) -> list[MarketBar]:
    def keep(bar: MarketBar) -> bool:
        if start_date is not None and bar.timestamp.date() < start_date:
            return False
        return not (end_date is not None and bar.timestamp.date() > end_date)

    return [bar for bar in bars if keep(bar)]


def result_to_payload(result: ReplayResult) -> dict[str, object]:
    return {
        "instrument_id": result.instrument_id,
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "bars_count": result.bars_count,
        "initial_cash": str(result.initial_cash),
        "final_cash": str(result.final_cash),
        "realized_pnl": str(result.realized_pnl),
        "net_return_percent": result.net_return_percent,
        "buys": result.buys,
        "sells": result.sells,
        "win_rate": result.win_rate,
        "trades": [
            {
                "index": trade.index,
                "timestamp": trade.timestamp.isoformat(),
                "side": trade.side.value,
                "price": str(trade.price),
                "quantity": trade.quantity,
                "pnl": str(trade.pnl),
            }
            for trade in result.trades
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="replay-model")
    parser.add_argument("dataset_id", help="dataset id like cn-equity-159516-szse-1m-none")
    parser.add_argument("--model", required=True, help="LightGBM model file path")
    parser.add_argument("--params", required=True, help="threshold params JSON file")
    parser.add_argument("--data-root", type=Path, default=Path(".astraquant") / "data")
    parser.add_argument("--initial-cash", default="100000")
    parser.add_argument("--fee-rate", default="0.00025")
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD inclusive filter")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD inclusive filter")
    parser.add_argument("--output", type=Path, default=None, help="write result JSON here")
    args = parser.parse_args()
    try:
        params = json.loads(Path(args.params).read_text(encoding="utf-8"))
        bars, instrument_id = load_market_bars(args.data_root, args.dataset_id)
        bars = filter_bars(
            bars,
            start_date=(None if args.start_date is None else date.fromisoformat(args.start_date)),
            end_date=None if args.end_date is None else date.fromisoformat(args.end_date),
        )
        if not bars:
            raise ValueError("no bars in the selected window")
        predictor = make_predictor(Path(args.model))
        result = replay_bars(
            bars,
            instrument_id=InstrumentId.parse(instrument_id),
            predict=predictor,
            buy_threshold=float(params.get("buy_threshold", 0.6)),
            sell_threshold=float(params.get("sell_threshold", 0.4)),
            fee_rate=Decimal(args.fee_rate),
            initial_cash=Decimal(args.initial_cash),
        )
    except (ValueError, OSError) as error:
        print(f"replay failed: {error}", file=sys.stderr)
        return 1
    payload = result_to_payload(result)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

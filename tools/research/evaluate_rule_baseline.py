"""Evaluate the rule fallback strategy on recorded real minute bars."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from astraquant_data.market_bars import MarketBar
from astraquant_data.research_store import load_dataset_bars as load_market_bars
from astraquant_domain import InstrumentId, SignalAction
from astraquant_quant import evaluate_intraday_signal

_FEE_RATE = Decimal("0.00025")
_MIN_BARS = 20


def run_rule_backtest(
    bars: list[MarketBar],
    *,
    instrument_id: InstrumentId,
) -> dict[str, float | int]:
    buys = 0
    sells = 0
    holds = 0
    position_qty = 0
    entry_price: Decimal | None = None
    realized = Decimal("0")
    for index in range(_MIN_BARS - 1, len(bars) - 1):
        completed = bars[: index + 1]
        decision_time = bars[index].timestamp + timedelta(minutes=1)
        decision = evaluate_intraday_signal(
            instrument_id,
            completed,
            decision_time,
            market_live=True,
        )
        action = decision.signal.action
        price = bars[index].close
        if action is SignalAction.BUY and position_qty == 0:
            buys += 1
            position_qty = 100
            entry_price = price
        elif action is SignalAction.SELL and position_qty > 0:
            sells += 1
            assert entry_price is not None
            gross = (price - entry_price) * position_qty
            fees = gross * _FEE_RATE * 2
            realized += gross - fees
            position_qty = 0
            entry_price = None
        else:
            holds += 1
    return {
        "buys": buys,
        "sells": sells,
        "holds": holds,
        "realized_pnl": float(realized),
        "open_position": position_qty,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="evaluate-rule-baseline")
    parser.add_argument("dataset_id", help="dataset id like cn-equity-159516-szse-1m-none")
    parser.add_argument("--data-root", type=Path, default=Path(".astraquant") / "data")
    args = parser.parse_args()
    try:
        bars, instrument_id = load_market_bars(args.data_root, args.dataset_id)
        result = {
            "instrument_id": instrument_id,
            "bars": len(bars),
            **run_rule_backtest(bars, instrument_id=InstrumentId.parse(instrument_id)),
        }
    except (ValueError, OSError) as error:
        print(f"evaluation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

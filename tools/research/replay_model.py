"""Replay an approved model over a recorded dataset and report performance.

Fees follow the user's configured schedule: the CLI reads ``--fee-config``
JSON (same shape as ``GET /v1/paper/fee-config``) or, by default, the persisted
Paper fee config in the local state database. The report includes both the
user-fee net return and a zero-fee net return for comparison.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from astraquant_data.market_bars import MarketBar
from astraquant_data.research_store import load_dataset_bars as load_market_bars
from astraquant_domain import FeeSchedule, InstrumentId
from astraquant_quant.model_predictor import make_model_predictor
from astraquant_quant.replay import ReplayResult, replay_bars

_FEE_CONFIG_KEY = "paper.fee_schedule"


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


def load_user_fee_schedule(
    state_db: Path | None,
    *,
    fee_config: Path | None,
) -> FeeSchedule | None:
    """Resolve the user-configured fee schedule, preferring --fee-config JSON."""
    if fee_config is not None:
        return _fee_schedule_from_payload(json.loads(fee_config.read_text(encoding="utf-8")))
    if state_db is None or not state_db.exists():
        return None
    try:
        with sqlite3.connect(f"file:{state_db}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = ?", (_FEE_CONFIG_KEY,)
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    return _fee_schedule_from_payload(payload)


def _fee_schedule_from_payload(payload: object) -> FeeSchedule | None:
    if not isinstance(payload, dict):
        return None
    try:
        return FeeSchedule(
            commission_rate=Decimal(str(payload["commission_rate"])),
            minimum_commission=Decimal(str(payload["minimum_commission"])),
            stamp_duty_rate=Decimal(str(payload["stamp_duty_rate"])),
            transfer_fee_rate=Decimal(str(payload["transfer_fee_rate"])),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _zero_fee_schedule() -> FeeSchedule:
    return FeeSchedule(
        commission_rate=Decimal("0"),
        minimum_commission=Decimal("0"),
        stamp_duty_rate=Decimal("0"),
        transfer_fee_rate=Decimal("0"),
    )


def result_to_payload(
    result: ReplayResult,
    *,
    zero_fee_net_return_percent: float,
    fee_config: dict[str, str] | None,
) -> dict[str, object]:
    return {
        "instrument_id": result.instrument_id,
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "bars_count": result.bars_count,
        "initial_cash": str(result.initial_cash),
        "final_cash": str(result.final_cash),
        "realized_pnl": str(result.realized_pnl),
        "net_return_percent": result.net_return_percent,
        "zero_fee_net_return_percent": zero_fee_net_return_percent,
        "fee_config": fee_config,
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
    parser.add_argument("--fee-config", type=Path, default=None, help="fee schedule JSON")
    parser.add_argument(
        "--no-stamp-duty-exempt",
        action="store_true",
        help="charge stamp duty on sells (stocks); ETFs are exempt by default",
    )
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD inclusive filter")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD inclusive filter")
    parser.add_argument("--output", type=Path, default=None, help="write result JSON here")
    args = parser.parse_args()
    try:
        params = json.loads(Path(args.params).read_text(encoding="utf-8"))
        state_db = args.data_root.parent / "state" / "astraquant.sqlite3"
        fee_schedule = load_user_fee_schedule(
            state_db,
            fee_config=args.fee_config,
        )
        if fee_schedule is None:
            print(
                "warning: no user fee config found; falling back to default schedule",
                file=sys.stderr,
            )
            fee_schedule = FeeSchedule()
        bars, instrument_id = load_market_bars(args.data_root, args.dataset_id)
        bars = filter_bars(
            bars,
            start_date=(None if args.start_date is None else date.fromisoformat(args.start_date)),
            end_date=None if args.end_date is None else date.fromisoformat(args.end_date),
        )
        if not bars:
            raise ValueError("no bars in the selected window")
        predictor = make_model_predictor(Path(args.model))
        stamp_duty_exempt = not args.no_stamp_duty_exempt
        result = replay_bars(
            bars,
            instrument_id=InstrumentId.parse(instrument_id),
            predict=predictor,
            buy_threshold=float(params.get("buy_threshold", 0.6)),
            sell_threshold=float(params.get("sell_threshold", 0.4)),
            fee_schedule=fee_schedule,
            initial_cash=Decimal(args.initial_cash),
            stamp_duty_exempt=stamp_duty_exempt,
        )
        zero_result = replay_bars(
            bars,
            instrument_id=InstrumentId.parse(instrument_id),
            predict=predictor,
            buy_threshold=float(params.get("buy_threshold", 0.6)),
            sell_threshold=float(params.get("sell_threshold", 0.4)),
            fee_schedule=_zero_fee_schedule(),
            initial_cash=Decimal(args.initial_cash),
            stamp_duty_exempt=stamp_duty_exempt,
        )
    except (ValueError, OSError) as error:
        print(f"replay failed: {error}", file=sys.stderr)
        return 1
    payload = result_to_payload(
        result,
        zero_fee_net_return_percent=zero_result.net_return_percent,
        fee_config={
            "commission_rate": str(fee_schedule.commission_rate),
            "minimum_commission": str(fee_schedule.minimum_commission),
            "stamp_duty_rate": str(fee_schedule.stamp_duty_rate),
            "transfer_fee_rate": str(fee_schedule.transfer_fee_rate),
            "stamp_duty_exempt": str(stamp_duty_exempt),
        },
    )
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

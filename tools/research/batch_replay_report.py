"""Batch replay report across sector ETF datasets with the approved model.

Runs ``replay_bars`` on every recorded minute dataset with the user-configured
fee schedule (no minimum commission, 0.02% commission, ETF stamp-duty exempt),
in both cash-start and fully-invested modes, and produces a Markdown report
plus JSON payload under ``.astraquant/research/reports/``.
"""

# ruff: noqa: RUF001  # report text is Chinese documentation; full-width punctuation is intentional
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from astraquant_data.market_bars import MarketBar
from astraquant_data.research_store import load_dataset_bars
from astraquant_domain import FeeSchedule, InstrumentId, OrderSide
from astraquant_quant.model_predictor import make_model_predictor
from astraquant_quant.replay import Predictor, ReplayResult, ReplayTrade, replay_bars

_SECTOR_ETFS: dict[str, str] = {
    "512480.SSE": "半导体ETF(国联安)",
    "512880.SSE": "证券ETF(国泰)",
    "512170.SSE": "医疗ETF(华宝)",
    "515030.SSE": "新能源车ETF(华夏)",
    "512660.SSE": "军工ETF(国泰)",
    "512800.SSE": "银行ETF(华宝)",
    "512690.SSE": "酒ETF(鹏华)",
    "159819.SZSE": "人工智能ETF(易方达)",
    "159992.SZSE": "创新药ETF(银华)",
    "515790.SSE": "光伏ETF(华泰柏瑞)",
}

_BEIJING = timezone(timedelta(hours=8))


@dataclass(frozen=True, slots=True)
class InstrumentStats:
    instrument_id: str
    name: str
    bars_count: int
    start: str
    end: str
    proba: dict[str, object]
    cash: dict[str, object]
    invested: dict[str, object]


def _proba_distribution(predict: Predictor, bars: list[MarketBar]) -> dict[str, object]:
    sampled: list[float] = []
    for index in range(30, len(bars), 5):
        proba = predict(bars[: index + 1])
        if proba is not None:
            sampled.append(proba)
    if not sampled:
        return {"samples": 0}
    over_buy = sum(1 for value in sampled if value >= 0.5)
    under_sell = sum(1 for value in sampled if value <= 0.35)
    return {
        "samples": len(sampled),
        "min": round(min(sampled), 4),
        "mean": round(sum(sampled) / len(sampled), 4),
        "max": round(max(sampled), 4),
        "over_buy_threshold_ratio": round(over_buy / len(sampled), 4),
        "under_sell_threshold_ratio": round(under_sell / len(sampled), 4),
    }


def _sell_timing(trades: list[ReplayTrade]) -> dict[str, int]:
    opening = 0
    first_decision = 0
    other = 0
    for trade in trades:
        if trade.side is not OrderSide.SELL:
            continue
        local = trade.timestamp.astimezone(_BEIJING)
        minute = local.hour * 60 + local.minute
        if minute <= 9 * 60 + 33:
            opening += 1
        elif minute <= 10 * 60 + 5:
            first_decision += 1
        else:
            other += 1
    return {"opening_0930_0933": opening, "first_decision_1000": first_decision, "other": other}


def _intraday_t_pairs(trades: list[ReplayTrade]) -> int:
    pairs = 0
    previous_date: date | None = None
    previous_side: OrderSide | None = None
    for trade in trades:
        if (
            trade.side is OrderSide.BUY
            and previous_side is OrderSide.SELL
            and previous_date == trade.timestamp.date()
        ):
            pairs += 1
        previous_date = trade.timestamp.date()
        previous_side = trade.side
    return pairs


def _top2_win_concentration(result: ReplayResult) -> float:
    sells = [trade for trade in result.trades if trade.side is OrderSide.SELL]
    wins = sorted((trade.pnl for trade in sells if trade.pnl > 0), reverse=True)
    if not wins or result.realized_pnl <= 0:
        return 0.0
    return float(sum(wins[:2]) / result.realized_pnl)


def _max_single_loss_percent(result: ReplayResult, *, initial_equity: Decimal) -> float:
    worst = min(
        (trade.pnl for trade in result.trades if trade.side is OrderSide.SELL),
        default=Decimal("0"),
    )
    if initial_equity <= 0 or worst >= 0:
        return 0.0
    return float(abs(worst) / initial_equity * 100)


def _run_one(
    bars: list[MarketBar],
    *,
    instrument_id: InstrumentId,
    predict: Predictor,
    buy_threshold: float,
    sell_threshold: float,
    fee_schedule: FeeSchedule,
    initial_cash: Decimal,
    fully_invested: bool,
) -> tuple[ReplayResult, ReplayResult]:
    with_fees = replay_bars(
        bars,
        instrument_id=instrument_id,
        predict=predict,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        initial_cash=initial_cash,
        stamp_duty_exempt=True,
        fully_invested=fully_invested,
        fee_schedule=fee_schedule,
    )
    zero = replay_bars(
        bars,
        instrument_id=instrument_id,
        predict=predict,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        initial_cash=initial_cash,
        stamp_duty_exempt=True,
        fully_invested=fully_invested,
        fee_schedule=FeeSchedule(
            commission_rate=Decimal("0"),
            minimum_commission=Decimal("0"),
            stamp_duty_rate=Decimal("0"),
            transfer_fee_rate=Decimal("0"),
        ),
    )
    return with_fees, zero


def _stats_block(
    result: ReplayResult,
    zero_result: ReplayResult,
    *,
    initial_cash: Decimal,
) -> dict[str, object]:
    timing = _sell_timing(list(result.trades))
    sells = [trade for trade in result.trades if trade.side is OrderSide.SELL]
    return {
        "net_return_percent": result.net_return_percent,
        "zero_fee_net_return_percent": zero_result.net_return_percent,
        "buy_hold_return_percent": result.buy_hold_return_percent,
        "excess_return_percent": result.excess_return_percent,
        "win_rate": result.win_rate,
        "max_drawdown_percent": result.max_drawdown_percent,
        "sharpe": result.sharpe,
        "profit_factor": result.profit_factor,
        "buys": result.buys,
        "sells": result.sells,
        "realized_pnl": str(result.realized_pnl),
        "sell_timing": timing,
        "intraday_t_pairs": _intraday_t_pairs(list(result.trades)),
        "top2_win_concentration": round(_top2_win_concentration(result), 3),
        "max_single_loss_percent": round(
            _max_single_loss_percent(result, initial_equity=initial_cash), 2
        ),
        "position_remaining": result.position_remaining,
        "sell_count": len(sells),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="batch-replay-report")
    parser.add_argument("--model", required=True, help="LightGBM model file path")
    parser.add_argument("--params", required=True, help="threshold params JSON file")
    parser.add_argument("--data-root", type=Path, default=Path(".astraquant") / "data")
    parser.add_argument("--output", type=Path, default=None, help="report directory")
    parser.add_argument("--initial-cash", default="100000")
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD inclusive filter")
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    params = json.loads(Path(args.params).read_text(encoding="utf-8"))
    buy_threshold = float(params.get("buy_threshold", 0.5))
    sell_threshold = float(params.get("sell_threshold", 0.35))
    initial_cash = Decimal(args.initial_cash)
    start_date = None if args.start_date is None else date.fromisoformat(args.start_date)
    fee_schedule = FeeSchedule(
        commission_rate=Decimal("0.0002"),
        minimum_commission=Decimal("0"),
        stamp_duty_rate=Decimal("0.0005"),
        transfer_fee_rate=Decimal("0.00001"),
    )
    predictor = make_model_predictor(Path(args.model))

    stats: list[InstrumentStats] = []
    failures: list[str] = []
    for code, name in _SECTOR_ETFS.items():
        dataset_id = f"cn-equity-{code.lower().replace('.', '-')}-1m-none"
        try:
            bars, instrument_id = load_dataset_bars(data_root, dataset_id)
        except (ValueError, OSError) as error:
            failures.append(f"{code}: {error}")
            continue
        if start_date is not None:
            bars = [bar for bar in bars if bar.timestamp.date() >= start_date]
        if not bars:
            failures.append(f"{code}: no bars in window")
            continue
        instrument = InstrumentId.parse(instrument_id)
        cash, cash_zero = _run_one(
            bars,
            instrument_id=instrument,
            predict=predictor,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            fee_schedule=fee_schedule,
            initial_cash=initial_cash,
            fully_invested=False,
        )
        invested, invested_zero = _run_one(
            bars,
            instrument_id=instrument,
            predict=predictor,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            fee_schedule=fee_schedule,
            initial_cash=initial_cash,
            fully_invested=True,
        )
        stats.append(
            InstrumentStats(
                instrument_id=instrument_id,
                name=_SECTOR_ETFS[code],
                bars_count=len(bars),
                start=bars[0].timestamp.isoformat(),
                end=bars[-1].timestamp.isoformat(),
                proba=_proba_distribution(predictor, bars),
                cash=_stats_block(cash, cash_zero, initial_cash=initial_cash),
                invested=_stats_block(invested, invested_zero, initial_cash=initial_cash),
            )
        )
        print(f"done {code} {name}")

    payload = {
        "generated_at": datetime.now().isoformat(),
        "model": str(args.model),
        "params": params,
        "fee_schedule": {
            "commission_rate": str(fee_schedule.commission_rate),
            "minimum_commission": str(fee_schedule.minimum_commission),
            "stamp_duty_rate": str(fee_schedule.stamp_duty_rate),
            "transfer_fee_rate": str(fee_schedule.transfer_fee_rate),
            "stamp_duty_exempt": True,
        },
        "initial_cash": str(initial_cash),
        "start_date": start_date.isoformat() if start_date else None,
        "instruments": [asdict(item) for item in stats],
        "failures": failures,
    }

    output_dir = (args.output or data_root.parent / "research" / "reports").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "sector-etf-batch-report.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# 板块 ETF 量化核心批量回放报表")
    lines.append("")
    lines.append(f"- 生成时间:{datetime.now().isoformat()}")
    lines.append(
        f"- 模型:`{args.model}`（lgbm-minute-v1，训练集含 159516/159599/513310/515880 "
        "的 2026-07 数据；本报表为样本外诊断）"
    )
    lines.append(f"- 参数:buy_threshold={buy_threshold}，sell_threshold={sell_threshold}")
    lines.append("- 费用:用户配置（佣金万2、免最低佣金、ETF 免印花税、过户费万0.1），对照零费用")
    lines.append(f"- 初始资金:{initial_cash}；数据窗口:{start_date or '全部'} 起")
    lines.append("")
    lines.append(
        "| ETF | 模式 | 净收益% | 零费% | B&H% | 超额% | 胜率 | 回撤% | Sharpe "
        "| 买卖次数 | 开盘SELL | 10:00SELL | 做T对 | Top2贡献 | 最大单笔亏% |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for item in stats:
        for mode, label in (("cash", "空仓起"), ("invested", "全仓起")):
            block: Any = item.cash if mode == "cash" else item.invested
            lines.append(
                f"| {item.name} | {label} | "
                f"{block['net_return_percent']:.2f} | {block['zero_fee_net_return_percent']:.2f} | "
                f"{block['buy_hold_return_percent']:.2f} | {block['excess_return_percent']:+.2f} | "
                f"{block['win_rate']:.0%} | {block['max_drawdown_percent']:.2f} "
                f"| {block['sharpe']:.2f} | "
                f"{block['buys']}/{block['sells']} | {block['sell_timing']['opening_0930_0933']} | "
                f"{block['sell_timing']['first_decision_1000']} | {block['intraday_t_pairs']} | "
                f"{block['top2_win_concentration']:.0%} | {block['max_single_loss_percent']:.1f} |"
            )
    lines.append("")
    lines.append("## 模型信号强度分布（样本外诊断）")
    lines.append("")
    lines.append(
        "| ETF | 采样数 | proba 最小 | proba 均值 | proba 最大 "
        "| ≥买入阈值0.5占比 | ≤卖出阈值0.35占比 |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for item in stats:
        p: Any = item.proba
        if not p.get("samples"):
            lines.append(f"| {item.name} | 0 | - | - | - | - | - |")
            continue
        lines.append(
            f"| {item.name} | {p['samples']} | {p['min']:.3f} | {p['mean']:.3f} "
            f"| {p['max']:.3f} | "
            f"{p['over_buy_threshold_ratio']:.0%} | {p['under_sell_threshold_ratio']:.0%} |"
        )
    if failures:
        lines.append("")
        lines.append("## 失败数据集")
        for failure in failures:
            lines.append(f"- {failure}")
    lines.append("")
    lines.append(
        "> 注:净收益含用户费率；做T对 = 同日 SELL→BUY 相邻；Top2贡献 = "
        "盈利最多两笔占已实现盈利比例（集中度）；"
    )
    lines.append(
        "> 开盘SELL = 09:30–09:33 卖出笔数；10:00SELL = 当天第 30 根 bar（10:00–10:05）卖出笔数。"
    )

    report_path = output_dir / "sector-etf-batch-report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nreport: {report_path}")
    print(f"json: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

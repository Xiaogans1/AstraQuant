"""Capital-level next-open execution scoring for research predictions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum

from astraquant_data.market_bars import MarketBar
from astraquant_quant.baseline_matrix import WalkForwardFold

_CENT = Decimal("0.01")
_BPS = Decimal("10000")


class InstrumentKind(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    initial_cash: Decimal = Decimal("100000")
    commission_rate: Decimal = Decimal("0.00025")
    minimum_commission: Decimal = Decimal("5")
    stamp_duty_rate: Decimal = Decimal("0.0005")
    transfer_fee_rate: Decimal = Decimal("0.00001")
    slippage_bps: Decimal = Decimal("2")
    participation_rate: Decimal = Decimal("0.10")
    lot_size: int = 100
    instrument_kind: InstrumentKind = InstrumentKind.STOCK

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        rates = (
            self.commission_rate,
            self.minimum_commission,
            self.stamp_duty_rate,
            self.transfer_fee_rate,
            self.slippage_bps,
        )
        if any(value < 0 for value in rates):
            raise ValueError("execution costs must not be negative")
        if not 0 < self.participation_rate <= 1:
            raise ValueError("participation_rate must be in (0, 1]")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")


@dataclass(frozen=True, slots=True)
class ExecutableTrade:
    fold_id: str
    row_id: int
    decision_bar_index: int
    entry_bar_index: int
    exit_bar_index: int
    quantity: int
    entry_price: Decimal
    exit_price: Decimal
    entry_gross: Decimal
    exit_gross: Decimal
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    slippage_cost: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal


@dataclass(frozen=True, slots=True)
class ExecutableFoldMetrics:
    fold_id: str
    initial_equity: Decimal
    ending_equity: Decimal
    gross_return: float
    net_return: float
    executed_trades: int
    selected_signals: int
    overlap_skips: int
    capacity_skips: int
    invalid_interval_skips: int
    win_rate: float
    turnover: float
    max_drawdown: float


@dataclass(frozen=True, slots=True)
class ExecutableBacktestReport:
    folds: tuple[ExecutableFoldMetrics, ...]
    trades: tuple[ExecutableTrade, ...]
    initial_equity: Decimal
    ending_equity: Decimal
    gross_return: float
    net_return: float
    executed_trades: int
    selected_signals: int
    overlap_skips: int
    capacity_skips: int
    invalid_interval_skips: int
    win_rate: float
    turnover: float
    max_drawdown: float
    total_commission: Decimal
    total_stamp_duty: Decimal
    total_transfer_fee: Decimal
    slippage_cost: Decimal


@dataclass(frozen=True, slots=True)
class _Fees:
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.stamp_duty + self.transfer_fee


def run_executable_backtest(
    *,
    rows: Sequence[Mapping[str, object]],
    raw_bars: Sequence[MarketBar],
    row_bar_indices: Sequence[int],
    folds: Sequence[WalkForwardFold],
    predictions: Sequence[Mapping[str, object]],
    prediction_threshold: float,
    holding_bars: int,
    policy: ExecutionPolicy,
) -> ExecutableBacktestReport:
    if not rows or len(rows) != len(row_bar_indices):
        raise ValueError("rows and row_bar_indices must have identical non-zero length")
    if not raw_bars:
        raise ValueError("raw_bars must not be empty")
    if holding_bars <= 0:
        raise ValueError("holding_bars must be positive")
    if not 0 < prediction_threshold < 1:
        raise ValueError("prediction_threshold must be between zero and one")
    exact_folds = tuple(folds)
    if not exact_folds:
        raise ValueError("folds must not be empty")
    probabilities = _prediction_map(exact_folds, predictions)

    all_trades: list[ExecutableTrade] = []
    fold_metrics: list[ExecutableFoldMetrics] = []
    for fold in exact_folds:
        metrics, trades = _run_fold(
            fold=fold,
            raw_bars=raw_bars,
            row_bar_indices=row_bar_indices,
            probabilities=probabilities,
            prediction_threshold=prediction_threshold,
            holding_bars=holding_bars,
            policy=policy,
        )
        fold_metrics.append(metrics)
        all_trades.extend(trades)

    initial_equity = policy.initial_cash * len(fold_metrics)
    ending_equity = sum(
        (item.ending_equity for item in fold_metrics),
        start=Decimal("0"),
    )
    gross_pnl = sum((item.gross_pnl for item in all_trades), start=Decimal("0"))
    wins = sum(item.net_pnl > 0 for item in all_trades)
    turnover_notional = sum(
        (item.entry_gross + item.exit_gross for item in all_trades),
        start=Decimal("0"),
    )
    return ExecutableBacktestReport(
        folds=tuple(fold_metrics),
        trades=tuple(all_trades),
        initial_equity=initial_equity,
        ending_equity=ending_equity,
        gross_return=float(gross_pnl / initial_equity),
        net_return=float((ending_equity - initial_equity) / initial_equity),
        executed_trades=len(all_trades),
        selected_signals=sum(item.selected_signals for item in fold_metrics),
        overlap_skips=sum(item.overlap_skips for item in fold_metrics),
        capacity_skips=sum(item.capacity_skips for item in fold_metrics),
        invalid_interval_skips=sum(item.invalid_interval_skips for item in fold_metrics),
        win_rate=0.0 if not all_trades else wins / len(all_trades),
        turnover=float(turnover_notional / initial_equity),
        max_drawdown=max((item.max_drawdown for item in fold_metrics), default=0.0),
        total_commission=sum(
            (item.commission for item in all_trades),
            start=Decimal("0"),
        ),
        total_stamp_duty=sum(
            (item.stamp_duty for item in all_trades),
            start=Decimal("0"),
        ),
        total_transfer_fee=sum(
            (item.transfer_fee for item in all_trades),
            start=Decimal("0"),
        ),
        slippage_cost=sum(
            (item.slippage_cost for item in all_trades),
            start=Decimal("0"),
        ),
    )


def _run_fold(
    *,
    fold: WalkForwardFold,
    raw_bars: Sequence[MarketBar],
    row_bar_indices: Sequence[int],
    probabilities: Mapping[tuple[str, int], float],
    prediction_threshold: float,
    holding_bars: int,
    policy: ExecutionPolicy,
) -> tuple[ExecutableFoldMetrics, list[ExecutableTrade]]:
    cash = policy.initial_cash
    peak = cash
    max_drawdown = Decimal("0")
    previous_exit_index = -1
    selected_signals = 0
    overlap_skips = 0
    capacity_skips = 0
    invalid_interval_skips = 0
    trades: list[ExecutableTrade] = []

    for row_id in fold.test_indices:
        if probabilities[(fold.fold_id, row_id)] < prediction_threshold:
            continue
        selected_signals += 1
        decision_index = row_bar_indices[row_id]
        entry_index = decision_index + 1
        exit_index = decision_index + holding_bars + 1
        if decision_index < previous_exit_index:
            overlap_skips += 1
            continue
        if not _valid_interval(raw_bars, decision_index, entry_index, exit_index):
            invalid_interval_skips += 1
            continue
        entry_bar = raw_bars[entry_index]
        exit_bar = raw_bars[exit_index]
        capacity = _capacity(entry_bar, exit_bar, policy)
        if capacity < policy.lot_size:
            capacity_skips += 1
            continue
        entry_price = entry_bar.open * (Decimal("1") + policy.slippage_bps / _BPS)
        exit_price = exit_bar.open * (Decimal("1") - policy.slippage_bps / _BPS)
        quantity = _affordable_quantity(cash, entry_price, capacity, policy)
        if quantity < policy.lot_size:
            capacity_skips += 1
            continue
        entry_gross = entry_price * quantity
        exit_gross = exit_price * quantity
        buy_fees = _fees(entry_gross, is_sell=False, policy=policy)
        sell_fees = _fees(exit_gross, is_sell=True, policy=policy)
        cash = _money(cash - entry_gross - buy_fees.total + exit_gross - sell_fees.total)
        commission = buy_fees.commission + sell_fees.commission
        stamp_duty = buy_fees.stamp_duty + sell_fees.stamp_duty
        transfer_fee = buy_fees.transfer_fee + sell_fees.transfer_fee
        gross_pnl = exit_gross - entry_gross
        net_pnl = gross_pnl - commission - stamp_duty - transfer_fee
        slippage_cost = _money(
            (entry_price - entry_bar.open + exit_bar.open - exit_price) * quantity
        )
        trades.append(
            ExecutableTrade(
                fold_id=fold.fold_id,
                row_id=row_id,
                decision_bar_index=decision_index,
                entry_bar_index=entry_index,
                exit_bar_index=exit_index,
                quantity=quantity,
                entry_price=entry_price,
                exit_price=exit_price,
                entry_gross=entry_gross,
                exit_gross=exit_gross,
                commission=commission,
                stamp_duty=stamp_duty,
                transfer_fee=transfer_fee,
                slippage_cost=slippage_cost,
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
            )
        )
        previous_exit_index = exit_index
        peak = max(peak, cash)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - cash) / peak)

    gross_pnl = sum((item.gross_pnl for item in trades), start=Decimal("0"))
    wins = sum(item.net_pnl > 0 for item in trades)
    turnover = sum(
        (item.entry_gross + item.exit_gross for item in trades),
        start=Decimal("0"),
    )
    return (
        ExecutableFoldMetrics(
            fold_id=fold.fold_id,
            initial_equity=policy.initial_cash,
            ending_equity=cash,
            gross_return=float(gross_pnl / policy.initial_cash),
            net_return=float((cash - policy.initial_cash) / policy.initial_cash),
            executed_trades=len(trades),
            selected_signals=selected_signals,
            overlap_skips=overlap_skips,
            capacity_skips=capacity_skips,
            invalid_interval_skips=invalid_interval_skips,
            win_rate=0.0 if not trades else wins / len(trades),
            turnover=float(turnover / policy.initial_cash),
            max_drawdown=float(max_drawdown),
        ),
        trades,
    )


def _prediction_map(
    folds: tuple[WalkForwardFold, ...],
    predictions: Sequence[Mapping[str, object]],
) -> dict[tuple[str, int], float]:
    expected = {(fold.fold_id, row_id) for fold in folds for row_id in fold.test_indices}
    values: dict[tuple[str, int], float] = {}
    for prediction in predictions:
        fold_id = prediction.get("fold_id")
        row_id = prediction.get("row_id")
        probability = prediction.get("probability")
        if (
            not isinstance(fold_id, str)
            or isinstance(row_id, bool)
            or not isinstance(row_id, int)
            or isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not 0 <= float(probability) <= 1
        ):
            raise ValueError("prediction schema mismatch")
        key = (fold_id, row_id)
        if key in values:
            raise ValueError("prediction coverage contains duplicates")
        values[key] = float(probability)
    if set(values) != expected:
        raise ValueError("prediction coverage does not match frozen folds")
    return values


def _valid_interval(
    bars: Sequence[MarketBar],
    decision_index: int,
    entry_index: int,
    exit_index: int,
) -> bool:
    if decision_index < 0 or exit_index >= len(bars):
        return False
    trading_day = bars[decision_index].timestamp.date()
    return (
        bars[entry_index].timestamp.date() == trading_day
        and bars[exit_index].timestamp.date() == trading_day
        and bars[entry_index].volume >= 0
        and bars[exit_index].volume >= 0
    )


def _capacity(entry: MarketBar, exit: MarketBar, policy: ExecutionPolicy) -> int:
    shares = min(entry.volume, exit.volume) * policy.participation_rate
    lots = (shares / policy.lot_size).to_integral_value(rounding=ROUND_FLOOR)
    return int(lots) * policy.lot_size


def _affordable_quantity(
    cash: Decimal,
    entry_price: Decimal,
    capacity: int,
    policy: ExecutionPolicy,
) -> int:
    cash_lots = (cash / entry_price / policy.lot_size).to_integral_value(rounding=ROUND_FLOOR)
    quantity = min(int(cash_lots) * policy.lot_size, capacity)
    while quantity >= policy.lot_size:
        gross = entry_price * quantity
        if gross + _fees(gross, is_sell=False, policy=policy).total <= cash:
            return quantity
        quantity -= policy.lot_size
    return 0


def _fees(gross: Decimal, *, is_sell: bool, policy: ExecutionPolicy) -> _Fees:
    commission = max(
        _money(gross * policy.commission_rate),
        _money(policy.minimum_commission),
    )
    is_stock = policy.instrument_kind is InstrumentKind.STOCK
    stamp_duty = _money(gross * policy.stamp_duty_rate) if is_stock and is_sell else Decimal("0")
    transfer_fee = (
        _money(gross * policy.transfer_fee_rate, minimum_if_positive=True)
        if is_stock
        else Decimal("0")
    )
    return _Fees(
        commission=commission,
        stamp_duty=stamp_duty,
        transfer_fee=transfer_fee,
    )


def _money(value: Decimal, *, minimum_if_positive: bool = False) -> Decimal:
    rounded = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    if minimum_if_positive and value > 0 and rounded == 0:
        return _CENT
    return rounded

"""Time-aligned multi-instrument research panels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_quant.baseline_matrix import (
    BaselineModel,
    WalkForwardFold,
    predict_fold_probabilities,
)
from astraquant_quant.executable_backtest import ExecutionPolicy, run_executable_backtest


@dataclass(frozen=True, slots=True)
class PanelInstrumentData:
    instrument_id: str
    rows: tuple[dict[str, float | int], ...]
    raw_bars: tuple[MarketBar, ...]
    row_bar_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PanelObservation:
    instrument_id: str
    local_row_id: int
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class PanelDataset:
    instruments: tuple[PanelInstrumentData, ...]
    rows: tuple[dict[str, float | int], ...]
    observations: tuple[PanelObservation, ...]


@dataclass(frozen=True, slots=True)
class PanelInstrumentReport:
    instrument_id: str
    initial_equity: Decimal
    ending_equity: Decimal
    net_return: float
    executed_trades: int
    selected_signals: int
    win_rate: float
    turnover: float
    max_drawdown: float
    total_commission: Decimal
    total_stamp_duty: Decimal
    total_transfer_fee: Decimal
    slippage_cost: Decimal


@dataclass(frozen=True, slots=True)
class PanelExecutableReport:
    model: BaselineModel
    instruments: tuple[PanelInstrumentReport, ...]
    initial_equity: Decimal
    ending_equity: Decimal
    net_return: float
    executed_trades: int
    selected_signals: int
    win_rate: float
    turnover: float
    worst_instrument_max_drawdown: float
    total_commission: Decimal
    total_stamp_duty: Decimal
    total_transfer_fee: Decimal
    slippage_cost: Decimal


def build_panel(instruments: Sequence[PanelInstrumentData]) -> PanelDataset:
    exact = tuple(instruments)
    if not exact:
        raise ValueError("panel instruments must not be empty")
    identifiers = [item.instrument_id for item in exact]
    if any(not value for value in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("panel instrument identifiers must be non-empty and unique")
    staged: list[tuple[PanelObservation, dict[str, float | int]]] = []
    for instrument in exact:
        if not instrument.rows or len(instrument.rows) != len(instrument.row_bar_indices):
            raise ValueError("panel rows and bar mapping must have identical non-zero length")
        if not instrument.raw_bars:
            raise ValueError("panel raw bars must not be empty")
        for local_row_id, bar_index in enumerate(instrument.row_bar_indices):
            if bar_index < 0 or bar_index >= len(instrument.raw_bars):
                raise ValueError("panel bar mapping contains an invalid index")
            staged.append(
                (
                    PanelObservation(
                        instrument_id=instrument.instrument_id,
                        local_row_id=local_row_id,
                        timestamp=instrument.raw_bars[bar_index].timestamp,
                    ),
                    instrument.rows[local_row_id],
                )
            )
    staged.sort(key=lambda item: (item[0].timestamp, item[0].instrument_id, item[0].local_row_id))
    return PanelDataset(
        instruments=tuple(sorted(exact, key=lambda item: item.instrument_id)),
        rows=tuple(item[1] for item in staged),
        observations=tuple(item[0] for item in staged),
    )


def panel_walk_forward(
    panel: PanelDataset,
    *,
    minimum_train_timestamps: int,
    test_timestamp_count: int,
    fold_count: int,
    purge_timestamp_count: int,
) -> tuple[WalkForwardFold, ...]:
    if min(minimum_train_timestamps, test_timestamp_count, fold_count) <= 0:
        raise ValueError("panel walk-forward sizes must be positive")
    if purge_timestamp_count < 0:
        raise ValueError("purge timestamp count must not be negative")
    timestamps = tuple(sorted({item.timestamp for item in panel.observations}))
    initial_test_start = len(timestamps) - test_timestamp_count * fold_count
    if initial_test_start - purge_timestamp_count < minimum_train_timestamps:
        raise ValueError("insufficient timestamps for requested panel folds")
    indices_by_timestamp: dict[datetime, list[int]] = {}
    for index, observation in enumerate(panel.observations):
        indices_by_timestamp.setdefault(observation.timestamp, []).append(index)
    folds = []
    for offset in range(fold_count):
        test_start = initial_test_start + offset * test_timestamp_count
        test_end = test_start + test_timestamp_count
        train_timestamps = timestamps[: test_start - purge_timestamp_count]
        test_timestamps = timestamps[test_start:test_end]
        folds.append(
            WalkForwardFold(
                fold_id=f"fold-{offset + 1:02d}",
                train_indices=tuple(
                    index
                    for timestamp in train_timestamps
                    for index in indices_by_timestamp[timestamp]
                ),
                test_indices=tuple(
                    index
                    for timestamp in test_timestamps
                    for index in indices_by_timestamp[timestamp]
                ),
            )
        )
    return tuple(folds)


def localize_predictions(
    panel: PanelDataset,
    folds: Sequence[WalkForwardFold],
    predictions: Sequence[Mapping[str, object]],
    instrument_id: str,
) -> tuple[tuple[WalkForwardFold, ...], tuple[dict[str, object], ...]]:
    if instrument_id not in {item.instrument_id for item in panel.instruments}:
        raise ValueError(f"panel has no instrument {instrument_id}")
    exact_folds = tuple(folds)
    expected = {(fold.fold_id, index) for fold in exact_folds for index in fold.test_indices}
    values: dict[tuple[str, int], float] = {}
    for item in predictions:
        fold_id = item.get("fold_id")
        row_id = item.get("row_id")
        probability = item.get("probability")
        if (
            not isinstance(fold_id, str)
            or isinstance(row_id, bool)
            or not isinstance(row_id, int)
            or isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not 0 <= float(probability) <= 1
        ):
            raise ValueError("panel prediction schema mismatch")
        key = (fold_id, row_id)
        if key in values:
            raise ValueError("panel predictions contain duplicates")
        values[key] = float(probability)
    if set(values) != expected:
        raise ValueError("panel prediction coverage mismatch")

    local_folds = []
    local_predictions: list[dict[str, object]] = []
    for fold in exact_folds:
        train = tuple(
            panel.observations[index].local_row_id
            for index in fold.train_indices
            if panel.observations[index].instrument_id == instrument_id
        )
        test_pairs = tuple(
            (index, panel.observations[index].local_row_id)
            for index in fold.test_indices
            if panel.observations[index].instrument_id == instrument_id
        )
        local_folds.append(
            WalkForwardFold(
                fold_id=fold.fold_id,
                train_indices=train,
                test_indices=tuple(local_id for _, local_id in test_pairs),
            )
        )
        local_predictions.extend(
            {
                "fold_id": fold.fold_id,
                "row_id": local_id,
                "probability": values[(fold.fold_id, global_id)],
            }
            for global_id, local_id in test_pairs
        )
    return tuple(local_folds), tuple(local_predictions)


def run_panel_executable_model(
    panel: PanelDataset,
    *,
    folds: Sequence[WalkForwardFold],
    model: BaselineModel,
    seed: int,
    prediction_threshold: float,
    holding_bars: int,
    policy: ExecutionPolicy,
) -> PanelExecutableReport:
    exact_folds = tuple(folds)
    predictions = predict_fold_probabilities(model, panel.rows, folds=exact_folds, seed=seed)
    instrument_reports = []
    for instrument in panel.instruments:
        local_folds, local_predictions = localize_predictions(
            panel, exact_folds, predictions, instrument.instrument_id
        )
        report = run_executable_backtest(
            rows=instrument.rows,
            raw_bars=instrument.raw_bars,
            row_bar_indices=instrument.row_bar_indices,
            folds=local_folds,
            predictions=local_predictions,
            prediction_threshold=prediction_threshold,
            holding_bars=holding_bars,
            policy=policy,
        )
        instrument_reports.append(
            PanelInstrumentReport(
                instrument_id=instrument.instrument_id,
                initial_equity=report.initial_equity,
                ending_equity=report.ending_equity,
                net_return=report.net_return,
                executed_trades=report.executed_trades,
                selected_signals=report.selected_signals,
                win_rate=report.win_rate,
                turnover=report.turnover,
                max_drawdown=report.max_drawdown,
                total_commission=report.total_commission,
                total_stamp_duty=report.total_stamp_duty,
                total_transfer_fee=report.total_transfer_fee,
                slippage_cost=report.slippage_cost,
            )
        )
    exact_reports = tuple(instrument_reports)
    initial = sum((item.initial_equity for item in exact_reports), start=Decimal("0"))
    ending = sum((item.ending_equity for item in exact_reports), start=Decimal("0"))
    trades = sum(item.executed_trades for item in exact_reports)
    wins = sum(item.win_rate * item.executed_trades for item in exact_reports)
    return PanelExecutableReport(
        model=model,
        instruments=exact_reports,
        initial_equity=initial,
        ending_equity=ending,
        net_return=float((ending - initial) / initial),
        executed_trades=trades,
        selected_signals=sum(item.selected_signals for item in exact_reports),
        win_rate=0.0 if trades == 0 else wins / trades,
        turnover=sum(item.turnover * float(item.initial_equity) for item in exact_reports)
        / float(initial),
        worst_instrument_max_drawdown=max(item.max_drawdown for item in exact_reports),
        total_commission=sum((item.total_commission for item in exact_reports), start=Decimal("0")),
        total_stamp_duty=sum((item.total_stamp_duty for item in exact_reports), start=Decimal("0")),
        total_transfer_fee=sum(
            (item.total_transfer_fee for item in exact_reports), start=Decimal("0")
        ),
        slippage_cost=sum((item.slippage_cost for item in exact_reports), start=Decimal("0")),
    )

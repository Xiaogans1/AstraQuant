"""Time-aligned multi-instrument research panels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from astraquant_data.market_bars import MarketBar
from astraquant_quant.baseline_matrix import WalkForwardFold


@dataclass(frozen=True, slots=True)
class PanelInstrumentData:
    instrument_id: str
    rows: tuple[Mapping[str, object], ...]
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
    rows: tuple[Mapping[str, object], ...]
    observations: tuple[PanelObservation, ...]


def build_panel(instruments: Sequence[PanelInstrumentData]) -> PanelDataset:
    exact = tuple(instruments)
    if not exact:
        raise ValueError("panel instruments must not be empty")
    identifiers = [item.instrument_id for item in exact]
    if any(not value for value in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("panel instrument identifiers must be non-empty and unique")
    staged: list[tuple[PanelObservation, Mapping[str, object]]] = []
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

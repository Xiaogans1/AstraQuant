from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_data.market_bars import MarketBar
from astraquant_quant.panel_research import (
    PanelInstrumentData,
    build_panel,
    panel_walk_forward,
)


def _instrument(instrument_id: str, *, minutes: int = 8) -> PanelInstrumentData:
    start = datetime(2026, 8, 3, 1, 30, tzinfo=UTC)
    bars = tuple(
        MarketBar(
            timestamp=start + timedelta(minutes=index),
            open=Decimal("10") + Decimal(index) / 100,
            high=Decimal("10.2") + Decimal(index) / 100,
            low=Decimal("9.8") + Decimal(index) / 100,
            close=Decimal("10.1") + Decimal(index) / 100,
            volume=Decimal("100000"),
            turnover=Decimal("1000000"),
        )
        for index in range(minutes)
    )
    return PanelInstrumentData(
        instrument_id=instrument_id,
        rows=tuple({"label": index % 2, "future_return": 0.01} for index in range(minutes)),
        raw_bars=bars,
        row_bar_indices=tuple(range(minutes)),
    )


def test_panel_orders_shared_timestamps_without_splitting_them_across_folds() -> None:
    panel = build_panel((_instrument("B.SSE"), _instrument("A.SSE")))

    assert [item.instrument_id for item in panel.observations[:2]] == ["A.SSE", "B.SSE"]
    folds = panel_walk_forward(
        panel,
        minimum_train_timestamps=3,
        test_timestamp_count=2,
        fold_count=2,
        purge_timestamp_count=1,
    )

    for fold in folds:
        train_times = {panel.observations[index].timestamp for index in fold.train_indices}
        test_times = {panel.observations[index].timestamp for index in fold.test_indices}
        assert train_times.isdisjoint(test_times)
        assert max(train_times) < min(test_times) - timedelta(minutes=1)
        for timestamp in test_times:
            instruments = {
                panel.observations[index].instrument_id
                for index in fold.test_indices
                if panel.observations[index].timestamp == timestamp
            }
            assert instruments == {"A.SSE", "B.SSE"}


def test_panel_rejects_duplicate_instruments_and_invalid_bar_mappings() -> None:
    instrument = _instrument("A.SSE")
    with pytest.raises(ValueError, match="unique"):
        build_panel((instrument, instrument))

    invalid = PanelInstrumentData(
        instrument_id="B.SSE",
        rows=instrument.rows,
        raw_bars=instrument.raw_bars,
        row_bar_indices=(*instrument.row_bar_indices[:-1], 99),
    )
    with pytest.raises(ValueError, match="bar mapping"):
        build_panel((invalid,))

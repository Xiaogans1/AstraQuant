from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_data.market_bars import MarketBar
from astraquant_quant.cross_sectional_features import (
    CONTEXT_FEATURE_COLUMNS,
    CrossSectionalFeatureRow,
    build_cross_sectional_context_features,
    fit_robust_feature_processor,
)
from astraquant_quant.cross_sectional_labels import DailyCrossSectionalPanel


def _bar(timestamp: datetime, price: Decimal, *, rising: bool = True) -> MarketBar:
    close = price * (Decimal("1.01") if rising else Decimal("0.99"))
    return MarketBar(
        timestamp=timestamp,
        open=price,
        high=max(price, close) * Decimal("1.01"),
        low=min(price, close) * Decimal("0.99"),
        close=close,
        volume=Decimal("100000") + price,
        turnover=(Decimal("100000") + price) * close,
    )


def _panel() -> DailyCrossSectionalPanel:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    sessions = tuple(start + timedelta(days=index) for index in range(25))
    instrument_bars = {
        "A.SSE": {
            session: _bar(session, Decimal("10") + index, rising=True)
            for index, session in enumerate(sessions)
        },
        "B.SSE": {
            session: _bar(session, Decimal("30") - Decimal(index) / 2, rising=False)
            for index, session in enumerate(sessions)
        },
        "C.SSE": {
            session: _bar(session, Decimal("20") + Decimal(index) / 4, rising=True)
            for index, session in enumerate(sessions)
        },
    }
    return DailyCrossSectionalPanel(
        sessions=sessions,
        instrument_bars=instrument_bars,
        benchmark_bars={
            session: _bar(session, Decimal("100") + Decimal(index) / 10)
            for index, session in enumerate(sessions)
        },
        eligible_by_session={
            session: frozenset(instrument_bars)
            for session in sessions
        },
    )


def _row(
    rows: tuple[CrossSectionalFeatureRow, ...],
    instrument_id: str,
    decision_time: datetime,
) -> CrossSectionalFeatureRow:
    return next(
        row
        for row in rows
        if row.instrument_id == instrument_id and row.decision_time == decision_time
    )


def test_context_features_use_only_history_available_at_decision_close() -> None:
    panel = _panel()
    rows = build_cross_sectional_context_features(panel)
    decision = panel.sessions[20]
    row = _row(rows, "A.SSE", decision)

    assert tuple(row.values) == CONTEXT_FEATURE_COLUMNS
    assert row.values["return_1"] > 0
    assert row.values["relative_return_20"] > 0
    assert row.values["market_breadth"] == pytest.approx(2 / 3)
    assert row.values["price_position_20"] <= 1
    assert all(value == value for value in row.values.values())


def test_future_bar_mutation_cannot_change_past_features() -> None:
    panel = _panel()
    before = build_cross_sectional_context_features(panel)
    bars = {instrument: dict(values) for instrument, values in panel.instrument_bars.items()}
    future = bars["A.SSE"][panel.sessions[24]]
    bars["A.SSE"][panel.sessions[24]] = replace(
        future,
        close=future.close * Decimal("10"),
        high=future.high * Decimal("10"),
    )

    after = build_cross_sectional_context_features(
        replace(panel, instrument_bars=bars)
    )

    assert _row(before, "A.SSE", panel.sessions[20]) == _row(
        after,
        "A.SSE",
        panel.sessions[20],
    )


def test_membership_and_missing_window_bars_control_row_presence() -> None:
    panel = _panel()
    membership = dict(panel.eligible_by_session)
    membership[panel.sessions[20]] = frozenset({"A.SSE", "B.SSE"})
    bars = {instrument: dict(values) for instrument, values in panel.instrument_bars.items()}
    del bars["B.SSE"][panel.sessions[10]]

    rows = build_cross_sectional_context_features(
        replace(panel, eligible_by_session=membership, instrument_bars=bars)
    )

    cohort = [row.instrument_id for row in rows if row.decision_time == panel.sessions[20]]
    assert cohort == ["A.SSE"]


def test_feature_rows_are_canonical_under_instrument_mapping_permutation() -> None:
    panel = _panel()
    first = build_cross_sectional_context_features(panel)
    second = build_cross_sectional_context_features(
        replace(
            panel,
            instrument_bars=dict(reversed(tuple(panel.instrument_bars.items()))),
        )
    )

    assert first == second


def test_robust_processor_fits_only_supplied_rows_and_clips_outer_values() -> None:
    panel = _panel()
    rows = build_cross_sectional_context_features(panel)
    fit_rows = tuple(row for row in rows if row.decision_time <= panel.sessions[22])
    outer_rows = tuple(row for row in rows if row.decision_time > panel.sessions[22])

    processor = fit_robust_feature_processor(fit_rows)
    transformed = processor.transform(outer_rows)
    mutated_outer = tuple(
        replace(
            row,
            values={name: value * 100000 for name, value in row.values.items()},
        )
        for row in outer_rows
    )
    repeated = fit_robust_feature_processor(fit_rows)

    assert processor == repeated
    assert processor.fit_count == len(fit_rows)
    assert transformed
    assert all(
        -3 <= value <= 3
        for row in processor.transform(mutated_outer)
        for value in row.values.values()
    )


def test_robust_processor_rejects_empty_or_nonfinite_fit() -> None:
    with pytest.raises(ValueError, match="fit rows"):
        fit_robust_feature_processor(())
    row = CrossSectionalFeatureRow(
        decision_time=datetime(2026, 1, 5, 7, tzinfo=UTC),
        instrument_id="A.SSE",
        values={
            name: (float("inf") if index == 0 else 0.0)
            for index, name in enumerate(CONTEXT_FEATURE_COLUMNS)
        },
    )
    with pytest.raises(ValueError, match="finite"):
        fit_robust_feature_processor((row,))

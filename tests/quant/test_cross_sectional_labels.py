from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_data.market_bars import MarketBar
from astraquant_domain import CrossSectionalTaskMatrix
from astraquant_quant.cross_sectional_labels import (
    CrossSectionalLabelRow,
    DailyCrossSectionalPanel,
    build_daily_cross_sectional_labels,
)


def _bar(timestamp: datetime, price: Decimal, *, close_shift: Decimal = Decimal("0")) -> MarketBar:
    return MarketBar(
        timestamp=timestamp,
        open=price,
        high=price * Decimal("1.03"),
        low=price * Decimal("0.97"),
        close=price + close_shift,
        volume=Decimal("1000000"),
        turnover=price * Decimal("1000000"),
    )


def _panel() -> DailyCrossSectionalPanel:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    sessions = tuple(start + timedelta(days=index) for index in range(13))
    instrument_bars: dict[str, dict[datetime, MarketBar]] = {}
    instruments = tuple(f"S{index:03d}.SSE" for index in range(50))
    for instrument_index, instrument_id in enumerate(instruments):
        step = Decimal(instrument_index + 1)
        instrument_bars[instrument_id] = {
            session: _bar(session, Decimal("100") + instrument_index + session_index * step)
            for session_index, session in enumerate(sessions)
        }
    benchmark_bars = {
        session: _bar(session, Decimal("1000") + Decimal(session_index))
        for session_index, session in enumerate(sessions)
    }
    return DailyCrossSectionalPanel(
        sessions=sessions,
        instrument_bars=instrument_bars,
        benchmark_bars=benchmark_bars,
        eligible_by_session={session: frozenset(instruments) for session in sessions},
    )


def _matrix() -> CrossSectionalTaskMatrix:
    return CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI")


def _row(
    rows: tuple[CrossSectionalLabelRow, ...],
    panel: DailyCrossSectionalPanel,
    instrument_id: str,
    *,
    decision_index: int,
    horizon: int,
) -> CrossSectionalLabelRow:
    return next(
        row
        for row in rows
        if row.instrument_id == instrument_id
        and row.decision_time == panel.sessions[decision_index]
        and row.horizon_sessions == horizon
    )


def test_d5_label_uses_next_open_entry_and_open_exit() -> None:
    panel = _panel()
    rows = build_daily_cross_sectional_labels(panel, _matrix())

    d5 = _row(rows, panel, "S000.SSE", decision_index=0, horizon=5)
    entry = panel.instrument_bars["S000.SSE"][panel.sessions[1]].open
    exit_price = panel.instrument_bars["S000.SSE"][panel.sessions[6]].open

    assert d5.entry_time == panel.sessions[1]
    assert d5.exit_time == panel.sessions[6]
    assert d5.raw_return == (exit_price / entry) - 1
    assert d5.market_excess_return == d5.raw_return - d5.benchmark_return
    assert Decimal("0") <= d5.cross_sectional_rank <= Decimal("1")
    assert d5.downside_risk >= 0


def test_decision_close_cannot_change_next_open_labels() -> None:
    panel = _panel()
    before = build_daily_cross_sectional_labels(panel, _matrix())
    bars = {instrument_id: dict(values) for instrument_id, values in panel.instrument_bars.items()}
    current = bars["S000.SSE"][panel.sessions[0]]
    bars["S000.SSE"][panel.sessions[0]] = replace(
        current,
        high=current.high * Decimal("10"),
        close=current.open * Decimal("9"),
    )
    mutated = replace(panel, instrument_bars=bars)

    after = build_daily_cross_sectional_labels(mutated, _matrix())

    assert _row(before, panel, "S000.SSE", decision_index=0, horizon=5) == _row(
        after,
        mutated,
        "S000.SSE",
        decision_index=0,
        horizon=5,
    )


def test_exit_day_low_cannot_change_risk_after_open_exit() -> None:
    panel = _panel()
    before = build_daily_cross_sectional_labels(panel, _matrix())
    bars = {instrument_id: dict(values) for instrument_id, values in panel.instrument_bars.items()}
    exit_bar = bars["S000.SSE"][panel.sessions[6]]
    bars["S000.SSE"][panel.sessions[6]] = replace(
        exit_bar,
        low=Decimal("0.01"),
    )

    after = build_daily_cross_sectional_labels(
        replace(panel, instrument_bars=bars),
        _matrix(),
    )

    assert _row(before, panel, "S000.SSE", decision_index=0, horizon=5).downside_risk == _row(
        after,
        panel,
        "S000.SSE",
        decision_index=0,
        horizon=5,
    ).downside_risk


@pytest.mark.parametrize("missing_index", [1, 6])
def test_missing_entry_or_exit_removes_only_that_instrument_horizon(missing_index: int) -> None:
    panel = _panel()
    bars = {instrument_id: dict(values) for instrument_id, values in panel.instrument_bars.items()}
    del bars["S000.SSE"][panel.sessions[missing_index]]

    rows = build_daily_cross_sectional_labels(replace(panel, instrument_bars=bars), _matrix())

    matching = [
        row
        for row in rows
        if row.instrument_id == "S000.SSE"
        and row.decision_time == panel.sessions[0]
        and row.horizon_sessions == 5
    ]
    assert matching == []
    assert _row(rows, panel, "S001.SSE", decision_index=0, horizon=5)


def test_rank_and_training_tail_mask_keep_every_valid_row() -> None:
    panel = _panel()
    rows = build_daily_cross_sectional_labels(panel, _matrix())
    cohort = [
        row
        for row in rows
        if row.decision_time == panel.sessions[0] and row.horizon_sessions == 5
    ]

    assert len(cohort) == 50
    assert min(cohort, key=lambda row: row.market_excess_return).cross_sectional_rank == 0
    assert max(cohort, key=lambda row: row.market_excess_return).cross_sectional_rank == 1
    assert sum(not row.training_eligible for row in cohort) == 2
    assert not min(cohort, key=lambda row: row.market_excess_return).training_eligible
    assert not max(cohort, key=lambda row: row.market_excess_return).training_eligible


def test_rows_have_canonical_order() -> None:
    rows = build_daily_cross_sectional_labels(_panel(), _matrix())

    keys = [
        (row.decision_time, row.horizon_sessions, row.instrument_id)
        for row in rows
    ]
    assert keys == sorted(keys)


def test_panel_rejects_noncanonical_sessions() -> None:
    panel = _panel()
    with pytest.raises(ValueError, match="sessions"):
        replace(panel, sessions=tuple(reversed(panel.sessions)))


def test_panel_rejects_unknown_membership_instrument() -> None:
    panel = _panel()
    membership = dict(panel.eligible_by_session)
    membership[panel.sessions[0]] = frozenset({"UNKNOWN.SSE"})
    with pytest.raises(ValueError, match="unknown"):
        replace(panel, eligible_by_session=membership)


def test_panel_rejects_missing_benchmark_bar() -> None:
    panel = _panel()
    benchmark = dict(panel.benchmark_bars)
    del benchmark[panel.sessions[3]]
    with pytest.raises(ValueError, match="benchmark"):
        replace(panel, benchmark_bars=benchmark)

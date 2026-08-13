"""Execution-aligned daily cross-sectional labels for Stage B v2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_domain import CrossSectionalTaskMatrix


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DailyCrossSectionalPanel:
    """One immutable logical view of a daily market panel and its membership."""

    sessions: tuple[datetime, ...]
    instrument_bars: Mapping[str, Mapping[datetime, MarketBar]]
    benchmark_bars: Mapping[datetime, MarketBar]
    eligible_by_session: Mapping[datetime, frozenset[str]]

    def __post_init__(self) -> None:
        if not self.sessions:
            raise ValueError("sessions must not be empty")
        for session in self.sessions:
            _require_aware("session", session)
        if self.sessions != tuple(sorted(set(self.sessions))):
            raise ValueError("sessions must be unique and chronological")

        session_set = set(self.sessions)
        if set(self.benchmark_bars) != session_set:
            raise ValueError("benchmark bars must cover every session exactly")
        if set(self.eligible_by_session) != session_set:
            raise ValueError("eligible membership must cover every session exactly")

        known_instruments = set(self.instrument_bars)
        if not known_instruments or any(not item.strip() for item in known_instruments):
            raise ValueError("instrument bars must use non-empty instrument identifiers")
        for session, members in self.eligible_by_session.items():
            unknown = set(members) - known_instruments
            if unknown:
                raise ValueError(
                    f"eligible membership contains unknown instruments at {session.isoformat()}"
                )

        self._validate_bars("benchmark", self.benchmark_bars, session_set)
        for instrument_id, bars in self.instrument_bars.items():
            self._validate_bars(instrument_id, bars, session_set)

    @staticmethod
    def _validate_bars(
        owner: str,
        bars: Mapping[datetime, MarketBar],
        sessions: set[datetime],
    ) -> None:
        unexpected = set(bars) - sessions
        if unexpected:
            raise ValueError(f"{owner} bars contain timestamps outside sessions")
        for timestamp, bar in bars.items():
            if timestamp != bar.timestamp:
                raise ValueError(f"{owner} bar key must equal bar timestamp")


@dataclass(frozen=True, slots=True)
class CrossSectionalLabelRow:
    decision_time: datetime
    instrument_id: str
    horizon_sessions: int
    entry_time: datetime
    exit_time: datetime
    raw_return: Decimal
    benchmark_return: Decimal
    market_excess_return: Decimal
    cross_sectional_rank: Decimal
    downside_risk: Decimal
    training_eligible: bool


def build_daily_cross_sectional_labels(
    panel: DailyCrossSectionalPanel,
    matrix: CrossSectionalTaskMatrix,
) -> tuple[CrossSectionalLabelRow, ...]:
    """Build next-open labels without deleting train-only extreme observations."""

    rows: list[CrossSectionalLabelRow] = []
    for decision_index, decision_time in enumerate(panel.sessions):
        for horizon in matrix.horizons:
            entry_index = decision_index + matrix.entry_lag_sessions
            exit_index = entry_index + horizon
            if exit_index >= len(panel.sessions):
                continue
            entry_time = panel.sessions[entry_index]
            exit_time = panel.sessions[exit_index]
            benchmark_entry = panel.benchmark_bars[entry_time].open
            benchmark_exit = panel.benchmark_bars[exit_time].open
            benchmark_return = benchmark_exit / benchmark_entry - 1

            cohort: list[CrossSectionalLabelRow] = []
            required_sessions = panel.sessions[entry_index : exit_index + 1]
            risk_sessions = panel.sessions[entry_index:exit_index]
            for instrument_id in sorted(panel.eligible_by_session[decision_time]):
                bars = panel.instrument_bars[instrument_id]
                if any(session not in bars for session in required_sessions):
                    continue
                entry_open = bars[entry_time].open
                exit_open = bars[exit_time].open
                raw_return = exit_open / entry_open - 1
                holding_low = min(bars[session].low for session in risk_sessions)
                downside_risk = max(Decimal("0"), 1 - holding_low / entry_open)
                cohort.append(
                    CrossSectionalLabelRow(
                        decision_time=decision_time,
                        instrument_id=instrument_id,
                        horizon_sessions=horizon,
                        entry_time=entry_time,
                        exit_time=exit_time,
                        raw_return=raw_return,
                        benchmark_return=benchmark_return,
                        market_excess_return=raw_return - benchmark_return,
                        cross_sectional_rank=Decimal("0"),
                        downside_risk=downside_risk,
                        training_eligible=True,
                    )
                )
            rows.extend(_rank_and_mask(cohort, matrix.extreme_tail_fraction))

    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.decision_time,
                row.horizon_sessions,
                row.instrument_id,
            ),
        )
    )


def _rank_and_mask(
    cohort: list[CrossSectionalLabelRow],
    tail_fraction: Decimal,
) -> list[CrossSectionalLabelRow]:
    if not cohort:
        return []
    ordered = sorted(
        cohort,
        key=lambda row: (row.market_excess_return, row.instrument_id),
    )
    ranked: list[CrossSectionalLabelRow] = []
    denominator = Decimal(len(ordered) - 1)
    index = 0
    while index < len(ordered):
        end = index
        value = ordered[index].market_excess_return
        while end + 1 < len(ordered) and ordered[end + 1].market_excess_return == value:
            end += 1
        rank = (
            Decimal("0.5")
            if denominator == 0
            else (Decimal(index) + Decimal(end)) / 2 / denominator
        )
        ranked.extend(
            replace(ordered[position], cross_sectional_rank=rank)
            for position in range(index, end + 1)
        )
        index = end + 1

    tail_count = int(Decimal(len(ranked)) * tail_fraction)
    if tail_count:
        excluded = {
            row.instrument_id
            for row in ranked[:tail_count] + ranked[len(ranked) - tail_count :]
        }
        ranked = [
            replace(row, training_eligible=False)
            if row.instrument_id in excluded
            else row
            for row in ranked
        ]
    return ranked

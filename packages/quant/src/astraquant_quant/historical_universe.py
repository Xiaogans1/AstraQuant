"""Leakage-safe historical liquidity universes for Stage B v2."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal
from statistics import median
from types import MappingProxyType

from astraquant_data.market_bars import MarketBar
from astraquant_domain import HistoricalUniversePolicy
from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

_SNAPSHOT_SCHEMA = "astraquant.historical-universe/v1"


class InsufficientHistoricalUniverseError(ValueError):
    """A formal decision session has fewer eligible names than policy allows."""


@dataclass(frozen=True, slots=True)
class DailyInstrumentStatus:
    tradable: bool
    special_treatment: bool
    evidence_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.tradable, bool) or not isinstance(
            self.special_treatment, bool
        ):
            raise ValueError("daily instrument status flags must be boolean")
        object.__setattr__(
            self,
            "evidence_digest",
            validate_digest("status evidence_digest", self.evidence_digest),
        )


@dataclass(frozen=True, slots=True)
class DailyUniverseInstrument:
    instrument_id: str
    source_snapshot_id: str
    lifecycle_evidence_digest: str
    listed_on: date
    delisted_on: date | None
    common_a_share: bool
    bars: Mapping[datetime, MarketBar]

    def __post_init__(self) -> None:
        instrument_id = self.instrument_id.strip()
        if not instrument_id:
            raise ValueError("instrument_id must not be empty")
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(
            self,
            "source_snapshot_id",
            validate_digest("source_snapshot_id", self.source_snapshot_id),
        )
        object.__setattr__(
            self,
            "lifecycle_evidence_digest",
            validate_digest(
                "lifecycle_evidence_digest",
                self.lifecycle_evidence_digest,
            ),
        )
        if self.delisted_on is not None and self.delisted_on < self.listed_on:
            raise ValueError("delisted_on must not precede listed_on")
        if not isinstance(self.common_a_share, bool):
            raise ValueError("common_a_share must be boolean")
        frozen_bars: dict[datetime, MarketBar] = {}
        for timestamp, bar in sorted(self.bars.items()):
            if timestamp != bar.timestamp:
                raise ValueError("universe bar key must equal bar timestamp")
            if timestamp.date() < self.listed_on or (
                self.delisted_on is not None and timestamp.date() > self.delisted_on
            ):
                raise ValueError("universe bar falls outside instrument lifecycle")
            frozen_bars[timestamp] = bar
        if not frozen_bars:
            raise ValueError("universe instrument bars must not be empty")
        object.__setattr__(self, "bars", MappingProxyType(frozen_bars))

    def active_on(self, session: datetime) -> bool:
        return self.listed_on <= session.date() and (
            self.delisted_on is None or session.date() <= self.delisted_on
        )


@dataclass(frozen=True, slots=True)
class HistoricalUniverseSnapshot:
    schema_version: str
    members_by_time: Mapping[datetime, frozenset[str]]
    policy_digest: str
    sources_digest: str
    status_digest: str
    snapshot_digest: str


def build_historical_universe(
    *,
    sessions: Sequence[datetime],
    instruments: Sequence[DailyUniverseInstrument],
    status_by_session: Mapping[datetime, Mapping[str, DailyInstrumentStatus]],
    policy: HistoricalUniversePolicy,
) -> HistoricalUniverseSnapshot:
    """Select each session using only lifecycle, status and bars visible by that session."""

    timeline = tuple(sessions)
    _validate_sessions(timeline)
    exact_instruments = tuple(sorted(instruments, key=lambda item: item.instrument_id))
    by_instrument = {item.instrument_id: item for item in exact_instruments}
    if not exact_instruments or len(by_instrument) != len(exact_instruments):
        raise ValueError("universe instruments must be non-empty and unique")
    timeline_set = set(timeline)
    if any(set(instrument.bars) - timeline_set for instrument in exact_instruments):
        raise ValueError("instrument bars must belong to the declared sessions")

    decision_sessions = timeline[policy.minimum_history_sessions - 1 :]
    if not decision_sessions:
        raise ValueError("sessions do not cover minimum history")
    statuses = _validate_statuses(
        decision_sessions=decision_sessions,
        by_instrument=by_instrument,
        status_by_session=status_by_session,
    )

    minimum_window_observations = int(
        (
            Decimal(policy.liquidity_lookback_sessions)
            * policy.minimum_observation_ratio
        ).to_integral_value(rounding=ROUND_CEILING)
    )
    members_by_time: dict[datetime, frozenset[str]] = {}
    for session_index, session in enumerate(timeline):
        if session not in statuses:
            continue
        candidates: list[tuple[Decimal, str]] = []
        history_sessions = timeline[: session_index + 1]
        window_sessions = timeline[
            session_index + 1 - policy.liquidity_lookback_sessions : session_index + 1
        ]
        for instrument in exact_instruments:
            status = statuses[session][instrument.instrument_id]
            if not instrument.active_on(session):
                continue
            if policy.common_a_share_only and not instrument.common_a_share:
                continue
            if not status.tradable or (
                policy.exclude_special_treatment and status.special_treatment
            ):
                continue
            current = instrument.bars.get(session)
            if current is None or current.volume <= 0 or current.close < policy.minimum_price:
                continue
            history_count = sum(
                history_session in instrument.bars for history_session in history_sessions
            )
            if history_count < policy.minimum_history_sessions:
                continue
            window_bars = [
                instrument.bars[window_session]
                for window_session in window_sessions
                if window_session in instrument.bars
            ]
            if len(window_bars) < minimum_window_observations:
                continue
            median_turnover = median(bar.turnover for bar in window_bars)
            if median_turnover <= 0:
                continue
            candidates.append((median_turnover, instrument.instrument_id))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        if len(candidates) < policy.minimum_size:
            raise InsufficientHistoricalUniverseError(
                f"historical universe at {session.isoformat()} has {len(candidates)} "
                f"eligible instruments; minimum {policy.minimum_size}"
            )
        selected = candidates[: min(policy.target_size, policy.maximum_size)]
        members_by_time[session] = frozenset(instrument_id for _, instrument_id in selected)

    sources_value = [
        {
            "common_a_share": instrument.common_a_share,
            "delisted_on": (
                None if instrument.delisted_on is None else instrument.delisted_on.isoformat()
            ),
            "instrument_id": instrument.instrument_id,
            "lifecycle_evidence_digest": instrument.lifecycle_evidence_digest,
            "listed_on": instrument.listed_on.isoformat(),
            "source_snapshot_id": instrument.source_snapshot_id,
        }
        for instrument in exact_instruments
    ]
    status_value = [
        {
            "decision_time": session.isoformat(),
            "instruments": [
                {
                    "evidence_digest": statuses[session][instrument_id].evidence_digest,
                    "instrument_id": instrument_id,
                    "special_treatment": statuses[session][
                        instrument_id
                    ].special_treatment,
                    "tradable": statuses[session][instrument_id].tradable,
                }
                for instrument_id in sorted(statuses[session])
            ],
        }
        for session in sorted(statuses)
    ]
    sources_digest = _digest(sources_value)
    status_digest = _digest(status_value)
    snapshot_digest = _digest(
        {
            "members": [
                {
                    "decision_time": session.isoformat(),
                    "instruments": sorted(members_by_time[session]),
                }
                for session in sorted(members_by_time)
            ],
            "policy_digest": policy.policy_digest,
            "schema_version": _SNAPSHOT_SCHEMA,
            "sources_digest": sources_digest,
            "status_digest": status_digest,
        }
    )
    return HistoricalUniverseSnapshot(
        schema_version=_SNAPSHOT_SCHEMA,
        members_by_time=MappingProxyType(members_by_time),
        policy_digest=policy.policy_digest,
        sources_digest=sources_digest,
        status_digest=status_digest,
        snapshot_digest=snapshot_digest,
    )


def _validate_sessions(sessions: tuple[datetime, ...]) -> None:
    if not sessions:
        raise ValueError("sessions must not be empty")
    if any(
        session.tzinfo is None or session.utcoffset() is None for session in sessions
    ):
        raise ValueError("sessions must be timezone-aware")
    if sessions != tuple(sorted(set(sessions))):
        raise ValueError("sessions must be unique and chronological")


def _validate_statuses(
    *,
    decision_sessions: tuple[datetime, ...],
    by_instrument: Mapping[str, DailyUniverseInstrument],
    status_by_session: Mapping[datetime, Mapping[str, DailyInstrumentStatus]],
) -> dict[datetime, dict[str, DailyInstrumentStatus]]:
    if set(status_by_session) != set(decision_sessions):
        raise ValueError("status coverage must match every decision session exactly")
    known = set(by_instrument)
    statuses: dict[datetime, dict[str, DailyInstrumentStatus]] = {}
    for session in decision_sessions:
        current = dict(status_by_session[session])
        unknown = set(current) - known
        if unknown:
            raise ValueError("status contains unknown instruments")
        required = {
            instrument_id
            for instrument_id, instrument in by_instrument.items()
            if instrument.active_on(session)
        }
        if not required.issubset(current):
            raise ValueError("status coverage is missing active instruments")
        statuses[session] = {key: current[key] for key in sorted(current)}
    return statuses


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

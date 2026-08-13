from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_data.market_bars import MarketBar
from astraquant_domain import HistoricalUniversePolicy
from astraquant_quant.historical_universe import (
    DailyInstrumentStatus,
    DailyUniverseInstrument,
    InsufficientHistoricalUniverseError,
    build_historical_universe,
)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _policy(*, minimum_size: int = 1) -> HistoricalUniversePolicy:
    return HistoricalUniversePolicy(
        schema_version="astraquant.historical-universe-policy/v1",
        liquidity_lookback_sessions=2,
        minimum_history_sessions=3,
        target_size=2,
        minimum_size=minimum_size,
        maximum_size=3,
        minimum_price=Decimal("2"),
        minimum_observation_ratio=Decimal("1"),
        exclude_special_treatment=True,
        common_a_share_only=True,
    )


def _sessions() -> tuple[datetime, ...]:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    return tuple(start + timedelta(days=index) for index in range(6))


def _bar(timestamp: datetime, *, turnover: int, close: str = "10") -> MarketBar:
    price = Decimal(close)
    return MarketBar(
        timestamp=timestamp,
        open=price,
        high=price * Decimal("1.01"),
        low=price * Decimal("0.99"),
        close=price,
        volume=Decimal("100000"),
        turnover=Decimal(turnover),
    )


def _instrument(
    instrument_id: str,
    *,
    turnover: int,
    listed_index: int = 0,
    common: bool = True,
    source_character: str,
) -> DailyUniverseInstrument:
    sessions = _sessions()
    return DailyUniverseInstrument(
        instrument_id=instrument_id,
        source_snapshot_id=_digest(source_character),
        lifecycle_evidence_digest=_digest(source_character.upper()),
        listed_on=sessions[listed_index].date(),
        delisted_on=None,
        common_a_share=common,
        bars={
            session: _bar(session, turnover=turnover + index)
            for index, session in enumerate(sessions)
            if index >= listed_index
        },
    )


def _instruments() -> tuple[DailyUniverseInstrument, ...]:
    return (
        _instrument("A.SSE", turnover=100, source_character="1"),
        _instrument("B.SSE", turnover=200, source_character="2"),
        _instrument("C.SSE", turnover=500, listed_index=2, source_character="3"),
        _instrument("D.SSE", turnover=1000, common=False, source_character="4"),
    )


def _statuses(
    instruments: tuple[DailyUniverseInstrument, ...] | None = None,
) -> dict[datetime, dict[str, DailyInstrumentStatus]]:
    sources = _instruments() if instruments is None else instruments
    sessions = _sessions()
    values: dict[datetime, dict[str, DailyInstrumentStatus]] = {}
    evidence_by_instrument = {
        "A.SSE": _digest("5"),
        "B.SSE": _digest("6"),
        "C.SSE": _digest("7"),
        "D.SSE": _digest("8"),
    }
    for session_index, session in enumerate(sessions[2:], start=2):
        current: dict[str, DailyInstrumentStatus] = {}
        for instrument in sources:
            if instrument.listed_on > session.date():
                continue
            current[instrument.instrument_id] = DailyInstrumentStatus(
                tradable=not (instrument.instrument_id == "B.SSE" and session_index == 3),
                special_treatment=(
                    instrument.instrument_id == "B.SSE" and session_index == 4
                ),
                evidence_digest=evidence_by_instrument[instrument.instrument_id],
            )
        values[session] = current
    return values


def test_historical_universe_respects_history_status_and_asset_kind() -> None:
    snapshot = build_historical_universe(
        sessions=_sessions(),
        instruments=_instruments(),
        status_by_session=_statuses(),
        policy=_policy(),
    )

    assert snapshot.members_by_time[_sessions()[2]] == frozenset({"A.SSE", "B.SSE"})
    assert snapshot.members_by_time[_sessions()[3]] == frozenset({"A.SSE"})
    assert snapshot.members_by_time[_sessions()[4]] == frozenset({"A.SSE", "C.SSE"})
    assert all("D.SSE" not in members for members in snapshot.members_by_time.values())
    assert snapshot.policy_digest == _policy().policy_digest
    assert snapshot.snapshot_digest.startswith("sha256:")


def test_a_share_lifecycle_uses_shanghai_trading_date_not_utc_storage_date() -> None:
    utc_storage_time = datetime(2026, 8, 3, 16, tzinfo=UTC)

    instrument = DailyUniverseInstrument(
        instrument_id="600000.SSE",
        source_snapshot_id=_digest("a"),
        lifecycle_evidence_digest=_digest("b"),
        listed_on=date(2026, 8, 4),
        delisted_on=None,
        common_a_share=True,
        bars={utc_storage_time: _bar(utc_storage_time, turnover=100)},
    )

    assert instrument.active_on(utc_storage_time) is True


def test_future_turnover_cannot_change_past_membership() -> None:
    instruments = _instruments()
    before = build_historical_universe(
        sessions=_sessions(),
        instruments=instruments,
        status_by_session=_statuses(instruments),
        policy=_policy(),
    )
    changed = list(instruments)
    a = changed[0]
    bars = dict(a.bars)
    bars[_sessions()[5]] = _bar(_sessions()[5], turnover=999999999)
    changed[0] = replace(a, source_snapshot_id=_digest("9"), bars=bars)

    after = build_historical_universe(
        sessions=_sessions(),
        instruments=tuple(changed),
        status_by_session=_statuses(tuple(changed)),
        policy=_policy(),
    )

    assert before.members_by_time[_sessions()[2]] == after.members_by_time[_sessions()[2]]
    assert before.snapshot_digest != after.snapshot_digest


def test_input_permutation_is_digest_stable() -> None:
    instruments = _instruments()
    first = build_historical_universe(
        sessions=_sessions(),
        instruments=instruments,
        status_by_session=_statuses(instruments),
        policy=_policy(),
    )
    second = build_historical_universe(
        sessions=_sessions(),
        instruments=tuple(reversed(instruments)),
        status_by_session=_statuses(tuple(reversed(instruments))),
        policy=_policy(),
    )

    assert first.snapshot_digest == second.snapshot_digest
    assert first.members_by_time == second.members_by_time


def test_price_floor_and_delisting_remove_instrument_at_exact_session() -> None:
    instruments = list(_instruments())
    a = instruments[0]
    a_bars = dict(a.bars)
    a_bars[_sessions()[5]] = _bar(_sessions()[5], turnover=999, close="1")
    instruments[0] = replace(a, source_snapshot_id=_digest("8"), bars=a_bars)
    b = instruments[1]
    bars = dict(b.bars)
    del bars[_sessions()[5]]
    instruments[1] = replace(
        b,
        source_snapshot_id=_digest("9"),
        delisted_on=date(2026, 1, 9),
        bars=bars,
    )

    snapshot = build_historical_universe(
        sessions=_sessions(),
        instruments=tuple(instruments),
        status_by_session=_statuses(tuple(instruments)),
        policy=_policy(),
    )

    assert "A.SSE" not in snapshot.members_by_time[_sessions()[5]]
    assert "B.SSE" not in snapshot.members_by_time[_sessions()[5]]


def test_formal_universe_fails_when_daily_candidate_count_is_below_minimum() -> None:
    with pytest.raises(InsufficientHistoricalUniverseError, match="minimum 2"):
        build_historical_universe(
            sessions=_sessions(),
            instruments=_instruments(),
            status_by_session=_statuses(),
            policy=_policy(minimum_size=2),
        )


def test_missing_or_unknown_status_evidence_fails_closed() -> None:
    statuses = _statuses()
    del statuses[_sessions()[2]]["A.SSE"]
    with pytest.raises(ValueError, match="status coverage"):
        build_historical_universe(
            sessions=_sessions(),
            instruments=_instruments(),
            status_by_session=statuses,
            policy=_policy(),
        )

    statuses = _statuses()
    statuses[_sessions()[2]]["UNKNOWN.SSE"] = DailyInstrumentStatus(
        tradable=True,
        special_treatment=False,
        evidence_digest=_digest("a"),
    )
    with pytest.raises(ValueError, match="unknown"):
        build_historical_universe(
            sessions=_sessions(),
            instruments=_instruments(),
            status_by_session=statuses,
            policy=_policy(),
        )


def test_noncanonical_sessions_and_unsealed_source_fail_closed() -> None:
    with pytest.raises(ValueError, match="sessions"):
        build_historical_universe(
            sessions=tuple(reversed(_sessions())),
            instruments=_instruments(),
            status_by_session=_statuses(),
            policy=_policy(),
        )
    with pytest.raises(ValueError, match="source_snapshot_id"):
        replace(_instruments()[0], source_snapshot_id="latest")

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_data.canonical import (
    CanonicalBarInput,
    CaptureRowLineage,
    normalize_bar,
)
from astraquant_data.temporal import (
    LiveOnline,
    MirrorOnline,
    PaperOnline,
    PitFidelity,
    ReplayAsDelivered,
    ReplayPitStrict,
    RevisionPolicy,
    VintageMode,
    VisibilityPolicy,
    VisibilityRejected,
    assess_visibility,
    build_visibility_report,
    is_visible,
    select_visible_vintage,
    visible_at,
)
from astraquant_domain import (
    Adjustment,
    AvailabilityBasis,
    BarFrequency,
    InstrumentId,
    ObservationInterval,
    VintageKind,
)

NOMINAL = datetime(2010, 1, 4, 7, 1, tzinfo=UTC)
FIRST_RECEIVED = datetime(2026, 8, 11, 1, 2, tzinfo=UTC)
EPSILON = timedelta(microseconds=1)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _bar(**changes: object):  # type: ignore[no-untyped-def]
    supersedes_vintage_id = changes.pop("supersedes_vintage_id", None)
    values: dict[str, object] = {
        "instrument_id": InstrumentId.parse("600000.SSE"),
        "frequency": BarFrequency.DAY,
        "trading_date": date(2010, 1, 4),
        "source_available_time": NOMINAL,
        "observed_received_time": FIRST_RECEIVED,
        "recorded_time": FIRST_RECEIVED + timedelta(seconds=1),
        "first_received_time": FIRST_RECEIVED,
        "source_revision_time": None,
        "source_revision_id": None,
        "vintage_proven_time": FIRST_RECEIVED,
        "vintage_kind": VintageKind.AS_DELIVERED_UNVERSIONED,
        "availability_basis": AvailabilityBasis.SESSION_CLOSE,
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9"),
        "close": Decimal("10.5"),
        "volume": Decimal("1000"),
        "turnover": Decimal("10500"),
        "open_interest": None,
        "settlement": None,
        "adjustment": Adjustment.NONE,
        "source_adjustment": Adjustment.NONE,
        "units": ("price=CNY", "turnover=CNY", "volume=share"),
    }
    values.update(changes)
    return normalize_bar(
        CanonicalBarInput(**values),  # type: ignore[arg-type]
        interval=ObservationInterval(
            interval_start=datetime(2010, 1, 4, 1, 30, tzinfo=UTC),
            interval_end=datetime(2010, 1, 4, 7, 0, tzinfo=UTC),
            event_time=datetime(2010, 1, 4, 7, 0, tzinfo=UTC),
            calendar_snapshot_id=_digest("1"),
        ),
        lineage=CaptureRowLineage(capture_id=_digest("2"), chunk_id=_digest("3"), row_index=0),
        supersedes_vintage_id=supersedes_vintage_id,  # type: ignore[arg-type]
    )


def test_historical_backfill_has_distinct_nominal_strict_and_online_visibility() -> None:
    old_bar = _bar()

    assert visible_at(old_bar, ReplayAsDelivered()) == NOMINAL
    assert visible_at(old_bar, ReplayPitStrict()) == FIRST_RECEIVED
    assert not is_visible(
        old_bar,
        ReplayPitStrict(),
        decision_time=datetime(2015, 1, 1, tzinfo=UTC),
    )
    assert is_visible(
        old_bar,
        ReplayAsDelivered(),
        decision_time=datetime(2015, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize("policy", [PaperOnline(), MirrorOnline(), LiveOnline()])
def test_online_modes_share_receive_and_revision_visibility_contract(
    policy: VisibilityPolicy,
) -> None:
    revision_time = FIRST_RECEIVED - timedelta(minutes=1)
    revised = _bar(
        observed_received_time=FIRST_RECEIVED,
        recorded_time=FIRST_RECEIVED + timedelta(seconds=1),
        source_revision_time=revision_time,
        source_revision_id="revision-2",
        vintage_proven_time=revision_time,
        vintage_kind=VintageKind.SOURCE_VERSIONED,
        availability_basis=AvailabilityBasis.SOURCE_REVISION,
    )

    assert visible_at(revised, policy) == FIRST_RECEIVED
    assert not is_visible(revised, policy, decision_time=FIRST_RECEIVED - EPSILON)
    assert is_visible(revised, policy, decision_time=FIRST_RECEIVED)


def test_visibility_rejection_is_reasoned_and_rejects_naive_decision_time() -> None:
    bar = _bar()

    decision = assess_visibility(
        bar,
        ReplayPitStrict(),
        decision_time=FIRST_RECEIVED - EPSILON,
    )
    assert not decision.visible
    assert decision.reason == "NOT_YET_VISIBLE"
    with pytest.raises(ValueError, match="timezone-aware"):
        is_visible(bar, ReplayPitStrict(), decision_time=FIRST_RECEIVED.replace(tzinfo=None))


def test_revision_selection_never_rewrites_an_old_decision_or_crosses_cutoff() -> None:
    first = _bar()
    revision_observed = FIRST_RECEIVED + timedelta(days=1)
    revised = _bar(
        close=Decimal("10.6"),
        observed_received_time=revision_observed,
        recorded_time=revision_observed + timedelta(seconds=1),
        source_revision_time=revision_observed - timedelta(minutes=1),
        source_revision_id="revision-2",
        vintage_proven_time=revision_observed - timedelta(minutes=1),
        vintage_kind=VintageKind.SOURCE_VERSIONED,
        availability_basis=AvailabilityBasis.SOURCE_REVISION,
        supersedes_vintage_id=first.vintage_id,
    )

    selected_old = select_visible_vintage(
        (first, revised),
        ReplayPitStrict(),
        decision_time=FIRST_RECEIVED + timedelta(hours=1),
        data_vintage_cutoff=FIRST_RECEIVED + timedelta(hours=1),
        revision_policy=RevisionPolicy.LATEST_VISIBLE,
    )
    selected_new = select_visible_vintage(
        (first, revised),
        ReplayPitStrict(),
        decision_time=revision_observed,
        data_vintage_cutoff=revision_observed + timedelta(seconds=1),
        revision_policy=RevisionPolicy.LATEST_VISIBLE,
    )

    assert selected_old.vintage_id == first.vintage_id
    assert selected_new.vintage_id == revised.vintage_id


def test_exact_vintage_selection_fails_closed_when_id_is_missing() -> None:
    with pytest.raises(VisibilityRejected) as caught:
        select_visible_vintage(
            (_bar(),),
            ReplayPitStrict(),
            decision_time=FIRST_RECEIVED,
            data_vintage_cutoff=FIRST_RECEIVED + timedelta(seconds=1),
            revision_policy=RevisionPolicy.EXACT_VINTAGE,
            exact_vintage_id=_digest("8"),
        )

    assert caught.value.code == "EXACT_VINTAGE_NOT_FOUND"


def test_as_delivered_report_discloses_cutoff_mix_and_nominal_fidelity() -> None:
    unversioned = _bar()
    certified = _bar(
        instrument_id=InstrumentId.parse("000001.SZSE"),
        observed_received_time=NOMINAL,
        recorded_time=NOMINAL + timedelta(seconds=1),
        first_received_time=NOMINAL,
        vintage_proven_time=NOMINAL,
        vintage_kind=VintageKind.SOURCE_CERTIFIED,
        availability_basis=AvailabilityBasis.SOURCE_DECLARED,
    )

    report = build_visibility_report(
        (unversioned, replace(certified, lineage=replace(certified.lineage, row_index=1))),
        ReplayAsDelivered(),
        data_vintage_cutoff=FIRST_RECEIVED + timedelta(seconds=1),
    )

    assert report.vintage_mode is VintageMode.REPLAY_AS_DELIVERED
    assert report.data_vintage_cutoff == FIRST_RECEIVED + timedelta(seconds=1)
    assert report.unversioned_ratio == Decimal("0.5")
    assert report.pit_fidelity is PitFidelity.NOMINAL_ONLY

    strict_report = build_visibility_report(
        (unversioned, certified),
        ReplayPitStrict(),
        data_vintage_cutoff=FIRST_RECEIVED + timedelta(seconds=1),
    )
    assert strict_report.authoritative_count == 1
    assert strict_report.locally_proven_count == 1
    assert strict_report.pit_fidelity is PitFidelity.MIXED

"""Point-in-time and online visibility policies for canonical observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from astraquant_data.canonical import (
    CanonicalBarObservation,
    validate_canonical_observations,
)
from astraquant_domain import VintageKind


class VintageMode(StrEnum):
    REPLAY_AS_DELIVERED = "REPLAY_AS_DELIVERED"
    REPLAY_PIT_STRICT = "REPLAY_PIT_STRICT"
    PAPER = "PAPER"
    MIRROR = "MIRROR"
    LIVE = "LIVE"


class RevisionPolicy(StrEnum):
    LATEST_VISIBLE = "LATEST_VISIBLE"
    EXACT_VINTAGE = "EXACT_VINTAGE"


class PitFidelity(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    OBSERVED_ONLY = "OBSERVED_ONLY"
    MIXED = "MIXED"
    NOMINAL_ONLY = "NOMINAL_ONLY"


class VisibilityPolicy(Protocol):
    @property
    def mode(self) -> VintageMode: ...


@dataclass(frozen=True, slots=True)
class ReplayAsDelivered:
    mode: VintageMode = VintageMode.REPLAY_AS_DELIVERED


@dataclass(frozen=True, slots=True)
class ReplayPitStrict:
    mode: VintageMode = VintageMode.REPLAY_PIT_STRICT


@dataclass(frozen=True, slots=True)
class PaperOnline:
    mode: VintageMode = VintageMode.PAPER


@dataclass(frozen=True, slots=True)
class MirrorOnline:
    mode: VintageMode = VintageMode.MIRROR


@dataclass(frozen=True, slots=True)
class LiveOnline:
    mode: VintageMode = VintageMode.LIVE


@dataclass(frozen=True, slots=True)
class VisibilityDecision:
    visible: bool
    visible_time: datetime
    decision_time: datetime
    reason: str
    vintage_mode: VintageMode


@dataclass(frozen=True, slots=True)
class VisibilityReport:
    vintage_mode: VintageMode
    data_vintage_cutoff: datetime
    total_count: int
    authoritative_count: int
    locally_proven_count: int
    unversioned_count: int
    unversioned_ratio: Decimal
    pit_fidelity: PitFidelity


class VisibilityRejected(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"visibility rejected: {code}")


def _aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def visible_at(observation: CanonicalBarObservation, policy: VisibilityPolicy) -> datetime:
    source_available = _aware("source_available_time", observation.source_available_time)
    if policy.mode is VintageMode.REPLAY_AS_DELIVERED:
        return source_available
    if policy.mode is VintageMode.REPLAY_PIT_STRICT:
        return max(
            source_available,
            _aware("vintage_proven_time", observation.vintage_proven_time),
        )
    if policy.mode in {VintageMode.PAPER, VintageMode.MIRROR, VintageMode.LIVE}:
        candidates = [
            source_available,
            _aware("observed_received_time", observation.observed_received_time),
        ]
        if observation.source_revision_time is not None:
            candidates.append(_aware("source_revision_time", observation.source_revision_time))
        return max(candidates)
    raise ValueError(f"unsupported vintage mode: {policy.mode}")


def assess_visibility(
    observation: CanonicalBarObservation,
    policy: VisibilityPolicy,
    *,
    decision_time: datetime,
    data_vintage_cutoff: datetime | None = None,
) -> VisibilityDecision:
    decision = _aware("decision_time", decision_time)
    cutoff = (
        None if data_vintage_cutoff is None else _aware("data_vintage_cutoff", data_vintage_cutoff)
    )
    derived = visible_at(observation, policy)
    if cutoff is not None and _aware("recorded_time", observation.recorded_time) > cutoff:
        return VisibilityDecision(
            visible=False,
            visible_time=derived,
            decision_time=decision,
            reason="AFTER_DATA_VINTAGE_CUTOFF",
            vintage_mode=policy.mode,
        )
    if derived > decision:
        return VisibilityDecision(
            visible=False,
            visible_time=derived,
            decision_time=decision,
            reason="NOT_YET_VISIBLE",
            vintage_mode=policy.mode,
        )
    return VisibilityDecision(
        visible=True,
        visible_time=derived,
        decision_time=decision,
        reason="VISIBLE",
        vintage_mode=policy.mode,
    )


def is_visible(
    observation: CanonicalBarObservation,
    policy: VisibilityPolicy,
    *,
    decision_time: datetime,
    data_vintage_cutoff: datetime | None = None,
) -> bool:
    return assess_visibility(
        observation,
        policy,
        decision_time=decision_time,
        data_vintage_cutoff=data_vintage_cutoff,
    ).visible


def select_visible_vintage(
    observations: tuple[CanonicalBarObservation, ...] | list[CanonicalBarObservation],
    policy: VisibilityPolicy,
    *,
    decision_time: datetime,
    data_vintage_cutoff: datetime,
    revision_policy: RevisionPolicy,
    exact_vintage_id: str | None = None,
) -> CanonicalBarObservation:
    validated = validate_canonical_observations(observations)
    if not validated:
        raise VisibilityRejected("NO_VINTAGES")
    logical_keys = {
        (
            value.instrument_id,
            value.frequency,
            value.interval_start,
            value.interval_end,
        )
        for value in validated
    }
    if len(logical_keys) != 1:
        raise VisibilityRejected("MIXED_OBSERVATION_KEYS")

    if revision_policy is RevisionPolicy.EXACT_VINTAGE:
        if exact_vintage_id is None:
            raise VisibilityRejected("EXACT_VINTAGE_ID_REQUIRED")
        exact = next(
            (value for value in validated if value.vintage_id == exact_vintage_id),
            None,
        )
        if exact is None:
            raise VisibilityRejected("EXACT_VINTAGE_NOT_FOUND")
        if not is_visible(
            exact,
            policy,
            decision_time=decision_time,
            data_vintage_cutoff=data_vintage_cutoff,
        ):
            raise VisibilityRejected("EXACT_VINTAGE_NOT_VISIBLE")
        return exact

    if revision_policy is not RevisionPolicy.LATEST_VISIBLE:
        raise VisibilityRejected("UNSUPPORTED_REVISION_POLICY")

    eligible = [
        value
        for value in validated
        if is_visible(
            value,
            policy,
            decision_time=decision_time,
            data_vintage_cutoff=data_vintage_cutoff,
        )
    ]
    if not eligible:
        raise VisibilityRejected("NO_VISIBLE_VINTAGE")
    return max(
        eligible,
        key=lambda value: (
            visible_at(value, policy),
            value.recorded_time,
            value.vintage_id,
        ),
    )


def build_visibility_report(
    observations: tuple[CanonicalBarObservation, ...] | list[CanonicalBarObservation],
    policy: VisibilityPolicy,
    *,
    data_vintage_cutoff: datetime,
) -> VisibilityReport:
    cutoff = _aware("data_vintage_cutoff", data_vintage_cutoff)
    validated = validate_canonical_observations(observations)
    included = [
        value for value in validated if _aware("recorded_time", value.recorded_time) <= cutoff
    ]
    authoritative = sum(
        value.vintage_kind in {VintageKind.SOURCE_CERTIFIED, VintageKind.SOURCE_VERSIONED}
        for value in included
    )
    locally_proven = len(included) - authoritative
    unversioned = sum(
        value.vintage_kind is VintageKind.AS_DELIVERED_UNVERSIONED for value in included
    )
    total = len(included)
    ratio = Decimal(0) if total == 0 else Decimal(unversioned) / Decimal(total)
    if policy.mode is VintageMode.REPLAY_AS_DELIVERED:
        fidelity = PitFidelity.NOMINAL_ONLY
    elif authoritative == total and total:
        fidelity = PitFidelity.AUTHORITATIVE
    elif locally_proven == total:
        fidelity = PitFidelity.OBSERVED_ONLY
    else:
        fidelity = PitFidelity.MIXED
    return VisibilityReport(
        vintage_mode=policy.mode,
        data_vintage_cutoff=cutoff,
        total_count=total,
        authoritative_count=authoritative,
        locally_proven_count=locally_proven,
        unversioned_count=unversioned,
        unversioned_ratio=ratio,
        pit_fidelity=fidelity,
    )

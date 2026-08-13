"""Global-time-axis walk-forward splits for Stage B v2 cross-sectional models."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from astraquant_domain.run_manifest import canonical_json_bytes


class DecisionRowLike(Protocol):
    @property
    def decision_time(self) -> datetime: ...

    @property
    def instrument_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class CrossSectionalFold:
    fold_id: str
    timeline_sessions: tuple[datetime, ...]
    fit_sessions: tuple[datetime, ...]
    inner_valid_sessions: tuple[datetime, ...]
    outer_test_sessions: tuple[datetime, ...]
    purge_sessions: int
    fold_digest: str


@dataclass(frozen=True, slots=True)
class CrossSectionalFoldRows:
    fold_id: str
    fit_indices: tuple[int, ...]
    inner_valid_indices: tuple[int, ...]
    outer_test_indices: tuple[int, ...]
    fold_digest: str
    assignment_digest: str


def build_cross_sectional_folds(
    decision_times: Sequence[datetime],
    *,
    horizons: tuple[int, ...],
    minimum_fit_sessions: int = 756,
    inner_valid_sessions: int = 120,
    outer_test_sessions: int = 60,
    fold_count: int = 6,
    purge_sessions: int = 11,
) -> tuple[CrossSectionalFold, ...]:
    """Build expanding folds with independent fit, inner-valid and outer-test regions."""

    timeline = tuple(decision_times)
    _validate_timeline(timeline)
    if (
        not horizons
        or horizons != tuple(sorted(set(horizons)))
        or any(isinstance(value, bool) or value <= 0 for value in horizons)
    ):
        raise ValueError("horizons must be positive, unique and canonical")
    sizes = (
        minimum_fit_sessions,
        inner_valid_sessions,
        outer_test_sessions,
        fold_count,
    )
    if any(isinstance(value, bool) or value <= 0 for value in sizes):
        raise ValueError("fold sizes and count must be positive")
    minimum_purge = max(horizons) + 1
    if isinstance(purge_sessions, bool) or purge_sessions < minimum_purge:
        raise ValueError("purge sessions must cover maximum horizon plus entry lag")

    initial_test_start = len(timeline) - outer_test_sessions * fold_count
    initial_valid_end = initial_test_start - purge_sessions
    initial_valid_start = initial_valid_end - inner_valid_sessions
    initial_fit_end = initial_valid_start - purge_sessions
    if initial_fit_end < minimum_fit_sessions:
        raise ValueError("insufficient sessions for requested cross-sectional folds")

    timeline_digest = _digest([session.isoformat() for session in timeline])
    folds: list[CrossSectionalFold] = []
    for offset in range(fold_count):
        test_start = initial_test_start + offset * outer_test_sessions
        test_end = test_start + outer_test_sessions
        valid_end = test_start - purge_sessions
        valid_start = valid_end - inner_valid_sessions
        fit_end = valid_start - purge_sessions
        fit = timeline[:fit_end]
        valid = timeline[valid_start:valid_end]
        test = timeline[test_start:test_end]
        body = {
            "fit_end": fit[-1].isoformat(),
            "fit_session_count": len(fit),
            "fold_id": f"fold-{offset + 1:02d}",
            "inner_valid_end": valid[-1].isoformat(),
            "inner_valid_start": valid[0].isoformat(),
            "outer_test_end": test[-1].isoformat(),
            "outer_test_start": test[0].isoformat(),
            "purge_sessions": purge_sessions,
            "schema_version": "astraquant.cross-sectional-fold/v1",
            "timeline_digest": timeline_digest,
        }
        folds.append(
            CrossSectionalFold(
                fold_id=f"fold-{offset + 1:02d}",
                timeline_sessions=timeline,
                fit_sessions=fit,
                inner_valid_sessions=valid,
                outer_test_sessions=test,
                purge_sessions=purge_sessions,
                fold_digest=_digest(body),
            )
        )
    return tuple(folds)


def assign_cross_sectional_fold_rows(
    rows: Sequence[DecisionRowLike],
    folds: Sequence[CrossSectionalFold],
) -> tuple[CrossSectionalFoldRows, ...]:
    """Project whole decision-date cohorts into each fold without splitting a date."""

    values = tuple(rows)
    exact_folds = tuple(folds)
    if not values or not exact_folds:
        raise ValueError("rows and folds must not be empty")
    timeline = exact_folds[0].timeline_sessions
    if any(fold.timeline_sessions != timeline for fold in exact_folds):
        raise ValueError("fold timelines must be identical")
    timeline_set = set(timeline)
    identities: set[tuple[datetime, str]] = set()
    for row in values:
        if row.decision_time.tzinfo is None or row.decision_time.utcoffset() is None:
            raise ValueError("row decision_time must be timezone-aware")
        if row.decision_time not in timeline_set:
            raise ValueError("row decision_time is absent from the fold timeline")
        identity = (row.decision_time, row.instrument_id)
        if not row.instrument_id or identity in identities:
            raise ValueError("row identities must be non-empty and unique")
        identities.add(identity)

    assignments: list[CrossSectionalFoldRows] = []
    for fold in exact_folds:
        fit_set = set(fold.fit_sessions)
        valid_set = set(fold.inner_valid_sessions)
        test_set = set(fold.outer_test_sessions)
        fit = tuple(index for index, row in enumerate(values) if row.decision_time in fit_set)
        valid = tuple(index for index, row in enumerate(values) if row.decision_time in valid_set)
        test = tuple(index for index, row in enumerate(values) if row.decision_time in test_set)
        if not fit or not valid or not test:
            raise ValueError(f"fold row coverage is incomplete: {fold.fold_id}")
        canonical_identities = {
            "fit": sorted(
                (values[index].decision_time.isoformat(), values[index].instrument_id)
                for index in fit
            ),
            "inner_valid": sorted(
                (values[index].decision_time.isoformat(), values[index].instrument_id)
                for index in valid
            ),
            "outer_test": sorted(
                (values[index].decision_time.isoformat(), values[index].instrument_id)
                for index in test
            ),
        }
        assignments.append(
            CrossSectionalFoldRows(
                fold_id=fold.fold_id,
                fit_indices=fit,
                inner_valid_indices=valid,
                outer_test_indices=test,
                fold_digest=fold.fold_digest,
                assignment_digest=_digest(
                    {
                        "fold_digest": fold.fold_digest,
                        "identities": canonical_identities,
                        "schema_version": "astraquant.cross-sectional-fold-rows/v1",
                    }
                ),
            )
        )
    return tuple(assignments)


def _validate_timeline(timeline: tuple[datetime, ...]) -> None:
    if not timeline:
        raise ValueError("decision timeline must not be empty")
    if any(
        session.tzinfo is None or session.utcoffset() is None for session in timeline
    ):
        raise ValueError("decision timeline sessions must be timezone-aware")
    if timeline != tuple(sorted(set(timeline))):
        raise ValueError("decision timeline must be unique and chronological")


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

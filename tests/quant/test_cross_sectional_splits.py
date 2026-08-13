from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from astraquant_quant.cross_sectional_splits import (
    assign_cross_sectional_fold_rows,
    build_cross_sectional_folds,
)


@dataclass(frozen=True, slots=True)
class _Row:
    decision_time: datetime
    instrument_id: str


def _sessions(count: int = 65) -> tuple[datetime, ...]:
    start = datetime(2020, 1, 2, 7, tzinfo=UTC)
    return tuple(start + timedelta(days=index) for index in range(count))


def test_six_fold_policy_has_fit_valid_purge_and_outer_test_boundaries() -> None:
    folds = build_cross_sectional_folds(
        _sessions(),
        horizons=(1, 5, 10),
        minimum_fit_sessions=20,
        inner_valid_sessions=5,
        outer_test_sessions=5,
        fold_count=3,
        purge_sessions=11,
    )

    assert len(folds) == 3
    first = folds[0]
    assert len(first.fit_sessions) >= 20
    assert len(first.inner_valid_sessions) == 5
    assert len(first.outer_test_sessions) == 5
    assert first.fit_sessions[-1] < first.inner_valid_sessions[0]
    assert first.inner_valid_sessions[-1] < first.outer_test_sessions[0]
    assert (
        _sessions().index(first.inner_valid_sessions[0])
        - _sessions().index(first.fit_sessions[-1])
        - 1
        == 11
    )
    assert (
        _sessions().index(first.outer_test_sessions[0])
        - _sessions().index(first.inner_valid_sessions[-1])
        - 1
        == 11
    )
    assert folds[0].outer_test_sessions[-1] < folds[1].outer_test_sessions[0]
    assert folds[0].fold_digest != folds[1].fold_digest


def test_row_assignment_keeps_every_instrument_of_one_date_in_one_segment() -> None:
    sessions = _sessions()
    rows = tuple(
        _Row(session, instrument)
        for session in sessions
        for instrument in ("A.SSE", "B.SSE", "C.SSE")
    )
    folds = build_cross_sectional_folds(
        sessions,
        horizons=(1, 5, 10),
        minimum_fit_sessions=20,
        inner_valid_sessions=5,
        outer_test_sessions=5,
        fold_count=3,
        purge_sessions=11,
    )

    assignments = assign_cross_sectional_fold_rows(rows, folds)

    for assignment in assignments:
        for indices in (
            assignment.fit_indices,
            assignment.inner_valid_indices,
            assignment.outer_test_indices,
        ):
            times = {rows[index].decision_time for index in indices}
            for decision_time in times:
                assert sum(rows[index].decision_time == decision_time for index in indices) == 3
        assert not (
            set(assignment.fit_indices)
            & set(assignment.inner_valid_indices)
            or set(assignment.fit_indices) & set(assignment.outer_test_indices)
            or set(assignment.inner_valid_indices) & set(assignment.outer_test_indices)
        )


def test_fold_identity_is_stable_under_row_permutation() -> None:
    sessions = _sessions()
    rows = tuple(
        _Row(session, instrument)
        for session in sessions
        for instrument in ("B.SSE", "A.SSE")
    )
    folds = build_cross_sectional_folds(
        sessions,
        horizons=(1, 5, 10),
        minimum_fit_sessions=20,
        inner_valid_sessions=5,
        outer_test_sessions=5,
        fold_count=3,
        purge_sessions=11,
    )

    first = assign_cross_sectional_fold_rows(rows, folds)
    second = assign_cross_sectional_fold_rows(tuple(reversed(rows)), folds)

    assert [item.assignment_digest for item in first] == [
        item.assignment_digest for item in second
    ]


def test_formal_defaults_are_three_year_six_fold_contract() -> None:
    sessions = _sessions(756 + 120 + 60 * 6 + 22)

    folds = build_cross_sectional_folds(sessions, horizons=(1, 5, 10))

    assert len(folds) == 6
    assert len(folds[0].fit_sessions) >= 756
    assert all(len(fold.inner_valid_sessions) == 120 for fold in folds)
    assert all(len(fold.outer_test_sessions) == 60 for fold in folds)
    assert all(fold.purge_sessions == 11 for fold in folds)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"purge_sessions": 10}, "horizon"),
        ({"minimum_fit_sessions": 50}, "insufficient"),
        ({"fold_count": 0}, "positive"),
    ],
)
def test_fold_builder_rejects_leaky_or_impossible_policy(
    changes: dict[str, int],
    match: str,
) -> None:
    values = {
        "minimum_fit_sessions": 20,
        "inner_valid_sessions": 5,
        "outer_test_sessions": 5,
        "fold_count": 3,
        "purge_sessions": 11,
    }
    values.update(changes)
    with pytest.raises(ValueError, match=match):
        build_cross_sectional_folds(
            _sessions(),
            horizons=(1, 5, 10),
            **values,
        )


def test_assignment_rejects_unknown_or_naive_decision_time() -> None:
    sessions = _sessions()
    folds = build_cross_sectional_folds(
        sessions,
        horizons=(1, 5, 10),
        minimum_fit_sessions=20,
        inner_valid_sessions=5,
        outer_test_sessions=5,
        fold_count=3,
        purge_sessions=11,
    )
    with pytest.raises(ValueError, match="timeline"):
        assign_cross_sectional_fold_rows(
            (_Row(sessions[-1] + timedelta(days=1), "A.SSE"),),
            folds,
        )
    with pytest.raises(ValueError, match="timezone"):
        assign_cross_sectional_fold_rows(
            (_Row(datetime(2020, 1, 1), "A.SSE"),),
            folds,
        )

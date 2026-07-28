from datetime import UTC, date, datetime, timedelta

from astraquant_data.quality import (
    QualityCode,
    QualitySeverity,
    evaluate_bars,
)

from .factories import make_bar

FETCHED_AT = datetime(2026, 7, 30, tzinfo=UTC)


def test_duplicate_and_unexpected_date_issues_are_stable_and_machine_readable() -> None:
    first = make_bar(day=24, availability_estimated=False)
    report = evaluate_bars(
        [
            first,
            first,
            make_bar(day=28, availability_estimated=False),
        ],
        expected_trading_dates={date(2026, 7, 24)},
        source_fetched_at=FETCHED_AT,
    )

    assert [(issue.code, issue.severity) for issue in report.issues] == [
        (QualityCode.DUPLICATE_KEY, QualitySeverity.ERROR),
        (QualityCode.UNEXPECTED_TRADING_DATE, QualitySeverity.WARNING),
    ]
    assert report.publishable is False


def test_a_later_revision_of_the_same_event_is_not_an_exact_duplicate() -> None:
    first = make_bar(day=24, availability_estimated=False)
    revised = make_bar(
        day=24,
        close="10.80",
        available_time=first.available_time + timedelta(hours=1),
        availability_estimated=False,
    )

    report = evaluate_bars(
        [first, revised],
        expected_trading_dates={date(2026, 7, 24)},
        source_fetched_at=FETCHED_AT,
    )

    assert QualityCode.DUPLICATE_KEY not in {issue.code for issue in report.issues}
    assert report.publishable


def test_information_available_after_fetch_time_is_rejected() -> None:
    bar = make_bar(available_time=FETCHED_AT + timedelta(seconds=1))

    report = evaluate_bars(
        [bar],
        expected_trading_dates={date(2026, 7, 24)},
        source_fetched_at=FETCHED_AT,
    )

    assert QualityCode.AVAILABLE_AFTER_SOURCE_FETCH in {
        issue.code for issue in report.issues
    }
    assert report.publishable is False


def test_estimated_availability_is_visible_but_publishable() -> None:
    report = evaluate_bars(
        [make_bar()],
        expected_trading_dates={date(2026, 7, 24)},
        source_fetched_at=FETCHED_AT,
    )

    assert report.issues[0].code is QualityCode.ESTIMATED_AVAILABILITY
    assert report.publishable

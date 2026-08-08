"""Deterministic, machine-readable market-data quality reports."""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from astraquant_domain import Bar


class QualitySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class QualityCode(StrEnum):
    EMPTY_DATASET = "EMPTY_DATASET"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    NON_MONOTONIC_TIME = "NON_MONOTONIC_TIME"
    AVAILABLE_AFTER_SOURCE_FETCH = "AVAILABLE_AFTER_SOURCE_FETCH"
    UNEXPECTED_TRADING_DATE = "UNEXPECTED_TRADING_DATE"
    ESTIMATED_AVAILABILITY = "ESTIMATED_AVAILABILITY"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: QualityCode
    severity: QualitySeverity
    count: int
    sample_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityReport:
    row_count: int
    issues: tuple[QualityIssue, ...]

    @property
    def publishable(self) -> bool:
        return all(issue.severity is not QualitySeverity.ERROR for issue in self.issues)


def evaluate_bars(
    bars: Iterable[Bar],
    *,
    expected_trading_dates: set[date],
    source_fetched_at: datetime,
) -> QualityReport:
    if source_fetched_at.tzinfo is None or source_fetched_at.utcoffset() is None:
        raise ValueError("source_fetched_at must be timezone-aware")
    rows = tuple(bars)
    findings: dict[QualityCode, list[str]] = defaultdict(list)
    if not rows:
        findings[QualityCode.EMPTY_DATASET].append("dataset")

    exact_keys = [
        (
            str(bar.instrument_id),
            bar.frequency.value,
            bar.event_time.isoformat(),
            bar.available_time.isoformat(),
        )
        for bar in rows
    ]
    for key, count in Counter(exact_keys).items():
        if count > 1:
            findings[QualityCode.DUPLICATE_KEY].extend(["|".join(key)] * (count - 1))

    groups: dict[tuple[str, str], list[Bar]] = defaultdict(list)
    for bar in rows:
        groups[(str(bar.instrument_id), bar.frequency.value)].append(bar)
    for group in groups.values():
        previous_available: datetime | None = None
        previous_event: datetime | None = None
        for bar in sorted(group, key=lambda item: (item.event_time, item.available_time)):
            if (
                previous_event is not None
                and bar.event_time > previous_event
                and previous_available is not None
                and bar.available_time < previous_available
            ):
                findings[QualityCode.NON_MONOTONIC_TIME].append(_bar_key(bar))
            previous_event = bar.event_time
            previous_available = bar.available_time

    for bar in rows:
        if bar.available_time > source_fetched_at:
            findings[QualityCode.AVAILABLE_AFTER_SOURCE_FETCH].append(_bar_key(bar))
        if bar.trading_date not in expected_trading_dates:
            findings[QualityCode.UNEXPECTED_TRADING_DATE].append(_bar_key(bar))
        if bar.availability_estimated:
            findings[QualityCode.ESTIMATED_AVAILABILITY].append(_bar_key(bar))

    severity = {
        QualityCode.EMPTY_DATASET: QualitySeverity.ERROR,
        QualityCode.DUPLICATE_KEY: QualitySeverity.ERROR,
        QualityCode.NON_MONOTONIC_TIME: QualitySeverity.ERROR,
        QualityCode.AVAILABLE_AFTER_SOURCE_FETCH: QualitySeverity.ERROR,
        QualityCode.UNEXPECTED_TRADING_DATE: QualitySeverity.WARNING,
        QualityCode.ESTIMATED_AVAILABILITY: QualitySeverity.WARNING,
    }
    issues = tuple(
        QualityIssue(
            code=code,
            severity=severity[code],
            count=len(findings[code]),
            sample_keys=tuple(findings[code][:5]),
        )
        for code in QualityCode
        if findings[code]
    )
    return QualityReport(row_count=len(rows), issues=issues)


def _bar_key(bar: Bar) -> str:
    return "|".join(
        (
            str(bar.instrument_id),
            bar.frequency.value,
            bar.event_time.isoformat(),
            bar.available_time.isoformat(),
        )
    )

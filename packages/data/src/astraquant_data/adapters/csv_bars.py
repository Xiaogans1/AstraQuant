"""Strict offline CSV provider for deterministic development fixtures."""

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from astraquant_data.providers import HistoryRequest
from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId

_REQUIRED_COLUMNS = frozenset(
    {
        "instrument_id",
        "trading_date",
        "event_time",
        "available_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "open_interest",
        "settlement",
        "adjustment",
        "availability_estimated",
    }
)


class CsvDailyBarProvider:
    def __init__(self, path: Path, *, source_version: str) -> None:
        if not source_version.strip():
            raise ValueError("source_version must not be empty")
        self._path = path
        self.source_version = source_version

    def provider_id(self) -> str:
        return "fixture-csv"

    def fetch_bars(self, request: HistoryRequest) -> tuple[Bar, ...]:
        if request.frequency is not BarFrequency.DAY:
            raise ValueError("CSV daily provider only supports 1d bars")
        with self._path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            actual_columns = set(reader.fieldnames or ())
            missing = _REQUIRED_COLUMNS - actual_columns
            if missing:
                raise ValueError(
                    f"CSV bar schema missing columns: {', '.join(sorted(missing))}"
                )
            bars = tuple(_row_to_bar(row) for row in reader)
        return tuple(
            bar
            for bar in bars
            if bar.instrument_id == request.instrument_id
            and request.start <= bar.trading_date <= request.end
            and bar.adjustment is request.adjustment
        )


def _row_to_bar(row: dict[str, str]) -> Bar:
    return Bar(
        instrument_id=InstrumentId.parse(row["instrument_id"]),
        frequency=BarFrequency.DAY,
        trading_date=date.fromisoformat(row["trading_date"]),
        event_time=_datetime(row["event_time"]),
        available_time=_datetime(row["available_time"]),
        open=Decimal(row["open"]),
        high=Decimal(row["high"]),
        low=Decimal(row["low"]),
        close=Decimal(row["close"]),
        volume=Decimal(row["volume"]),
        turnover=_optional_decimal(row["turnover"]),
        open_interest=_optional_decimal(row["open_interest"]),
        settlement=_optional_decimal(row["settlement"]),
        adjustment=Adjustment(row["adjustment"]),
        availability_estimated=_boolean(row["availability_estimated"]),
    )


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("CSV bar timestamps must be timezone-aware")
    return parsed


def _optional_decimal(value: str) -> Decimal | None:
    return None if value == "" else Decimal(value)


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"invalid boolean value: {value!r}")
    return normalized == "true"

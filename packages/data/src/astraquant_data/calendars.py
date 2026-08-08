"""Imported and versioned trading-session calendars."""

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol, Self

from astraquant_domain import Venue


@dataclass(frozen=True, slots=True)
class TradingSession:
    venue: Venue
    trading_date: date
    session_open: datetime
    session_close: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("session_open", self.session_open),
            ("session_close", self.session_close),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.session_close <= self.session_open:
            raise ValueError("session_close must be after session_open")


class TradingCalendar(Protocol):
    @property
    def calendar_version(self) -> str: ...

    def is_session(self, trading_date: date) -> bool: ...

    def session(self, trading_date: date) -> TradingSession: ...


@dataclass(frozen=True, slots=True)
class CsvTradingCalendar:
    venue: Venue
    source_version: str
    calendar_version: str
    _sessions: dict[date, TradingSession]

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        expected_venue: Venue,
        source_version: str,
    ) -> Self:
        if not source_version.strip():
            raise ValueError("source_version must not be empty")
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        sessions: dict[date, TradingSession] = {}
        for row in rows:
            try:
                venue = Venue(row["venue"].strip().upper())
                trading_date = date.fromisoformat(row["trading_date"].strip())
                session_open = _parse_datetime(row["session_open"])
                session_close = _parse_datetime(row["session_close"])
            except (KeyError, ValueError) as error:
                raise ValueError(f"invalid trading calendar row: {row!r}") from error
            if venue is not expected_venue:
                raise ValueError(
                    f"calendar venue {venue.value} does not match {expected_venue.value}"
                )
            if trading_date in sessions:
                raise ValueError(f"duplicate trading calendar date: {trading_date}")
            sessions[trading_date] = TradingSession(
                venue=venue,
                trading_date=trading_date,
                session_open=session_open,
                session_close=session_close,
            )
        if not sessions:
            raise ValueError("trading calendar must contain at least one session")
        canonical = {
            "source_version": source_version,
            "venue": expected_venue.value,
            "sessions": [
                {
                    "trading_date": trading_date.isoformat(),
                    "session_open": session.session_open.isoformat(),
                    "session_close": session.session_close.isoformat(),
                }
                for trading_date, session in sorted(sessions.items())
            ],
        }
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return cls(
            venue=expected_venue,
            source_version=source_version,
            calendar_version=hashlib.sha256(encoded).hexdigest(),
            _sessions=sessions,
        )

    def is_session(self, trading_date: date) -> bool:
        return trading_date in self._sessions

    def session(self, trading_date: date) -> TradingSession:
        try:
            return self._sessions[trading_date]
        except KeyError:
            raise KeyError(
                f"{trading_date} is not present in {self.venue.value} calendar"
            ) from None


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("calendar timestamps must be timezone-aware")
    return parsed

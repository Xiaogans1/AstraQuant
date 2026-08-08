"""Strict market-bar contracts and deterministic calendar aggregation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class MarketPeriod(StrEnum):
    INTRADAY = "intraday"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    MINUTE_60 = "60m"
    DAY = "1d"
    WEEK = "1w"
    MONTH = "1mo"
    YEAR = "1y"


@dataclass(frozen=True, slots=True)
class MarketBar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal
    previous_close: Decimal | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("market bar timestamp must be timezone-aware")
        if any(value <= 0 for value in (self.open, self.high, self.low, self.close)):
            raise ValueError("market bar prices must be positive")
        if self.high < max(self.open, self.close):
            raise ValueError("market bar high must include open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("market bar low must include open and close")
        if self.low > self.high:
            raise ValueError("market bar low must not exceed high")
        if self.volume < 0 or self.turnover < 0:
            raise ValueError("market bar volume and turnover must be non-negative")
        if self.previous_close is not None and self.previous_close <= 0:
            raise ValueError("market bar previous close must be positive")


def normalize_market_bars(rows: Sequence[Mapping[str, Any]]) -> list[MarketBar]:
    unique: dict[datetime, MarketBar] = {}
    for row in rows:
        raw_timestamp = row.get("bob") or row.get("eob")
        timestamp = (
            raw_timestamp
            if isinstance(raw_timestamp, datetime)
            else datetime.fromisoformat(str(raw_timestamp))
        )
        previous_close = _optional_positive_decimal(row.get("pre_close"))
        item = MarketBar(
            timestamp=timestamp,
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=Decimal(str(row.get("volume", 0) or 0)),
            turnover=Decimal(str(row.get("amount", 0) or 0)),
            previous_close=previous_close,
        )
        unique[timestamp] = item
    return [unique[key] for key in sorted(unique)]


def aggregate_daily_bars(
    bars: Sequence[MarketBar],
    period: MarketPeriod,
) -> list[MarketBar]:
    if period not in (MarketPeriod.WEEK, MarketPeriod.MONTH, MarketPeriod.YEAR):
        raise ValueError("daily bars can only aggregate to week, month or year")
    ordered = sorted(bars, key=lambda item: item.timestamp)
    groups: dict[tuple[int, ...], list[MarketBar]] = {}
    for item in ordered:
        groups.setdefault(_calendar_key(item.timestamp, period), []).append(item)
    return [_aggregate(group) for group in groups.values()]


def _calendar_key(timestamp: datetime, period: MarketPeriod) -> tuple[int, ...]:
    if period is MarketPeriod.WEEK:
        iso_year, iso_week, _ = timestamp.date().isocalendar()
        return (iso_year, iso_week)
    if period is MarketPeriod.MONTH:
        return (timestamp.year, timestamp.month)
    return (timestamp.year,)


def _aggregate(group: Sequence[MarketBar]) -> MarketBar:
    first = group[0]
    last = group[-1]
    return MarketBar(
        timestamp=first.timestamp,
        open=first.open,
        high=max(item.high for item in group),
        low=min(item.low for item in group),
        close=last.close,
        volume=sum((item.volume for item in group), start=Decimal("0")),
        turnover=sum((item.turnover for item in group), start=Decimal("0")),
        previous_close=first.previous_close,
    )


def _optional_positive_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    parsed = Decimal(str(value))
    return parsed if parsed > 0 else None

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from astraquant_data.adapters.akshare import (
    AkShareDailyBarProvider,
    ProviderSchemaError,
)
from astraquant_data.calendars import CsvTradingCalendar
from astraquant_data.providers import HistoryRequest
from astraquant_domain import Adjustment, BarFrequency, InstrumentId, Venue

FIXTURES = Path("tests/fixtures/market_data")


class FakeAkShare:
    def stock_zh_a_hist(self, **_: object) -> FakeFrame:
        return FakeFrame(
            [
                {
                    "日期": "2026-07-24",
                    "开盘": 10,
                    "最高": 11,
                    "最低": 9,
                    "收盘": 10.5,
                    "成交量": 100,
                    "成交额": 105000,
                }
            ]
        )

    def futures_zh_daily_sina(self, **_: object) -> FakeFrame:
        return FakeFrame(
            [
                {
                    "date": "2026-07-23",
                    "open": 3500,
                    "high": 3530,
                    "low": 3480,
                    "close": 3510,
                    "volume": 200,
                    "hold": 300,
                    "settle": 3505,
                },
                {
                    "date": "2026-07-24",
                    "open": 3510,
                    "high": 3540,
                    "low": 3500,
                    "close": 3520,
                    "volume": 220,
                    "hold": 310,
                    "settle": 3515,
                },
            ]
        )


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.columns = tuple(rows[0]) if rows else ()

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        if orient != "records":
            raise ValueError(f"unsupported orientation: {orient}")
        return [dict(row) for row in self._rows]


def calendars() -> dict[Venue, CsvTradingCalendar]:
    return {
        Venue.SSE: CsvTradingCalendar.load(
            FIXTURES / "cn_equity_sessions.csv",
            expected_venue=Venue.SSE,
            source_version="fixture-v1",
        ),
        Venue.SHFE: CsvTradingCalendar.load(
            FIXTURES / "cn_futures_sessions.csv",
            expected_venue=Venue.SHFE,
            source_version="fixture-v1",
        ),
    }


def test_stock_daily_data_is_normalized_with_estimated_availability() -> None:
    provider = AkShareDailyBarProvider(client=FakeAkShare(), calendars=calendars())
    request = HistoryRequest(
        instrument_id=InstrumentId.parse("600000.SSE"),
        frequency=BarFrequency.DAY,
        start=date(2026, 7, 24),
        end=date(2026, 7, 24),
        adjustment=Adjustment.NONE,
    )

    bars = provider.fetch_bars(request)

    assert len(bars) == 1
    assert str(bars[0].instrument_id) == "600000.SSE"
    assert bars[0].available_time > bars[0].event_time
    assert bars[0].availability_estimated is True
    assert bars[0].volume == Decimal("10000")
    assert provider.provider_metadata(request).volume_unit == "share"


def test_futures_continuous_data_preserves_settlement_and_open_interest() -> None:
    provider = AkShareDailyBarProvider(client=FakeAkShare(), calendars=calendars())
    request = HistoryRequest(
        instrument_id=InstrumentId.parse("RB0.SHFE"),
        frequency=BarFrequency.DAY,
        start=date(2026, 7, 24),
        end=date(2026, 7, 24),
    )

    bars = provider.fetch_bars(request)
    metadata = provider.provider_metadata(request)

    assert len(bars) == 1
    assert bars[0].settlement == Decimal("3515")
    assert bars[0].open_interest == Decimal("310")
    assert metadata.series_kind == "continuous"
    assert metadata.roll_policy == "upstream_provider"
    assert metadata.volume_unit == "contract"


def test_provider_rejects_an_upstream_schema_change() -> None:
    client = FakeAkShare()
    client.stock_zh_a_hist = lambda **_: FakeFrame(  # type: ignore[method-assign]
        [{"日期": "2026-07-24"}]
    )
    provider = AkShareDailyBarProvider(client=client, calendars=calendars())

    with pytest.raises(ProviderSchemaError, match="missing"):
        provider.fetch_bars(
            HistoryRequest(
                instrument_id=InstrumentId.parse("600000.SSE"),
                frequency=BarFrequency.DAY,
                start=date(2026, 7, 24),
                end=date(2026, 7, 24),
            )
        )

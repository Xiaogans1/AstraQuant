from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from astraquant_data.adapters.akshare_live import AkShareDelayedProvider
from astraquant_data.market_bars import MarketPeriod
from astraquant_domain import InstrumentId, MarketEventQuality


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 12, 2, 31, tzinfo=UTC)


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.columns = tuple(rows[0]) if rows else ()

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        assert orient == "records"
        return [dict(row) for row in self.rows]


class FakeAkShare:
    def stock_zh_a_spot_em(self) -> FakeFrame:
        return FakeFrame(
            [
                {
                    "代码": "600000",
                    "名称": "浦发银行",
                    "最新价": 10.5,
                    "今开": 10,
                    "最高": 10.8,
                    "最低": 9.9,
                    "昨收": 9.8,
                    "成交量": 12345,
                    "成交额": 12962250,
                },
                {
                    "代码": "000001",
                    "名称": "平安银行",
                    "最新价": 11,
                    "今开": 10.9,
                    "最高": 11.1,
                    "最低": 10.8,
                    "昨收": 10.7,
                    "成交量": 100,
                    "成交额": 110000,
                },
            ]
        )

    def stock_zh_a_hist_min_em(self, **_: object) -> FakeFrame:
        return FakeFrame(
            [
                {
                    "时间": "2026-08-12 09:35:00",
                    "开盘": 10,
                    "最高": 10.8,
                    "最低": 9.9,
                    "收盘": 10.5,
                    "成交量": 100,
                    "成交额": 105000,
                }
            ]
        )

    def stock_zh_index_spot_em(self, **_: object) -> FakeFrame:
        return FakeFrame(
            [
                {
                    "代码": "000001",
                    "名称": "上证指数",
                    "最新价": 3300,
                    "今开": 3290,
                    "最高": 3310,
                    "最低": 3280,
                    "昨收": 3295,
                    "成交量": 10000,
                    "成交额": 100000000,
                }
            ]
        )

    def stock_zh_a_hist(self, **_: object) -> FakeFrame:
        return FakeFrame(
            [
                {
                    "日期": "2026-08-11",
                    "开盘": 10,
                    "最高": 10.8,
                    "最低": 9.9,
                    "收盘": 10.5,
                    "成交量": 100,
                    "成交额": 105000,
                }
            ]
        )

    def tool_trade_date_hist_sina(self) -> FakeFrame:
        return FakeFrame([{"trade_date": "2026-08-12"}])


def test_delayed_provider_polls_searches_and_marks_quotes_delayed() -> None:
    provider = AkShareDelayedProvider(client=FakeAkShare(), clock=FixedClock())
    provider.connect("")

    quotes = provider.poll(
        (InstrumentId.parse("600000.SSE"), InstrumentId.parse("000001.SSE"))
    )
    results = provider.search("浦发")

    assert len(quotes) == 2
    assert quotes[0].source_id == "akshare-eastmoney-web"
    assert quotes[0].quality == frozenset({MarketEventQuality.DELAYED})
    assert str(quotes[1].instrument_id) == "000001.SSE"
    assert results == [{"instrument_id": "600000.SSE", "name": "浦发银行"}]


def test_delayed_provider_normalizes_minute_daily_and_calendar() -> None:
    provider = AkShareDelayedProvider(client=FakeAkShare(), clock=FixedClock())
    instrument = InstrumentId.parse("600000.SSE")

    minute = provider.bars(instrument, period=MarketPeriod.MINUTE_5, count=20)
    daily = provider.bars(instrument, period=MarketPeriod.DAY, count=20)

    assert minute[0].timestamp.isoformat() == "2026-08-12T09:35:00+08:00"
    assert minute[0].volume == 10000
    assert daily[0].timestamp.isoformat() == "2026-08-11T00:00:00+08:00"
    assert provider.trading_dates(date(2026, 8, 12), date(2026, 8, 12)) == [
        date(2026, 8, 12)
    ]

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from astraquant_data import public_quotes
from astraquant_domain import InstrumentId, MarketEventQuality

RECEIVED = datetime(2026, 8, 12, 3, 36, tzinfo=UTC)


def test_tencent_fetches_only_requested_symbols_and_normalizes_quotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_url = ""

    def download(url: str, *, referer: str | None = None) -> str:
        nonlocal requested_url
        requested_url = url
        assert referer is None
        return (
            'v_sh600000="1~浦发银行~600000~9.17~9.21~9.21~284739~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~'
            '20260812113541~-0.04~-0.43~9.22~9.12~9.17/284739/261040533~284739~26104.0533~0";'
        )

    monkeypatch.setattr(public_quotes, "_download", download)
    quotes, parse_errors = public_quotes.fetch_public_quotes(
        (InstrumentId.parse("600000.SSE"),), RECEIVED
    )

    assert requested_url == "https://qt.gtimg.cn/q=sh600000"
    assert parse_errors == 0
    assert quotes[0].last_price.as_tuple() == (0, (9, 1, 7), -2)
    assert quotes[0].cumulative_volume == 28_473_900
    assert quotes[0].source_id == "tencent-public-web"
    assert quotes[0].quality == frozenset({MarketEventQuality.DELAYED})


def test_sina_is_used_when_tencent_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def download(url: str, *, referer: str | None = None) -> str:
        calls.append(url)
        if "gtimg" in url:
            raise ConnectionError("blocked")
        assert referer == "https://finance.sina.com.cn/"
        return (
            'var hq_str_sz000001="平安银行,11.260,11.260,11.210,11.290,11.200,'
            "11.210,11.220,34023384,382133840.530,0,0,0,0,0,0,0,0,0,0,0,0,0,0,"
            '0,0,0,0,0,0,2026-08-12,11:30:00,00,";'
        )

    monkeypatch.setattr(public_quotes, "_download", download)
    quotes, parse_errors = public_quotes.fetch_public_quotes(
        (InstrumentId.parse("000001.SZSE"),), RECEIVED
    )

    assert len(calls) == 2
    assert parse_errors == 0
    assert quotes[0].source_id == "sina-public-web"
    assert quotes[0].event_time.isoformat() == "2026-08-12T11:30:00+08:00"


def test_tencent_search_is_bounded_and_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        public_quotes,
        "_download",
        lambda url: 'v_hint="sh~600000~\\u6d66\\u53d1\\u94f6\\u884c~pfyh~GP-A"',
    )

    assert public_quotes.search_public_instruments("浦发") == [
        {
            "instrument_id": "600000.SSE",
            "symbol": "600000",
            "sec_name": "浦发银行",
            "name": "浦发银行",
        }
    ]

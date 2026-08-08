from datetime import UTC, datetime
from decimal import Decimal

import pytest

from astraquant_data.eastmoney_protocol import (
    from_eastmoney_symbol,
    map_current_quote,
    to_eastmoney_symbol,
)
from astraquant_domain import InstrumentId


@pytest.mark.parametrize(
    ("canonical", "eastmoney"),
    [
        ("000001.SSE", "SHSE.000001"),
        ("399001.SZSE", "SZSE.399001"),
        ("920001.BSE", "BJSE.920001"),
        ("IF2608.CFFEX", "CFFEX.IF2608"),
        ("RB2610.SHFE", "SHFE.RB2610"),
    ],
)
def test_maps_exchange_codes_without_guessing(canonical: str, eastmoney: str) -> None:
    instrument_id = InstrumentId.parse(canonical)
    assert to_eastmoney_symbol(instrument_id) == eastmoney
    assert from_eastmoney_symbol(eastmoney) == instrument_id


def test_rejects_an_unknown_eastmoney_exchange() -> None:
    with pytest.raises(ValueError, match="exchange"):
        from_eastmoney_symbol("UNKNOWN.000001")


def test_maps_current_snapshot_to_a_real_source_quote() -> None:
    received_at = datetime(2026, 8, 5, 2, 30, 4, tzinfo=UTC)
    quote = map_current_quote(
        {
            "symbol": "SHSE.000001",
            "price": 3560.12,
            "pre_close": 3540.0,
            "open": 3544.2,
            "high": 3565.1,
            "low": 3538.4,
            "cum_volume": 1200,
            "cum_amount": 4300000.0,
            "cum_position": 0,
            "created_at": "2026-08-05T10:30:03+08:00",
            "quotes": [
                {"bid_p": 3560.1, "bid_v": 4, "ask_p": 3560.2, "ask_v": 5},
            ],
        },
        received_at=received_at,
    )

    assert str(quote.instrument_id) == "000001.SSE"
    assert quote.source_id == "eastmoney"
    assert quote.received_time == received_at
    assert quote.previous_close == Decimal("3540.0")
    assert quote.bid[0].price == Decimal("3560.1")
    assert quote.ask[0].volume == 5


def test_rejects_missing_or_naive_event_times() -> None:
    payload = {
        "symbol": "SHSE.000001",
        "price": 10,
        "pre_close": 9,
        "open": 10,
        "high": 10,
        "low": 10,
        "cum_volume": 0,
        "created_at": "2026-08-05T10:30:03",
    }
    with pytest.raises(ValueError, match="timezone-aware"):
        map_current_quote(payload)


@pytest.mark.parametrize("pre_close", [None, "", 0, "0"])
def test_missing_previous_close_stays_unknown(pre_close: object) -> None:
    quote = map_current_quote(
        {
            "symbol": "SZSE.159516",
            "price": 0.712,
            "pre_close": pre_close,
            "open": 0.680,
            "high": 0.716,
            "low": 0.677,
            "cum_volume": 481900,
            "cum_amount": 34260000,
            "created_at": "2026-08-06T10:11:00+08:00",
        }
    )

    assert quote.previous_close is None
    assert quote.change is None
    assert quote.change_percent is None

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_data.eastmoney_protocol import (
    HistoryCompletenessError,
    HistoryPage,
    HistoryPageEvidence,
    HistoryPageSpec,
    PageFailureCode,
    from_eastmoney_symbol,
    map_current_quote,
    to_eastmoney_symbol,
    validate_history_pages,
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


def _page_spec(index: int, start: datetime) -> HistoryPageSpec:
    return HistoryPageSpec(
        index=index,
        page_count=2,
        cursor=f"page-{index}",
        start_at=start,
        end_at=start + timedelta(days=1),
    )


def _history_page(
    spec: HistoryPageSpec,
    *,
    rows: tuple[dict[str, object], ...] | None = None,
    declared_total: int | None = 2,
    schema_digest: str = "sha256:" + "1" * 64,
    units: tuple[str, ...] = ("price=CNY", "volume=share"),
    adjust: int = 0,
) -> HistoryPage:
    materialized_rows: tuple[dict[str, object], ...] = (
        ({"bob": spec.start_at.isoformat()},) if rows is None else rows
    )
    return HistoryPage(
        rows=materialized_rows,
        evidence=HistoryPageEvidence(
            spec=spec,
            returned_count=len(materialized_rows),
            declared_total=declared_total,
            frequency="1d",
            adjust=adjust,
            units=units,
            schema_digest=schema_digest,
            request_digest="sha256:" + "2" * 64,
            response_digest="sha256:" + "3" * 64,
        ),
    )


def test_history_pages_require_explicit_coverage_proof() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    specs = (_page_spec(0, start), _page_spec(1, start + timedelta(days=2)))
    pages = tuple(_history_page(spec) for spec in specs)

    batch = validate_history_pages(pages, expected_specs=specs)

    assert len(batch.rows) == 2
    assert batch.complete is True
    assert batch.declared_total == 2


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda pages: (pages[0], pages[0]), PageFailureCode.DUPLICATE_PAGE),
        (lambda pages: pages[:1], PageFailureCode.MISSING_PAGE),
        (
            lambda pages: (
                pages[1],
                pages[0],
            ),
            PageFailureCode.OUT_OF_ORDER,
        ),
        (
            lambda pages: (
                pages[0],
                _history_page(pages[1].evidence.spec, schema_digest="sha256:" + "4" * 64),
            ),
            PageFailureCode.SCHEMA_DRIFT,
        ),
        (
            lambda pages: (
                pages[0],
                _history_page(pages[1].evidence.spec, units=("price=fen",)),
            ),
            PageFailureCode.UNIT_DRIFT,
        ),
        (
            lambda pages: (pages[0], _history_page(pages[1].evidence.spec, adjust=1)),
            PageFailureCode.ADJUST_DRIFT,
        ),
    ],
)
def test_history_page_faults_fail_closed(
    mutate: object,
    code: PageFailureCode,
) -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    specs = (_page_spec(0, start), _page_spec(1, start + timedelta(days=2)))
    pages = tuple(_history_page(spec) for spec in specs)

    with pytest.raises(HistoryCompletenessError) as raised:
        validate_history_pages(mutate(pages), expected_specs=specs)  # type: ignore[operator]

    assert raised.value.code is code


def test_history_pages_reject_silent_truncation_and_unproven_empty_success() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    spec = HistoryPageSpec(
        index=0,
        page_count=1,
        cursor="page-0",
        start_at=start,
        end_at=start + timedelta(days=1),
    )

    with pytest.raises(HistoryCompletenessError) as truncated:
        validate_history_pages(
            (_history_page(spec, rows=(), declared_total=1),),
            expected_specs=(spec,),
        )
    assert truncated.value.code is PageFailureCode.SILENT_TRUNCATION

    with pytest.raises(HistoryCompletenessError) as unproven:
        validate_history_pages(
            (_history_page(spec, rows=(), declared_total=None),),
            expected_specs=(spec,),
        )
    assert unproven.value.code is PageFailureCode.UNPROVEN_COMPLETENESS

    empty = validate_history_pages(
        (_history_page(spec, rows=(), declared_total=None),),
        expected_specs=(spec,),
        expected_total=0,
    )
    assert empty.complete is True


def test_history_pages_reject_overlapping_ranges_and_rows_outside_page() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    first = _page_spec(0, start)
    overlapping = HistoryPageSpec(
        index=1,
        page_count=2,
        cursor="page-1",
        start_at=start + timedelta(hours=12),
        end_at=start + timedelta(days=2),
    )
    with pytest.raises(HistoryCompletenessError) as overlap:
        validate_history_pages(
            (_history_page(first), _history_page(overlapping)),
            expected_specs=(first, overlapping),
        )
    assert overlap.value.code is PageFailureCode.OVERLAPPING_RANGE

    single = HistoryPageSpec(
        index=0,
        page_count=1,
        cursor="page-0",
        start_at=start,
        end_at=start + timedelta(days=1),
    )
    outside = _history_page(
        single,
        rows=({"bob": (start + timedelta(days=2)).isoformat()},),
        declared_total=1,
    )
    with pytest.raises(HistoryCompletenessError) as out_of_range:
        validate_history_pages((outside,), expected_specs=(single,))
    assert out_of_range.value.code is PageFailureCode.ROW_OUT_OF_RANGE

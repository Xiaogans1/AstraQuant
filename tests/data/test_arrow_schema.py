import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from astraquant_data.arrow_schema import BAR_SCHEMA, bars_to_table, table_to_bars

from .factories import make_bar


def test_bar_arrow_round_trip_uses_the_canonical_schema() -> None:
    bars = [
        make_bar(symbol="RB2610.SHFE", day=25, close="3510"),
        make_bar(symbol="600000.SSE", day=24),
    ]

    table = bars_to_table(bars)

    assert table.schema == BAR_SCHEMA
    assert table.column_names == [
        "instrument_id",
        "venue",
        "frequency",
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
    ]
    assert table_to_bars(table) == tuple(sorted(bars, key=lambda bar: str(bar.instrument_id)))


def test_table_to_bars_rejects_schema_drift() -> None:
    table = pa.table({"instrument_id": ["600000.SSE"]})

    with pytest.raises(ValueError, match="schema"):
        table_to_bars(table)

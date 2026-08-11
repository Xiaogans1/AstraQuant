"""Canonical Arrow schemas and domain conversion for market data."""

from datetime import UTC
from decimal import Decimal

import pyarrow as pa  # type: ignore[import-untyped]

from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId, Venue

from .canonical_schema import CANONICAL_BAR_SCHEMA as CANONICAL_BAR_SCHEMA

_PRICE_QUANTUM = Decimal("0.00000001")
_MEASURE_QUANTUM = Decimal("0.00000001")
_DICTIONARY_STRING = pa.dictionary(pa.int8(), pa.string())

BAR_SCHEMA = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("venue", _DICTIONARY_STRING, nullable=False),
        pa.field("frequency", _DICTIONARY_STRING, nullable=False),
        pa.field("trading_date", pa.date32(), nullable=False),
        pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("available_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("open", pa.decimal128(24, 8), nullable=False),
        pa.field("high", pa.decimal128(24, 8), nullable=False),
        pa.field("low", pa.decimal128(24, 8), nullable=False),
        pa.field("close", pa.decimal128(24, 8), nullable=False),
        pa.field("volume", pa.decimal128(30, 8), nullable=False),
        pa.field("turnover", pa.decimal128(30, 8)),
        pa.field("open_interest", pa.decimal128(30, 8)),
        pa.field("settlement", pa.decimal128(24, 8)),
        pa.field("adjustment", _DICTIONARY_STRING, nullable=False),
        pa.field("availability_estimated", pa.bool_(), nullable=False),
    ]
)


def bars_to_table(bars: list[Bar] | tuple[Bar, ...]) -> pa.Table:
    ordered = sorted(
        bars,
        key=lambda bar: (
            str(bar.instrument_id),
            bar.event_time,
            bar.available_time,
        ),
    )
    records = [
        {
            "instrument_id": str(bar.instrument_id),
            "venue": bar.instrument_id.venue.value,
            "frequency": bar.frequency.value,
            "trading_date": bar.trading_date,
            "event_time": bar.event_time.astimezone(UTC),
            "available_time": bar.available_time.astimezone(UTC),
            "open": _quantize(bar.open, _PRICE_QUANTUM),
            "high": _quantize(bar.high, _PRICE_QUANTUM),
            "low": _quantize(bar.low, _PRICE_QUANTUM),
            "close": _quantize(bar.close, _PRICE_QUANTUM),
            "volume": _quantize(bar.volume, _MEASURE_QUANTUM),
            "turnover": _optional_quantize(bar.turnover, _MEASURE_QUANTUM),
            "open_interest": _optional_quantize(bar.open_interest, _MEASURE_QUANTUM),
            "settlement": _optional_quantize(bar.settlement, _PRICE_QUANTUM),
            "adjustment": bar.adjustment.value,
            "availability_estimated": bar.availability_estimated,
        }
        for bar in ordered
    ]
    return pa.Table.from_pylist(records, schema=BAR_SCHEMA)


def table_to_bars(table: pa.Table) -> tuple[Bar, ...]:
    if table.schema != BAR_SCHEMA:
        raise ValueError(f"bar table schema does not match canonical schema: {table.schema}")
    bars: list[Bar] = []
    for row in table.to_pylist():
        instrument_id = InstrumentId.parse(row["instrument_id"])
        venue = Venue(row["venue"])
        if instrument_id.venue is not venue:
            raise ValueError("venue column does not match instrument identifier")
        bars.append(
            Bar(
                instrument_id=instrument_id,
                frequency=BarFrequency(row["frequency"]),
                trading_date=row["trading_date"],
                event_time=row["event_time"],
                available_time=row["available_time"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                turnover=row["turnover"],
                open_interest=row["open_interest"],
                settlement=row["settlement"],
                adjustment=Adjustment(row["adjustment"]),
                availability_estimated=row["availability_estimated"],
            )
        )
    return tuple(bars)


def _quantize(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum)


def _optional_quantize(value: Decimal | None, quantum: Decimal) -> Decimal | None:
    return None if value is None else _quantize(value, quantum)

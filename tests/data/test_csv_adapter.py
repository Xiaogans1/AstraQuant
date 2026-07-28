from datetime import date
from decimal import Decimal
from pathlib import Path

from astraquant_data.adapters.csv_bars import CsvDailyBarProvider
from astraquant_data.providers import HistoryRequest
from astraquant_domain import BarFrequency, InstrumentId

FIXTURES = Path("tests/fixtures/market_data")


def test_csv_provider_imports_a_share_daily_bars() -> None:
    provider = CsvDailyBarProvider(
        FIXTURES / "cn_equity_daily_bars.csv",
        source_version="fixture-v1",
    )

    bars = provider.fetch_bars(
        HistoryRequest(
            instrument_id=InstrumentId.parse("600000.SSE"),
            frequency=BarFrequency.DAY,
            start=date(2026, 7, 24),
            end=date(2026, 7, 24),
        )
    )

    assert len(bars) == 1
    assert bars[0].close == Decimal("10.50")
    assert provider.provider_id() == "fixture-csv"


def test_csv_provider_filters_other_instruments() -> None:
    provider = CsvDailyBarProvider(
        FIXTURES / "cn_futures_daily_bars.csv",
        source_version="fixture-v1",
    )

    bars = provider.fetch_bars(
        HistoryRequest(
            instrument_id=InstrumentId.parse("IF2608.CFFEX"),
            frequency=BarFrequency.DAY,
            start=date(2026, 7, 24),
            end=date(2026, 7, 24),
        )
    )

    assert bars == ()

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from astraquant_data.eastmoney_daily_bootstrap import (
    eastmoney_daily_rows_to_domain_bars,
    publish_compact_daily_snapshot,
    select_liquid_common_a_share_candidates,
)


def _instrument(
    symbol: str,
    name: str,
    listed: str,
    delisted: str = "2038-01-01",
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "sec_name": name,
        "listed_date": f"{listed}T00:00:00+08:00",
        "delisted_date": f"{delisted}T00:00:00+08:00",
        "sec_type": 1,
        "sec_type_ext": 0,
    }


def test_candidate_selection_keeps_liquid_active_common_a_shares_deterministically() -> None:
    instruments = [
        _instrument("SHSE.600000", "浦发银行", "1999-11-10"),
        _instrument("SZSE.000001", "平安银行", "1991-04-03"),
        _instrument("SHSE.688001", "华兴源创", "2019-07-22"),
        _instrument("SZSE.200001", "深物业B", "1992-03-30"),
        _instrument("SHSE.600001", "已退市", "1992-01-01", "2020-01-01"),
        _instrument("SHSE.600002", "ST样本", "1992-01-01"),
    ]
    quotes = [
        {"symbol": "SZSE.000001", "price": 10.0, "cum_amount": 2_000_000.0},
        {"symbol": "SHSE.688001", "price": 20.0, "cum_amount": 3_000_000.0},
        {"symbol": "SHSE.600000", "price": 9.0, "cum_amount": 1_000_000.0},
        {"symbol": "SHSE.600002", "price": 5.0, "cum_amount": 9_000_000.0},
    ]

    selected = select_liquid_common_a_share_candidates(
        instruments,
        quotes,
        as_of=date(2026, 8, 13),
        target_size=3,
    )

    assert [item.instrument_id for item in selected] == [
        "688001.SSE",
        "000001.SZSE",
        "600000.SSE",
    ]
    assert selected[0].current_turnover == 3_000_000.0


def test_daily_rows_map_to_unadjusted_domain_bars_and_reject_wrong_symbol() -> None:
    rows = [
        {
            "symbol": "SHSE.600000",
            "bob": "2026-08-12T00:00:00+08:00",
            "eob": "2026-08-12T15:00:00+08:00",
            "open": 9.1,
            "high": 9.3,
            "low": 9.0,
            "close": 9.2,
            "volume": 10_000,
            "amount": 92_000,
            "pre_close": 9.0,
        }
    ]

    bars = eastmoney_daily_rows_to_domain_bars("600000.SSE", rows)

    assert len(bars) == 1
    assert str(bars[0].instrument_id) == "600000.SSE"
    assert bars[0].frequency.value == "1d"
    assert bars[0].adjustment.value == "none"
    assert bars[0].event_time.isoformat() == "2026-08-12T15:00:00+08:00"
    assert bars[0].available_time.isoformat() == "2026-08-12T15:00:00+08:00"

    with pytest.raises(ValueError, match="symbol"):
        eastmoney_daily_rows_to_domain_bars(
            "000001.SZSE",
            rows,
        )


def test_compact_daily_snapshot_is_repeatable_and_uses_one_parquet_file(
    tmp_path: Path,
) -> None:
    bars = eastmoney_daily_rows_to_domain_bars(
        "600000.SSE",
        [
            {
                "symbol": "SHSE.600000",
                "eob": "2026-08-12T15:00:00+08:00",
                "open": 9.1,
                "high": 9.3,
                "low": 9.0,
                "close": 9.2,
                "volume": 10_000,
                "amount": 92_000,
            }
        ],
    )
    fetched_at = datetime.fromisoformat("2026-08-13T07:01:00+00:00")
    provider = {"id": "eastmoney", "interface": "gm_python_sdk", "version": "3.0.186"}

    first = publish_compact_daily_snapshot(
        tmp_path,
        dataset_id="cn-equity-600000-sse-1d-none",
        bars=bars,
        provider=provider,
        source_fetched_at=fetched_at,
    )
    second = publish_compact_daily_snapshot(
        tmp_path,
        dataset_id="cn-equity-600000-sse-1d-none",
        bars=bars,
        provider=provider,
        source_fetched_at=fetched_at,
    )

    assert first.snapshot_id == second.snapshot_id
    assert len(first.manifest.files) == 1
    assert first.manifest.files[0].path == "bars.parquet"
    assert (first.snapshot_path / "bars.parquet").is_file()

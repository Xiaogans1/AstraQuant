from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tools.data.bootstrap_stage_b_v2_eastmoney import bootstrap_daily_snapshots


@dataclass(frozen=True)
class _Evidence:
    interface_build: str = "3.0.test"
    received_at: datetime = datetime(2026, 8, 13, 7, 1, tzinfo=UTC)

    def to_dict(self) -> dict[str, object]:
        return {
            "interface_build": self.interface_build,
            "received_at": self.received_at.isoformat(),
        }


class _Client:
    def stock_instruments_with_evidence(self) -> SimpleNamespace:
        return SimpleNamespace(
            result=[
                self._instrument("SHSE.600000", "浦发银行"),
                self._instrument("SZSE.000001", "平安银行"),
                self._instrument("SHSE.688001", "华兴源创"),
            ],
            evidence=_Evidence(),
        )

    def current_with_evidence(self, symbols: list[str]) -> SimpleNamespace:
        amounts = {"SHSE.600000": 10.0, "SZSE.000001": 30.0, "SHSE.688001": 20.0}
        return SimpleNamespace(
            result=[
                {"symbol": symbol, "price": 10.0, "cum_amount": amounts[symbol]}
                for symbol in symbols
            ],
            evidence=_Evidence(),
        )

    def history_page_with_evidence(self, **values: Any) -> SimpleNamespace:
        symbol = str(values["symbol"])
        rows = [
            {
                "symbol": symbol,
                "bob": f"2026-08-{day:02d}T00:00:00+08:00",
                "eob": f"2026-08-{day:02d}T15:00:00+08:00",
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.2,
                "volume": 1000,
                "amount": 10_200,
            }
            for day in (10, 11, 12)
        ]
        return SimpleNamespace(
            page=SimpleNamespace(rows=tuple(rows)),
            response=SimpleNamespace(result={"rows": rows}, evidence=_Evidence()),
        )

    @staticmethod
    def _instrument(symbol: str, name: str) -> dict[str, object]:
        return {
            "symbol": symbol,
            "sec_name": name,
            "listed_date": "2000-01-01T00:00:00+08:00",
            "delisted_date": "2038-01-01T00:00:00+08:00",
            "sec_type": 1,
            "sec_type_ext": 0,
        }


def test_bootstrap_discovers_and_publishes_resumable_real_daily_snapshots(
    tmp_path: Path,
) -> None:
    result = bootstrap_daily_snapshots(
        client=_Client(),
        output_root=tmp_path / "bootstrap",
        start=date(2021, 8, 12),
        end=date(2026, 8, 12),
        target_size=2,
        benchmark_provider_symbol="SHSE.000985",
        quote_batch_size=2,
    )

    assert result["status"] == "COMPLETE"
    assert result["instrument_count"] == 2
    assert result["benchmark"]["instrument_id"] == "000985.SSE"
    assert [item["instrument_id"] for item in result["sources"]] == [
        "000001.SZSE",
        "688001.SSE",
    ]
    assert (tmp_path / "bootstrap" / "bootstrap.json").is_file()
    assert (tmp_path / "bootstrap" / "selection.json").is_file()
    assert len(list((tmp_path / "bootstrap" / "raw").glob("*.json"))) == 3
    assert all(
        (
            tmp_path
            / "bootstrap"
            / "data"
            / "datasets"
            / item["dataset_id"]
            / "snapshots"
            / item["snapshot_id"]
            / "bars.parquet"
        ).is_file()
        for item in [*result["sources"], result["benchmark"]]
    )

    repeated = bootstrap_daily_snapshots(
        client=_Client(),
        output_root=tmp_path / "bootstrap",
        start=date(2021, 8, 12),
        end=date(2026, 8, 12),
        target_size=2,
        benchmark_provider_symbol="SHSE.000985",
        quote_batch_size=2,
    )
    assert repeated == result

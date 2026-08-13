from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tests.data.test_bootstrap_stage_b_v2_eastmoney_cli import _Client, _Evidence

from astraquant_domain import HistoricalUniversePolicy
from tools.data.bootstrap_stage_b_v2_eastmoney import bootstrap_daily_snapshots
from tools.research.build_stage_b_v2_real_export import build_stage_b_v2_real_export


class _LongHistoryClient(_Client):
    def history_page_with_evidence(self, **values: Any) -> SimpleNamespace:
        symbol = str(values["symbol"])
        start = date(2026, 6, 1)
        rows = []
        for index in range(50):
            session = start + timedelta(days=index)
            close = 10 + index / 100
            rows.append(
                {
                    "symbol": symbol,
                    "bob": f"{session.isoformat()}T00:00:00+08:00",
                    "eob": f"{session.isoformat()}T15:00:00+08:00",
                    "open": close - 0.02,
                    "high": close + 0.05,
                    "low": close - 0.05,
                    "close": close,
                    "volume": 1000 + index,
                    "amount": (1000 + index) * close,
                }
            )
        return SimpleNamespace(
            page=SimpleNamespace(rows=tuple(rows)),
            response=SimpleNamespace(result={"rows": rows}, evidence=_Evidence()),
        )


def test_real_export_builds_dynamic_panel_context_and_labels_from_exact_snapshots(
    tmp_path: Path,
) -> None:
    bootstrap = tmp_path / "bootstrap"
    bootstrap_daily_snapshots(
        client=_LongHistoryClient(),
        output_root=bootstrap,
        start=date(2021, 8, 12),
        end=date(2026, 8, 12),
        target_size=2,
        benchmark_provider_symbol="SHSE.000985",
        quote_batch_size=2,
    )
    policy = HistoricalUniversePolicy(
        schema_version="astraquant.historical-universe-policy/v1",
        liquidity_lookback_sessions=20,
        minimum_history_sessions=21,
        target_size=2,
        minimum_size=2,
        maximum_size=2,
        minimum_price=Decimal("2"),
        minimum_observation_ratio=Decimal("0.95"),
        exclude_special_treatment=True,
        common_a_share_only=True,
    )

    first = build_stage_b_v2_real_export(
        bootstrap_root=bootstrap,
        output_root=tmp_path / "first",
        universe_policy=policy,
    )
    second = build_stage_b_v2_real_export(
        bootstrap_root=bootstrap,
        output_root=tmp_path / "second",
        universe_policy=policy,
    )

    assert first == second
    assert first["run_class"] == "EXPLORATORY_REAL_API_CURRENT_STATUS"
    assert first["instrument_count"] == 2
    assert first["membership_session_count"] > 0
    assert first["context_row_count"] > 0
    assert first["label_row_count"] > first["context_row_count"]
    assert first["content_digest"].startswith("sha256:")
    assert (tmp_path / "first" / "request.json").is_file()
    assert (tmp_path / "first" / "bars.parquet").is_file()
    assert (tmp_path / "first" / "context.parquet").is_file()
    assert (tmp_path / "first" / "labels.parquet").is_file()

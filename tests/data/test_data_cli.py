from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from astraquant_data import cli
from astraquant_data.adapters.akshare import ProviderMetadata
from astraquant_data.providers import HistoryRequest
from astraquant_domain import Adjustment, Bar, BarFrequency


class FakeProvider:
    def fetch_bars(self, request: HistoryRequest) -> tuple[Bar, ...]:
        event_time = datetime(2026, 7, 24, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
        return (
            Bar(
                instrument_id=request.instrument_id,
                frequency=BarFrequency.FIVE_MINUTE,
                trading_date=request.start,
                event_time=event_time,
                available_time=event_time + timedelta(minutes=1),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10.5"),
                volume=Decimal("10000"),
                turnover=Decimal("105000"),
                open_interest=None,
                settlement=None,
                adjustment=Adjustment.NONE,
                availability_estimated=True,
            ),
        )

    def provider_metadata(self, request: HistoryRequest) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id="akshare",
            interface="stock_zh_a_hist_min_em",
            version="test",
            volume_unit="share",
            series_kind="instrument",
            roll_policy=None,
            calendar_version="test-calendar-v1",
            availability_policy="estimated_bar_end_plus_1m",
        )


def test_cli_publishes_complete_batch_with_exploratory_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "AkShareFiveMinuteBarProvider", FakeProvider)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "astraquant-data",
            "collect-5m",
            "--date",
            "2026-07-24",
            "--instrument",
            "600000.SSE",
            "--checkpoint",
            str(tmp_path / "checkpoint"),
            "--data-root",
            str(tmp_path / "data"),
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    manifest = Path(output["manifest_path"])
    evidence = Path(output["evidence_path"])
    assert output["status"] == "published"
    assert output["evidence_class"] == "EXPLORATORY_ONLY"
    assert manifest.exists()
    assert evidence.parent == tmp_path / "checkpoint"
    assert json.loads(evidence.read_text())["snapshot_id"] == output["snapshot_id"]

    cli.main()
    rerun = json.loads(capsys.readouterr().out)
    assert rerun["status"] == "already_published"
    assert rerun["snapshot_id"] == output["snapshot_id"]
    assert rerun["resumed"] == ["600000.SSE"]

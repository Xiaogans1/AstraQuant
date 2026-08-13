from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from astraquant_data.daily_panel import (
    DailyPanelSource,
    build_exact_eastmoney_daily_panel,
)
from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_data.research_store import load_exact_dataset_snapshot
from astraquant_domain import FixedClock

from .factories import make_bar

EASTMONEY = {"id": "eastmoney", "interface": "gm_python_sdk", "version": "v1"}


@dataclass(frozen=True, slots=True)
class _Universe:
    members_by_time: dict[datetime, frozenset[str]]
    snapshot_digest: str = f"sha256:{'f' * 64}"


def _publish(
    root: Path,
    dataset_id: str,
    instrument_id: str,
    *,
    days: tuple[int, ...] = (24, 25, 26, 27),
    provider: dict[str, str] | None = None,
) -> DailyPanelSource:
    store = ParquetSnapshotStore(
        root,
        clock=FixedClock(datetime(2026, 8, 1, tzinfo=UTC)),
    )
    published = store.publish_bars(
        dataset_id=dataset_id,
        bars=[make_bar(symbol=instrument_id, day=day) for day in days],
        provider=EASTMONEY if provider is None else provider,
        calendar_version="sse-szse-2026",
        availability_policy="session-close",
    )
    return DailyPanelSource(
        dataset_id=dataset_id,
        instrument_id=instrument_id,
        snapshot_id=published.snapshot_id,
    )


def _sources(root: Path) -> tuple[DailyPanelSource, DailyPanelSource, DailyPanelSource]:
    return (
        _publish(root, "cn-equity-a-daily", "600000.SSE"),
        _publish(root, "cn-equity-b-daily", "000001.SZSE", days=(24, 26, 27)),
        _publish(root, "cn-index-benchmark-daily", "000985.SSE"),
    )


def test_exact_snapshot_loader_verifies_daily_identity_and_provider(tmp_path: Path) -> None:
    source, _, _ = _sources(tmp_path)

    loaded = load_exact_dataset_snapshot(
        tmp_path,
        source.dataset_id,
        snapshot_id=source.snapshot_id,
    )

    assert loaded.dataset_id == source.dataset_id
    assert loaded.snapshot_id == source.snapshot_id
    assert loaded.provider_id == "eastmoney"
    assert loaded.instrument_id == "600000.SSE"
    assert loaded.frequency == "1d"
    assert len(loaded.bars) == 4


def test_build_daily_panel_is_repeatable_and_preserves_missing_stock_bars(
    tmp_path: Path,
) -> None:
    first_source, second_source, benchmark = _sources(tmp_path)
    sessions = tuple(
        make_bar(day=day).event_time for day in (24, 25, 26, 27)
    )
    universe = _Universe(
        members_by_time={
            sessions[0]: frozenset({"600000.SSE", "000001.SZSE"}),
            sessions[1]: frozenset({"600000.SSE", "000001.SZSE"}),
            sessions[2]: frozenset({"600000.SSE"}),
        }
    )

    first = build_exact_eastmoney_daily_panel(
        data_root=tmp_path,
        sources=(second_source, first_source),
        benchmark=benchmark,
        universe=universe,
    )
    second = build_exact_eastmoney_daily_panel(
        data_root=tmp_path,
        sources=(first_source, second_source),
        benchmark=benchmark,
        universe=universe,
    )

    assert first.content_digest == second.content_digest
    assert first.source_digest == second.source_digest
    assert first.sessions == sessions
    assert first.eligible_by_session[sessions[0]] == frozenset(
        {"600000.SSE", "000001.SZSE"}
    )
    assert sessions[1] not in first.instrument_bars["000001.SZSE"]
    assert first.eligible_by_session[sessions[3]] == frozenset()
    assert set(first.benchmark_bars) == set(sessions)


def test_daily_panel_rejects_missing_member_source(tmp_path: Path) -> None:
    first_source, _, benchmark = _sources(tmp_path)
    session = make_bar(day=24).event_time
    with pytest.raises(ValueError, match="without exact sources"):
        build_exact_eastmoney_daily_panel(
            data_root=tmp_path,
            sources=(first_source,),
            benchmark=benchmark,
            universe=_Universe(
                members_by_time={session: frozenset({"600000.SSE", "MISSING.SSE"})}
            ),
        )


def test_daily_panel_rejects_non_eastmoney_or_latest_source(tmp_path: Path) -> None:
    fixture = _publish(
        tmp_path,
        "cn-equity-fixture-daily",
        "600000.SSE",
        provider={"id": "fixture", "interface": "csv", "version": "1"},
    )
    benchmark = _publish(tmp_path, "cn-index-benchmark-daily", "000985.SSE")
    session = make_bar(day=24).event_time
    universe = _Universe(members_by_time={session: frozenset({"600000.SSE"})})
    with pytest.raises(ValueError, match="Eastmoney"):
        build_exact_eastmoney_daily_panel(
            data_root=tmp_path,
            sources=(fixture,),
            benchmark=benchmark,
            universe=universe,
        )
    with pytest.raises(ValueError, match="snapshot_id"):
        DailyPanelSource(
            dataset_id="cn-equity-latest-daily",
            instrument_id="600000.SSE",
            snapshot_id="latest",
        )


def test_exact_loader_detects_tampered_snapshot_file(tmp_path: Path) -> None:
    source, _, _ = _sources(tmp_path)
    snapshot = (
        tmp_path
        / "datasets"
        / source.dataset_id
        / "snapshots"
        / source.snapshot_id
    )
    part = next(snapshot.rglob("*.parquet"))
    part.write_bytes(part.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="file digest"):
        load_exact_dataset_snapshot(
            tmp_path,
            source.dataset_id,
            snapshot_id=source.snapshot_id,
        )

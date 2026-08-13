"""Exact Eastmoney daily panels with dynamic historical membership."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from astraquant_data.market_bars import MarketBar
from astraquant_data.research_store import ExactDatasetSnapshot, load_exact_dataset_snapshot
from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

_DATASET_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")


class HistoricalUniverseLike(Protocol):
    @property
    def members_by_time(self) -> Mapping[datetime, frozenset[str]]: ...

    @property
    def snapshot_digest(self) -> str: ...


@dataclass(frozen=True, slots=True)
class DailyPanelSource:
    dataset_id: str
    instrument_id: str
    snapshot_id: str

    def __post_init__(self) -> None:
        if not _DATASET_ID.fullmatch(self.dataset_id):
            raise ValueError("dataset_id must be canonical")
        instrument_id = self.instrument_id.strip()
        if not instrument_id:
            raise ValueError("instrument_id must not be empty")
        object.__setattr__(self, "instrument_id", instrument_id)
        exact = self.snapshot_id.removeprefix("sha256:")
        if (
            len(exact) != 64
            or any(character not in "0123456789abcdef" for character in exact)
            or set(exact) == {"0"}
        ):
            raise ValueError("snapshot_id must be an exact non-sentinel SHA-256 identity")
        object.__setattr__(self, "snapshot_id", exact)


@dataclass(frozen=True, slots=True)
class ExactDailyPanel:
    sessions: tuple[datetime, ...]
    instrument_bars: Mapping[str, Mapping[datetime, MarketBar]]
    benchmark_bars: Mapping[datetime, MarketBar]
    eligible_by_session: Mapping[datetime, frozenset[str]]
    universe_snapshot_digest: str
    source_digest: str
    content_digest: str


def build_exact_eastmoney_daily_panel(
    *,
    data_root: Path,
    sources: Sequence[DailyPanelSource],
    benchmark: DailyPanelSource,
    universe: HistoricalUniverseLike,
) -> ExactDailyPanel:
    """Load exact daily series and align them without price forward filling."""

    root = data_root
    exact_sources = tuple(sorted(sources, key=lambda source: source.instrument_id))
    if not exact_sources:
        raise ValueError("daily panel sources must not be empty")
    if len({source.instrument_id for source in exact_sources}) != len(exact_sources):
        raise ValueError("daily panel instrument sources must be unique")
    if len({source.dataset_id for source in exact_sources}) != len(exact_sources):
        raise ValueError("daily panel dataset sources must be unique")

    loaded_benchmark = load_exact_dataset_snapshot(
        root,
        benchmark.dataset_id,
        snapshot_id=benchmark.snapshot_id,
    )
    _validate_loaded(benchmark, loaded_benchmark)
    sessions = tuple(bar.timestamp for bar in loaded_benchmark.bars)
    benchmark_bars = {bar.timestamp: bar for bar in loaded_benchmark.bars}

    instrument_bars: dict[str, Mapping[datetime, MarketBar]] = {}
    source_values: list[dict[str, str]] = []
    for source in exact_sources:
        loaded = load_exact_dataset_snapshot(
            root,
            source.dataset_id,
            snapshot_id=source.snapshot_id,
        )
        _validate_loaded(source, loaded)
        bars = {
            bar.timestamp: bar for bar in loaded.bars if bar.timestamp in benchmark_bars
        }
        instrument_bars[source.instrument_id] = MappingProxyType(bars)
        source_values.append(
            {
                "dataset_id": source.dataset_id,
                "instrument_id": source.instrument_id,
                "snapshot_id": source.snapshot_id,
            }
        )

    universe_digest = validate_digest(
        "universe snapshot_digest",
        universe.snapshot_digest,
    )
    known = set(instrument_bars)
    members_by_time = dict(universe.members_by_time)
    if not set(members_by_time).issubset(benchmark_bars):
        raise ValueError("universe decisions must belong to benchmark sessions")
    unknown = set().union(*members_by_time.values()) - known if members_by_time else set()
    if unknown:
        raise ValueError("universe contains instruments without exact sources")
    eligible_by_session = {
        session: frozenset(members_by_time.get(session, frozenset())) for session in sessions
    }
    source_digest = _digest(
        {
            "benchmark": {
                "dataset_id": benchmark.dataset_id,
                "instrument_id": benchmark.instrument_id,
                "snapshot_id": benchmark.snapshot_id,
            },
            "sources": source_values,
        }
    )
    content_digest = _digest(
        {
            "schema_version": "astraquant.exact-daily-panel/v1",
            "sessions": [session.isoformat() for session in sessions],
            "source_digest": source_digest,
            "universe_snapshot_digest": universe_digest,
        }
    )
    return ExactDailyPanel(
        sessions=sessions,
        instrument_bars=MappingProxyType(instrument_bars),
        benchmark_bars=MappingProxyType(benchmark_bars),
        eligible_by_session=MappingProxyType(eligible_by_session),
        universe_snapshot_digest=universe_digest,
        source_digest=source_digest,
        content_digest=content_digest,
    )


def _validate_loaded(source: DailyPanelSource, loaded: ExactDatasetSnapshot) -> None:
    if loaded.provider_id != "eastmoney":
        raise ValueError("daily panel inputs must be Eastmoney snapshots")
    if loaded.instrument_id != source.instrument_id:
        raise ValueError("daily panel source instrument identity mismatch")
    if loaded.frequency != "1d":
        raise ValueError("daily panel source frequency must be 1d")
    if loaded.adjustment != "none":
        raise ValueError("daily panel raw source adjustment must be none")


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

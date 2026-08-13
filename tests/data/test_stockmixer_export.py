from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from astraquant_data.exports.stockmixer import (
    StockMixerExport,
    StockMixerSource,
    UniverseMembership,
    export_stockmixer_request,
)
from astraquant_data.market_bars import MarketBar
from astraquant_quant.baseline_matrix import WalkForwardFold
from astraquant_quant.panel_research import (
    PanelDataset,
    PanelInstrumentData,
    build_panel,
)

_START = datetime(2026, 8, 3, 7, tzinfo=UTC)
_TIMES = tuple(_START + timedelta(days=index) for index in range(6))


def _bar(timestamp: datetime, offset: Decimal, index: int) -> MarketBar:
    close = Decimal("10") + offset + Decimal(index) / Decimal("10")
    return MarketBar(
        timestamp=timestamp,
        open=close - Decimal("0.05"),
        high=close + Decimal("0.10"),
        low=close - Decimal("0.10"),
        close=close,
        volume=Decimal("100000") + index,
        turnover=(Decimal("100000") + index) * close,
    )


def _instrument(
    instrument_id: str,
    offset: Decimal,
    times: tuple[datetime, ...],
) -> PanelInstrumentData:
    bars = tuple(_bar(timestamp, offset, index) for index, timestamp in enumerate(times))
    return PanelInstrumentData(
        instrument_id=instrument_id,
        rows=tuple(
            {
                "future_return": float(Decimal(index + 1) / Decimal("1000")),
            }
            for index in range(len(bars))
        ),
        raw_bars=bars,
        row_bar_indices=tuple(range(len(bars))),
    )


def _panel() -> PanelDataset:
    return build_panel(
        (
            _instrument("AAA.SSE", Decimal("0"), _TIMES),
            _instrument("BBB.SSE", Decimal("1"), _TIMES[:-1]),
        )
    )


def _fold(panel: PanelDataset) -> WalkForwardFold:
    return WalkForwardFold(
        fold_id="fold-01",
        train_indices=tuple(
            index
            for index, observation in enumerate(panel.observations)
            if observation.timestamp <= _TIMES[3]
        ),
        test_indices=tuple(
            index
            for index, observation in enumerate(panel.observations)
            if observation.timestamp >= _TIMES[4]
        ),
    )


def _sources() -> tuple[StockMixerSource, ...]:
    return (
        StockMixerSource("dataset-aaa", "AAA.SSE", f"sha256:{'a' * 64}"),
        StockMixerSource("dataset-bbb", "BBB.SSE", f"sha256:{'b' * 64}"),
    )


def _universe() -> UniverseMembership:
    return UniverseMembership(
        universe_id="declared-two-stock-panel",
        universe_snapshot_id=f"sha256:{'c' * 64}",
        members_by_time={timestamp: frozenset({"AAA.SSE", "BBB.SSE"}) for timestamp in _TIMES},
    )


def _export(output_root: Path, *, panel: PanelDataset | None = None) -> StockMixerExport:
    exact_panel = panel or _panel()
    return export_stockmixer_request(
        output_root=output_root,
        panel=exact_panel,
        folds=(_fold(exact_panel),),
        sources=_sources(),
        universe=_universe(),
        lookback=3,
        label_name="future_return",
    )


def test_exports_repeatable_time_aligned_panel_with_explicit_missing_masks(
    tmp_path: Path,
) -> None:
    first = _export(tmp_path / "first")
    second = _export(tmp_path / "second")

    first_request = json.loads(first.request_path.read_text(encoding="utf-8"))
    second_request = json.loads(second.request_path.read_text(encoding="utf-8"))
    rows = pq.read_table(first.panel_path).to_pylist()

    assert first.content_digest == second.content_digest
    assert first_request == second_request
    assert first.panel_path.read_bytes() == second.panel_path.read_bytes()
    assert first.sample_count == 4
    assert len(rows) == 24
    assert first_request["content_digest"] == first.content_digest
    assert first_request["input_columns"] == ["open", "high", "low", "close", "volume"]
    assert first_request["lookback"] == 3
    assert first_request["universe"]["snapshot_id"] == f"sha256:{'c' * 64}"
    assert [
        (row["fold_id"], row["decision_time"], row["instrument_id"], row["sequence_index"])
        for row in rows
    ] == sorted(
        (
            row["fold_id"],
            row["decision_time"],
            row["instrument_id"],
            row["sequence_index"],
        )
        for row in rows
    )
    assert all(
        row["event_time"] is None or row["event_time"] <= row["decision_time"]
        for row in rows
    )

    missing = next(
        row
        for row in rows
        if row["instrument_id"] == "BBB.SSE"
        and row["decision_time"] == _TIMES[5]
        and row["sequence_index"] == 2
    )
    assert missing["presence_mask"] is True
    assert missing["tradable_mask"] is False
    assert missing["label_mask"] is False
    assert missing["feature_mask"] is False
    assert missing["event_time"] is None
    assert all(
        missing[name] == 0.0 for name in ("open", "high", "low", "close", "volume")
    )
    prior = [
        row
        for row in rows
        if row["instrument_id"] == "BBB.SSE" and row["decision_time"] == _TIMES[5]
    ]
    assert [row["feature_mask"] for row in prior] == [True, True, False]


def test_rejects_unsealed_sources_existing_output_and_incomplete_universe(
    tmp_path: Path,
) -> None:
    panel = _panel()
    with pytest.raises(ValueError, match="source snapshot"):
        export_stockmixer_request(
            output_root=tmp_path / "latest",
            panel=panel,
            folds=(_fold(panel),),
            sources=(replace(_sources()[0], source_snapshot_id="latest"), _sources()[1]),
            universe=_universe(),
            lookback=3,
            label_name="future_return",
        )

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        _export(existing)

    incomplete = replace(
        _universe(),
        members_by_time={timestamp: frozenset({"AAA.SSE"}) for timestamp in _TIMES},
    )
    with pytest.raises(ValueError, match="never includes panel instruments"):
        export_stockmixer_request(
            output_root=tmp_path / "incomplete-universe",
            panel=panel,
            folds=(_fold(panel),),
            sources=_sources(),
            universe=incomplete,
            lookback=3,
            label_name="future_return",
        )


def test_rejects_a_timestamp_split_between_train_and_test(tmp_path: Path) -> None:
    panel = _panel()
    shared = tuple(
        index
        for index, observation in enumerate(panel.observations)
        if observation.timestamp == _TIMES[3]
    )
    assert len(shared) == 2
    prior = tuple(
        index
        for index, observation in enumerate(panel.observations)
        if observation.timestamp < _TIMES[3]
    )
    split_fold = WalkForwardFold(
        fold_id="fold-01",
        train_indices=(*prior, shared[0]),
        test_indices=(shared[1], *_fold(panel).test_indices),
    )
    with pytest.raises(ValueError, match="same decision timestamp"):
        export_stockmixer_request(
            output_root=tmp_path / "split",
            panel=panel,
            folds=(split_fold,),
            sources=_sources(),
            universe=_universe(),
            lookback=3,
            label_name="future_return",
        )


def test_rejects_duplicate_sources_and_observation_time_drift(tmp_path: Path) -> None:
    panel = _panel()
    duplicate_sources = (
        _sources()[0],
        replace(_sources()[1], instrument_id="AAA.SSE"),
    )
    with pytest.raises(ValueError, match="sources must match panel instruments"):
        export_stockmixer_request(
            output_root=tmp_path / "duplicate-sources",
            panel=panel,
            folds=(_fold(panel),),
            sources=duplicate_sources,
            universe=_universe(),
            lookback=3,
            label_name="future_return",
        )

    observations = list(panel.observations)
    observations[0] = replace(
        observations[0], timestamp=observations[0].timestamp - timedelta(seconds=1)
    )
    drifted = replace(panel, observations=tuple(observations))
    with pytest.raises(ValueError, match="decision time does not match its bar"):
        export_stockmixer_request(
            output_root=tmp_path / "drifted",
            panel=drifted,
            folds=(_fold(panel),),
            sources=_sources(),
            universe=_universe(),
            lookback=3,
            label_name="future_return",
        )

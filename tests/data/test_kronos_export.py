from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from astraquant_data.exports.kronos import (
    KronosArtifact,
    KronosExport,
    KronosSource,
    export_kronos_request,
)
from astraquant_data.market_bars import MarketBar
from astraquant_quant.baseline_matrix import WalkForwardFold
from astraquant_quant.panel_research import PanelDataset, PanelInstrumentData, build_panel


class _Calendar:
    calendar_snapshot_id = f"sha256:{'c' * 64}"

    def future_times(
        self, *, instrument_id: str, decision_time: datetime, count: int
    ) -> tuple[datetime, ...]:
        assert instrument_id
        return tuple(decision_time + timedelta(minutes=index + 1) for index in range(count))


def _bars(offset: Decimal) -> tuple[MarketBar, ...]:
    morning = datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    times = (
        morning,
        morning + timedelta(minutes=1),
        morning + timedelta(minutes=2),
        morning + timedelta(hours=4),
        morning + timedelta(hours=4, minutes=1),
        morning + timedelta(hours=4, minutes=2),
        morning + timedelta(hours=4, minutes=3),
        morning + timedelta(hours=4, minutes=4),
    )
    return tuple(
        MarketBar(
            timestamp=timestamp,
            open=Decimal("10") + offset + Decimal(index) / 100,
            high=Decimal("10.2") + offset + Decimal(index) / 100,
            low=Decimal("9.8") + offset + Decimal(index) / 100,
            close=Decimal("10.1") + offset + Decimal(index) / 100,
            volume=Decimal("100000") + index,
            turnover=Decimal("1000000") + index,
        )
        for index, timestamp in enumerate(times)
    )


def _panel() -> PanelDataset:
    instruments = []
    for instrument_id, offset in (
        ("159516.SZSE", Decimal("0")),
        ("512800.SSE", Decimal("1")),
    ):
        bars = _bars(offset)
        instruments.append(
            PanelInstrumentData(
                instrument_id=instrument_id,
                rows=tuple({"future_return": 0.0} for _ in bars),
                raw_bars=bars,
                row_bar_indices=tuple(range(len(bars))),
            )
        )
    return build_panel(instruments)


def _sources() -> tuple[KronosSource, ...]:
    return (
        KronosSource(
            dataset_id="cn-equity-159516-szse-1m-none",
            instrument_id="159516.SZSE",
            source_snapshot_id=f"sha256:{'1' * 64}",
        ),
        KronosSource(
            dataset_id="cn-equity-512800-sse-1m-none",
            instrument_id="512800.SSE",
            source_snapshot_id=f"sha256:{'2' * 64}",
        ),
    )


def _artifact(identifier: str, revision: str, path: str, digit: str) -> KronosArtifact:
    return KronosArtifact(
        artifact_id=identifier,
        revision=revision,
        weights_path=path,
        weights_digest=f"sha256:{digit * 64}",
    )


def _export(
    output_root: Path, *, panel: PanelDataset | None = None, context: int = 4
) -> KronosExport:
    exact_panel = panel or _panel()
    fold = WalkForwardFold(
        fold_id="fold-01",
        train_indices=(0, 1, 2, 3),
        test_indices=tuple(range(4, len(exact_panel.rows))),
    )
    return export_kronos_request(
        output_root=output_root,
        panel=exact_panel,
        folds=(fold,),
        sources=_sources(),
        model=_artifact(
            "NeoQuasar/Kronos-base",
            "2b554741eca47781b64468546e77fef3e85130e6",
            "models/kronos-base/model.safetensors",
            "a",
        ),
        tokenizer=_artifact(
            "NeoQuasar/Kronos-Tokenizer-base",
            "0e0117387f39004a9016484a186a908917e22426",
            "models/kronos-tokenizer-base/model.safetensors",
            "b",
        ),
        context_length=context,
        prediction_length=5,
        seed=7,
        temperature=1.0,
        top_k=0,
        top_p=0.9,
        sample_count=5,
        calendar=_Calendar(),
    )


def test_exports_eligible_windows_without_future_leakage_repeatably(tmp_path: Path) -> None:
    first = _export(tmp_path / "first")
    second = _export(tmp_path / "second")

    first_request = json.loads(first.request_path.read_text(encoding="utf-8"))
    second_request = json.loads(second.request_path.read_text(encoding="utf-8"))
    first_rows = pq.read_table(first.windows_path).to_pylist()

    assert first_request == second_request
    assert first.windows_path.read_bytes() == second.windows_path.read_bytes()
    assert first_request["content_digest"] == first.content_digest
    assert first_request["calendar_snapshot_id"] == f"sha256:{'c' * 64}"
    assert all(len(row["forecast_times"]) == 5 for row in first_request["rows"])
    assert len(first_request["rows"]) == 10
    assert first.eligible_row_ids == tuple(range(6, 16))
    assert len(first_rows) == 40
    assert list(first_rows[0]) == [
        "fold_id",
        "row_id",
        "instrument_id",
        "decision_time",
        "sequence_index",
        "event_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in first_rows:
        grouped.setdefault(int(row["row_id"]), []).append(row)
        assert row["event_time"] <= row["decision_time"]
    for values in grouped.values():
        assert [item["sequence_index"] for item in values] == [0, 1, 2, 3]
        assert values[-1]["event_time"] == values[-1]["decision_time"]
    assert any(
        current["event_time"] - previous["event_time"] > timedelta(hours=1)
        for values in grouped.values()
        for previous, current in pairwise(values)
    )


def test_rejects_unsealed_source_existing_output_and_no_eligible_rows(tmp_path: Path) -> None:
    bad_source = replace(_sources()[0], source_snapshot_id="latest")
    with pytest.raises(ValueError, match="snapshot"):
        export_kronos_request(
            output_root=tmp_path / "bad-source",
            panel=_panel(),
            folds=(WalkForwardFold("fold-01", (0, 1), tuple(range(2, 16))),),
            sources=(bad_source, _sources()[1]),
            model=_artifact("NeoQuasar/Kronos-base", "2" * 40, "model", "a"),
            tokenizer=_artifact("NeoQuasar/Kronos-Tokenizer-base", "0" * 39 + "e", "token", "b"),
            context_length=4,
            prediction_length=5,
            seed=7,
            temperature=1.0,
            top_k=0,
            top_p=0.9,
            sample_count=5,
            calendar=_Calendar(),
        )

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        _export(existing)
    with pytest.raises(ValueError, match="eligible"):
        _export(tmp_path / "no-eligible", context=20)


def test_rejects_panel_source_mismatch_and_decision_time_drift(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sources"):
        export_kronos_request(
            output_root=tmp_path / "source-mismatch",
            panel=_panel(),
            folds=(WalkForwardFold("fold-01", (0, 1, 2, 3), tuple(range(4, 16))),),
            sources=(_sources()[0],),
            model=_artifact("NeoQuasar/Kronos-base", "2" * 40, "model", "a"),
            tokenizer=_artifact("NeoQuasar/Kronos-Tokenizer-base", "e" * 40, "token", "b"),
            context_length=4,
            prediction_length=5,
            seed=7,
            temperature=1.0,
            top_k=0,
            top_p=0.9,
            sample_count=5,
            calendar=_Calendar(),
        )

    panel = _panel()
    observations = list(panel.observations)
    observations[6] = replace(
        observations[6], timestamp=observations[6].timestamp - timedelta(seconds=1)
    )
    drifted = replace(panel, observations=tuple(observations))
    with pytest.raises(ValueError, match="decision time"):
        _export(tmp_path / "drifted", panel=drifted)


def test_rejects_artifact_path_escape(tmp_path: Path) -> None:
    panel = _panel()
    with pytest.raises(ValueError, match="weights path"):
        export_kronos_request(
            output_root=tmp_path / "path-escape",
            panel=panel,
            folds=(WalkForwardFold("fold-01", (0, 1, 2, 3), tuple(range(4, 16))),),
            sources=_sources(),
            model=_artifact(
                "NeoQuasar/Kronos-base",
                "2b554741eca47781b64468546e77fef3e85130e6",
                "../model.safetensors",
                "a",
            ),
            tokenizer=_artifact(
                "NeoQuasar/Kronos-Tokenizer-base",
                "0e0117387f39004a9016484a186a908917e22426",
                "models/tokenizer/model.safetensors",
                "b",
            ),
            context_length=4,
            prediction_length=5,
            seed=7,
            temperature=1.0,
            top_k=0,
            top_p=0.9,
            sample_count=5,
            calendar=_Calendar(),
        )


def test_rejects_future_times_that_are_not_strictly_after_decision(tmp_path: Path) -> None:
    class InvalidCalendar(_Calendar):
        def future_times(
            self, *, instrument_id: str, decision_time: datetime, count: int
        ) -> tuple[datetime, ...]:
            return (decision_time,) * count

    panel = _panel()
    with pytest.raises(ValueError, match="forecast times"):
        export_kronos_request(
            output_root=tmp_path / "invalid-calendar",
            panel=panel,
            folds=(WalkForwardFold("fold-01", (0, 1, 2, 3), tuple(range(4, 16))),),
            sources=_sources(),
            model=_artifact(
                "NeoQuasar/Kronos-base",
                "2b554741eca47781b64468546e77fef3e85130e6",
                "models/model.safetensors",
                "a",
            ),
            tokenizer=_artifact(
                "NeoQuasar/Kronos-Tokenizer-base",
                "0e0117387f39004a9016484a186a908917e22426",
                "models/tokenizer.safetensors",
                "b",
            ),
            context_length=4,
            prediction_length=5,
            seed=7,
            temperature=1.0,
            top_k=0,
            top_p=0.9,
            sample_count=5,
            calendar=InvalidCalendar(),
        )

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from astraquant_data.exports.stage_b_v2 import export_stage_b_v2_request
from astraquant_data.market_bars import MarketBar
from astraquant_domain import CrossSectionalTaskMatrix
from astraquant_quant.cross_sectional_features import (
    build_cross_sectional_context_features,
)
from astraquant_quant.cross_sectional_labels import (
    DailyCrossSectionalPanel,
    build_daily_cross_sectional_labels,
)


@dataclass(frozen=True, slots=True)
class _Panel:
    sessions: tuple[datetime, ...]
    instrument_bars: dict[str, dict[datetime, MarketBar]]
    benchmark_bars: dict[datetime, MarketBar]
    eligible_by_session: dict[datetime, frozenset[str]]
    content_digest: str = f"sha256:{'a' * 64}"
    source_digest: str = f"sha256:{'b' * 64}"
    universe_snapshot_digest: str = f"sha256:{'c' * 64}"


def _bar(timestamp: datetime, price: Decimal) -> MarketBar:
    return MarketBar(
        timestamp=timestamp,
        open=price,
        high=price * Decimal("1.02"),
        low=price * Decimal("0.98"),
        close=price * Decimal("1.01"),
        volume=Decimal("100000"),
        turnover=price * Decimal("100000"),
    )


def _panel() -> _Panel:
    start = datetime(2020, 1, 2, 7, tzinfo=UTC)
    sessions = tuple(start + timedelta(days=index) for index in range(35))
    instruments = ("A.SSE", "B.SSE", "C.SSE")
    instrument_bars = {
        instrument: {
            session: _bar(
                session,
                Decimal("10") + instrument_index + Decimal(session_index) / 10,
            )
            for session_index, session in enumerate(sessions)
        }
        for instrument_index, instrument in enumerate(instruments)
    }
    return _Panel(
        sessions=sessions,
        instrument_bars=instrument_bars,
        benchmark_bars={
            session: _bar(session, Decimal("100") + Decimal(index) / 10)
            for index, session in enumerate(sessions)
        },
        eligible_by_session={session: frozenset(instruments) for session in sessions},
    )


def _features_and_labels(panel: _Panel):  # type: ignore[no-untyped-def]
    logical = DailyCrossSectionalPanel(
        sessions=panel.sessions,
        instrument_bars=panel.instrument_bars,
        benchmark_bars=panel.benchmark_bars,
        eligible_by_session=panel.eligible_by_session,
    )
    return (
        build_cross_sectional_context_features(logical),
        build_daily_cross_sectional_labels(
            logical,
            CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI"),
        ),
    )


def test_stage_b_v2_export_is_repeatable_and_declares_pinned_alpha158(
    tmp_path: Path,
) -> None:
    panel = _panel()
    features, labels = _features_and_labels(panel)

    first = export_stage_b_v2_request(
        output_root=tmp_path / "first",
        panel=panel,
        context_rows=features,
        label_rows=labels,
        task_matrix=CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI"),
    )
    second = export_stage_b_v2_request(
        output_root=tmp_path / "second",
        panel=panel,
        context_rows=features,
        label_rows=labels,
        task_matrix=CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI"),
    )

    assert first.content_digest == second.content_digest
    assert first.request_path.read_bytes() == second.request_path.read_bytes()
    assert first.bars_path.read_bytes() == second.bars_path.read_bytes()
    assert first.context_path.read_bytes() == second.context_path.read_bytes()
    assert first.labels_path.read_bytes() == second.labels_path.read_bytes()
    request = json.loads(first.request_path.read_text(encoding="utf-8"))
    assert request["alpha158"]["feature_count"] == 158
    assert request["alpha158"]["materializer"] == "PINNED_QLIB_RUNNER"
    assert request["task_digest"] == CrossSectionalTaskMatrix.stage_b_v2_daily(
        "000985.CSI"
    ).task_digest
    assert pq.read_table(first.context_path).num_rows == len(features)
    assert pq.read_table(first.labels_path).num_rows == len(labels)


def test_stage_b_v2_export_rejects_unsealed_or_misaligned_inputs(tmp_path: Path) -> None:
    panel = _panel()
    features, labels = _features_and_labels(panel)
    with pytest.raises(ValueError, match="panel content_digest"):
        export_stage_b_v2_request(
            output_root=tmp_path / "unsealed",
            panel=replace(panel, content_digest="latest"),
            context_rows=features,
            label_rows=labels,
            task_matrix=CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI"),
        )
    bad_feature = replace(features[0], instrument_id="UNKNOWN.SSE")
    with pytest.raises(ValueError, match="context"):
        export_stage_b_v2_request(
            output_root=tmp_path / "misaligned",
            panel=panel,
            context_rows=(bad_feature, *features[1:]),
            label_rows=labels,
            task_matrix=CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI"),
        )

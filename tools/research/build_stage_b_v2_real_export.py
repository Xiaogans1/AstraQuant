"""Build Stage B v2 context/labels from exact real Eastmoney bootstrap snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from astraquant_data.daily_panel import DailyPanelSource, build_exact_eastmoney_daily_panel
from astraquant_data.exports.stage_b_v2 import export_stage_b_v2_request
from astraquant_data.research_store import load_exact_dataset_snapshot
from astraquant_domain import (
    CrossSectionalTaskMatrix,
    HistoricalUniversePolicy,
)
from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.cross_sectional_features import build_cross_sectional_context_features
from astraquant_quant.cross_sectional_labels import (
    DailyCrossSectionalPanel,
    build_daily_cross_sectional_labels,
)
from astraquant_quant.historical_universe import (
    DailyInstrumentStatus,
    DailyUniverseInstrument,
    build_historical_universe,
)

_BOOTSTRAP_SCHEMA = "astraquant.stage-b-v2-eastmoney-bootstrap/v1"
_SELECTION_SCHEMA = "astraquant.stage-b-v2-eastmoney-selection/v1"
_BUILD_SCHEMA = "astraquant.stage-b-v2-real-export-build/v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bootstrap_root", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--universe-size", type=int, default=300)
    parser.add_argument("--minimum-size", type=int, default=300)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        policy = HistoricalUniversePolicy(
            schema_version="astraquant.historical-universe-policy/v1",
            liquidity_lookback_sessions=60,
            minimum_history_sessions=120,
            target_size=arguments.universe_size,
            minimum_size=arguments.minimum_size,
            maximum_size=800,
            minimum_price=Decimal("2"),
            minimum_observation_ratio=Decimal("0.95"),
            exclude_special_treatment=True,
            common_a_share_only=True,
        )
        result = build_stage_b_v2_real_export(
            bootstrap_root=arguments.bootstrap_root,
            output_root=arguments.output_root,
            universe_policy=policy,
        )
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Stage B v2 real export failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "content_digest": result["content_digest"],
                "instrument_count": result["instrument_count"],
                "context_row_count": result["context_row_count"],
                "label_row_count": result["label_row_count"],
            },
            separators=(",", ":"),
        )
    )
    return 0


def build_stage_b_v2_real_export(
    *,
    bootstrap_root: Path,
    output_root: Path,
    universe_policy: HistoricalUniversePolicy,
) -> dict[str, Any]:
    """Build a real-API research export with explicitly limited status fidelity."""

    root = bootstrap_root.resolve()
    bootstrap = _read_verified(root / "bootstrap.json", _BOOTSTRAP_SCHEMA)
    selection = _read_verified(root / "selection.json", _SELECTION_SCHEMA)
    source_values = bootstrap.get("sources")
    if not isinstance(source_values, list) or not source_values:
        raise ValueError("real bootstrap sources are missing")
    data_root = root / "data"
    selection_candidates = selection.get("candidates")
    if not isinstance(selection_candidates, list):
        raise ValueError("real bootstrap selection candidates are missing")
    lifecycle = {
        str(value["instrument_id"]): value
        for value in selection_candidates
        if isinstance(value, dict) and isinstance(value.get("instrument_id"), str)
    }
    sources: list[DailyPanelSource] = []
    instruments: list[DailyUniverseInstrument] = []
    loaded_by_id = {}
    selection_digest = str(selection["content_digest"])
    for value in source_values:
        if not isinstance(value, dict):
            raise ValueError("real bootstrap source schema mismatch")
        dataset_id = str(value["dataset_id"])
        instrument_id = str(value["instrument_id"])
        snapshot_id = str(value["snapshot_id"])
        source = DailyPanelSource(
            dataset_id=dataset_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        loaded = load_exact_dataset_snapshot(
            data_root,
            dataset_id,
            snapshot_id=source.snapshot_id,
        )
        lifecycle_value = lifecycle.get(instrument_id)
        if lifecycle_value is None:
            raise ValueError("real bootstrap lifecycle coverage is incomplete")
        listed_on = datetime.fromisoformat(str(lifecycle_value["listed_on"])).date()
        raw_delisted = lifecycle_value.get("delisted_on")
        delisted_on = (
            None if raw_delisted is None else datetime.fromisoformat(str(raw_delisted)).date()
        )
        bars = {bar.timestamp: bar for bar in loaded.bars}
        sources.append(source)
        loaded_by_id[instrument_id] = loaded
        instruments.append(
            DailyUniverseInstrument(
                instrument_id=instrument_id,
                source_snapshot_id=f"sha256:{source.snapshot_id}",
                lifecycle_evidence_digest=selection_digest,
                listed_on=listed_on,
                delisted_on=delisted_on,
                common_a_share=True,
                bars=bars,
            )
        )
    benchmark_value = bootstrap.get("benchmark")
    if not isinstance(benchmark_value, dict):
        raise ValueError("real bootstrap benchmark is missing")
    benchmark = DailyPanelSource(
        dataset_id=str(benchmark_value["dataset_id"]),
        instrument_id=str(benchmark_value["instrument_id"]),
        snapshot_id=str(benchmark_value["snapshot_id"]),
    )
    loaded_benchmark = load_exact_dataset_snapshot(
        data_root,
        benchmark.dataset_id,
        snapshot_id=benchmark.snapshot_id,
    )
    sessions = tuple(bar.timestamp for bar in loaded_benchmark.bars)
    decision_sessions = sessions[universe_policy.minimum_history_sessions - 1 :]
    statuses = {
        session: {
            instrument.instrument_id: DailyInstrumentStatus(
                tradable=(session in instrument.bars and instrument.bars[session].volume > 0),
                special_treatment=False,
                evidence_digest=f"sha256:{loaded_by_id[instrument.instrument_id].snapshot_id}",
            )
            for instrument in instruments
            if instrument.active_on(session)
        }
        for session in decision_sessions
    }
    universe = build_historical_universe(
        sessions=sessions,
        instruments=instruments,
        status_by_session=statuses,
        policy=universe_policy,
    )
    panel = build_exact_eastmoney_daily_panel(
        data_root=data_root,
        sources=sources,
        benchmark=benchmark,
        universe=universe,
    )
    task_matrix = CrossSectionalTaskMatrix.stage_b_v2_daily(benchmark.instrument_id)
    context = build_cross_sectional_context_features(panel)
    labels = build_daily_cross_sectional_labels(
        DailyCrossSectionalPanel(
            sessions=panel.sessions,
            instrument_bars=panel.instrument_bars,
            benchmark_bars=panel.benchmark_bars,
            eligible_by_session=panel.eligible_by_session,
        ),
        task_matrix,
    )
    exported = export_stage_b_v2_request(
        output_root=output_root,
        panel=panel,
        context_rows=context,
        label_rows=labels,
        task_matrix=task_matrix,
    )
    body: dict[str, Any] = {
        "schema_version": _BUILD_SCHEMA,
        "run_class": "EXPLORATORY_REAL_API_CURRENT_STATUS",
        "bootstrap_digest": bootstrap["content_digest"],
        "selection_digest": selection_digest,
        "universe_policy_digest": universe_policy.policy_digest,
        "universe_snapshot_digest": universe.snapshot_digest,
        "panel_content_digest": panel.content_digest,
        "content_digest": exported.content_digest,
        "instrument_count": len(sources),
        "session_count": len(sessions),
        "membership_session_count": len(universe.members_by_time),
        "context_row_count": len(context),
        "label_row_count": len(labels),
        "status_fidelity": "CURRENT_NAME_AND_OBSERVED_BAR_ONLY",
    }
    (output_root / "build.json").write_bytes(canonical_json_bytes(body) + b"\n")
    return body


def _read_verified(path: Path, schema: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != schema:
        raise ValueError(f"real export artifact schema mismatch: {path.name}")
    body = {key: item for key, item in value.items() if key != "content_digest"}
    expected = f"sha256:{hashlib.sha256(canonical_json_bytes(body)).hexdigest()}"
    if value.get("content_digest") != expected:
        raise ValueError(f"real export artifact digest mismatch: {path.name}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

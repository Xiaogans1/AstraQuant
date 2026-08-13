"""Immutable Stage B v2 raw-bar, context and multi-horizon label export."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.exports.qlib import QLIB_UPSTREAM_COMMIT
from astraquant_data.exports.qlib_alpha158 import ALPHA158_CONFIG_DIGEST
from astraquant_data.market_bars import MarketBar
from astraquant_domain import CrossSectionalTaskMatrix
from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

_SCHEMA = "astraquant.stage-b-v2-request/v1"


class PanelLike(Protocol):
    @property
    def sessions(self) -> Sequence[datetime]: ...

    @property
    def instrument_bars(self) -> Mapping[str, Mapping[datetime, MarketBar]]: ...

    @property
    def benchmark_bars(self) -> Mapping[datetime, MarketBar]: ...

    @property
    def eligible_by_session(self) -> Mapping[datetime, frozenset[str]]: ...

    @property
    def content_digest(self) -> str: ...

    @property
    def source_digest(self) -> str: ...

    @property
    def universe_snapshot_digest(self) -> str: ...


class ContextRowLike(Protocol):
    @property
    def decision_time(self) -> datetime: ...

    @property
    def instrument_id(self) -> str: ...

    @property
    def values(self) -> Mapping[str, float]: ...


class LabelRowLike(Protocol):
    @property
    def decision_time(self) -> datetime: ...

    @property
    def instrument_id(self) -> str: ...

    @property
    def horizon_sessions(self) -> int: ...

    @property
    def entry_time(self) -> datetime: ...

    @property
    def exit_time(self) -> datetime: ...

    @property
    def raw_return(self) -> Decimal: ...

    @property
    def benchmark_return(self) -> Decimal: ...

    @property
    def market_excess_return(self) -> Decimal: ...

    @property
    def cross_sectional_rank(self) -> Decimal: ...

    @property
    def downside_risk(self) -> Decimal: ...

    @property
    def training_eligible(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class StageBV2Export:
    content_digest: str
    request_path: Path
    bars_path: Path
    context_path: Path
    labels_path: Path


def export_stage_b_v2_request(
    *,
    output_root: Path,
    panel: PanelLike,
    context_rows: Sequence[ContextRowLike],
    label_rows: Sequence[LabelRowLike],
    task_matrix: CrossSectionalTaskMatrix,
) -> StageBV2Export:
    """Seal raw inputs for official Alpha158 materialization and baseline training."""

    root = output_root.resolve()
    if root.exists():
        raise ValueError("Stage B v2 output_root must not already exist")
    panel_digest = validate_digest("panel content_digest", panel.content_digest)
    source_digest = validate_digest("panel source_digest", panel.source_digest)
    universe_digest = validate_digest(
        "panel universe_snapshot_digest",
        panel.universe_snapshot_digest,
    )
    sessions = tuple(panel.sessions)
    if not sessions or sessions != tuple(sorted(set(sessions))):
        raise ValueError("Stage B v2 panel sessions must be canonical")
    known = set(panel.instrument_bars)
    if not known:
        raise ValueError("Stage B v2 panel instruments must not be empty")
    context = tuple(
        sorted(context_rows, key=lambda row: (row.decision_time, row.instrument_id))
    )
    labels = tuple(
        sorted(
            label_rows,
            key=lambda row: (
                row.decision_time,
                row.horizon_sessions,
                row.instrument_id,
            ),
        )
    )
    context_columns = _validate_context(context, panel, known)
    _validate_labels(labels, panel, known, task_matrix)
    label_identities = {(row.decision_time, row.instrument_id) for row in labels}
    if not any((row.decision_time, row.instrument_id) in label_identities for row in context):
        raise ValueError("Stage B v2 context and labels have no trainable overlap")

    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=root.parent,
        prefix=f".{root.name}-staging-",
        ignore_cleanup_errors=True,
    ) as staging_name:
        staging = Path(staging_name)
        bars_path = staging / "bars.parquet"
        context_path = staging / "context.parquet"
        labels_path = staging / "labels.parquet"
        pq.write_table(
            _bars_table(panel, task_matrix),
            bars_path,
            compression="zstd",
            version="2.6",
        )
        pq.write_table(
            _context_table(context, context_columns),
            context_path,
            compression="zstd",
            version="2.6",
        )
        pq.write_table(_labels_table(labels), labels_path, compression="zstd", version="2.6")
        body: dict[str, object] = {
            "schema_version": _SCHEMA,
            "panel_content_digest": panel_digest,
            "source_digest": source_digest,
            "universe_snapshot_digest": universe_digest,
            "task_digest": task_matrix.task_digest,
            "horizons": list(task_matrix.horizons),
            "context_feature_columns": list(context_columns),
            "alpha158": {
                "config_digest": ALPHA158_CONFIG_DIGEST,
                "feature_count": 158,
                "materializer": "PINNED_QLIB_RUNNER",
                "upstream_commit": QLIB_UPSTREAM_COMMIT,
            },
            "bars_file": {"path": "bars.parquet", "digest": _file_digest(bars_path)},
            "context_file": {
                "path": "context.parquet",
                "digest": _file_digest(context_path),
            },
            "labels_file": {
                "path": "labels.parquet",
                "digest": _file_digest(labels_path),
            },
            "session_count": len(sessions),
            "instrument_count": len(known),
            "context_row_count": len(context),
            "label_row_count": len(labels),
        }
        content_digest = _digest(body)
        (staging / "request.json").write_text(
            json.dumps(
                {"content_digest": content_digest, **body},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        staging.replace(root)
    return StageBV2Export(
        content_digest=content_digest,
        request_path=root / "request.json",
        bars_path=root / "bars.parquet",
        context_path=root / "context.parquet",
        labels_path=root / "labels.parquet",
    )


def _validate_context(
    rows: tuple[ContextRowLike, ...],
    panel: PanelLike,
    known: set[str],
) -> tuple[str, ...]:
    if not rows:
        raise ValueError("Stage B v2 context rows must not be empty")
    columns = tuple(rows[0].values)
    identities: set[tuple[datetime, str]] = set()
    for row in rows:
        identity = (row.decision_time, row.instrument_id)
        if (
            row.instrument_id not in known
            or row.decision_time not in panel.eligible_by_session
            or row.instrument_id not in panel.eligible_by_session[row.decision_time]
            or tuple(row.values) != columns
            or identity in identities
        ):
            raise ValueError("Stage B v2 context rows are not aligned with the panel")
        identities.add(identity)
    return columns


def _validate_labels(
    rows: tuple[LabelRowLike, ...],
    panel: PanelLike,
    known: set[str],
    task_matrix: CrossSectionalTaskMatrix,
) -> None:
    if not rows:
        raise ValueError("Stage B v2 label rows must not be empty")
    identities: set[tuple[datetime, int, str]] = set()
    for row in rows:
        identity = (row.decision_time, row.horizon_sessions, row.instrument_id)
        if (
            row.instrument_id not in known
            or row.decision_time not in panel.eligible_by_session
            or row.instrument_id not in panel.eligible_by_session[row.decision_time]
            or row.horizon_sessions not in task_matrix.horizons
            or identity in identities
        ):
            raise ValueError("Stage B v2 label rows are not aligned with the panel")
        identities.add(identity)


def _bars_table(panel: PanelLike, task_matrix: CrossSectionalTaskMatrix) -> pa.Table:
    rows = []
    for instrument_id in sorted(panel.instrument_bars):
        for _timestamp, bar in sorted(panel.instrument_bars[instrument_id].items()):
            rows.append(_bar_value(instrument_id, bar, benchmark=False))
    for _timestamp, bar in sorted(panel.benchmark_bars.items()):
        rows.append(_bar_value(task_matrix.benchmark_instrument_id, bar, benchmark=True))
    rows.sort(key=lambda row: (row["timestamp"], row["instrument_id"]))
    return pa.Table.from_pylist(rows, schema=_bars_schema())


def _bar_value(instrument_id: str, bar: MarketBar, *, benchmark: bool) -> dict[str, object]:
    return {
        "timestamp": bar.timestamp,
        "instrument_id": instrument_id,
        "benchmark": benchmark,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(bar.volume),
        "turnover": float(bar.turnover),
    }


def _bars_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("benchmark", pa.bool_(), nullable=False),
            *(
                pa.field(name, pa.float64(), nullable=False)
                for name in ("open", "high", "low", "close", "volume", "turnover")
            ),
        ],
        metadata={b"schema_version": _SCHEMA.encode()},
    )


def _context_table(
    rows: tuple[ContextRowLike, ...],
    columns: tuple[str, ...],
) -> pa.Table:
    schema = pa.schema(
        [
            pa.field("decision_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("instrument_id", pa.string(), nullable=False),
            *(pa.field(name, pa.float64(), nullable=False) for name in columns),
        ],
        metadata={b"schema_version": _SCHEMA.encode()},
    )
    return pa.Table.from_pylist(
        [
            {
                "decision_time": row.decision_time,
                "instrument_id": row.instrument_id,
                **{name: float(row.values[name]) for name in columns},
            }
            for row in rows
        ],
        schema=schema,
    )


def _labels_table(rows: tuple[LabelRowLike, ...]) -> pa.Table:
    schema = pa.schema(
        [
            pa.field("decision_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("horizon_sessions", pa.int16(), nullable=False),
            pa.field("entry_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("exit_time", pa.timestamp("us", tz="UTC"), nullable=False),
            *(
                pa.field(name, pa.float64(), nullable=False)
                for name in (
                    "raw_return",
                    "benchmark_return",
                    "market_excess_return",
                    "cross_sectional_rank",
                    "downside_risk",
                )
            ),
            pa.field("training_eligible", pa.bool_(), nullable=False),
        ],
        metadata={b"schema_version": _SCHEMA.encode()},
    )
    return pa.Table.from_pylist(
        [
            {
                "decision_time": row.decision_time,
                "instrument_id": row.instrument_id,
                "horizon_sessions": row.horizon_sessions,
                "entry_time": row.entry_time,
                "exit_time": row.exit_time,
                "raw_return": float(row.raw_return),
                "benchmark_return": float(row.benchmark_return),
                "market_excess_return": float(row.market_excess_return),
                "cross_sectional_rank": float(row.cross_sectional_rank),
                "downside_risk": float(row.downside_risk),
                "training_eligible": row.training_eligible,
            }
            for row in rows
        ],
        schema=schema,
    )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

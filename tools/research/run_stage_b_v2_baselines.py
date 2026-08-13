"""Run the deterministic Stage B v2 cross-sectional baseline matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.cross_sectional_baselines import (
    CrossSectionalBaselineResult,
    CrossSectionalBaselineRow,
    CrossSectionalModelKind,
    run_cross_sectional_baseline,
)
from astraquant_quant.cross_sectional_splits import (
    assign_cross_sectional_fold_rows,
    build_cross_sectional_folds,
)

_SOURCE_SCHEMA = "astraquant.stage-b-v2-materialization/v1"
_REPORT_SCHEMA = "astraquant.stage-b-v2-baseline-report/v1"
_LABEL_COLUMNS = {
    "benchmark_return",
    "cross_sectional_rank",
    "downside_risk",
    "entry_time",
    "exit_time",
    "horizon_sessions",
    "instrument_id",
    "market_excess_return",
    "raw_return",
    "row_id",
    "training_eligible",
    "decision_time",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-stage-b-v2-baselines")
    parser.add_argument("materialization_root", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--minimum-fit-sessions", type=int, default=756)
    parser.add_argument("--inner-valid-sessions", type=int, default=120)
    parser.add_argument("--outer-test-sessions", type=int, default=60)
    parser.add_argument("--fold-count", type=int, default=6)
    parser.add_argument("--purge-sessions", type=int, default=11)
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 29, 53])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.output_root.exists():
            raise ValueError("baseline output_root must not already exist")
        manifest, rows = _load_materialization(arguments.materialization_root)
        seeds = _canonical_seeds(arguments.seeds)
        report = _run_matrix(
            manifest=manifest,
            rows=rows,
            seeds=seeds,
            minimum_fit_sessions=arguments.minimum_fit_sessions,
            inner_valid_sessions=arguments.inner_valid_sessions,
            outer_test_sessions=arguments.outer_test_sessions,
            fold_count=arguments.fold_count,
            purge_sessions=arguments.purge_sessions,
        )
        _publish(arguments.output_root, report)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Stage B v2 baseline matrix failed: {error}", file=sys.stderr)
        return 1
    return 0


def _load_materialization(
    root: Path,
) -> tuple[dict[str, Any], tuple[CrossSectionalBaselineRow, ...]]:
    manifest_path = root / "manifest.json"
    manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest_value, dict)
        or manifest_value.get("schema_version") != _SOURCE_SCHEMA
    ):
        raise ValueError("Stage B v2 materialization manifest schema mismatch")
    manifest: dict[str, Any] = manifest_value
    supplied_digest = _digest(
        canonical_json_bytes(
            {key: value for key, value in manifest.items() if key != "content_digest"}
        )
    )
    if manifest.get("content_digest") != supplied_digest:
        raise ValueError("Stage B v2 materialization manifest digest mismatch")
    matrix_file = manifest.get("matrix_file")
    if not isinstance(matrix_file, dict) or matrix_file.get("path") != "matrix.parquet":
        raise ValueError("Stage B v2 materialization matrix file schema mismatch")
    matrix_path = root / "matrix.parquet"
    if not matrix_path.is_file() or matrix_file.get("digest") != _digest(matrix_path.read_bytes()):
        raise ValueError("Stage B v2 materialization matrix digest mismatch")
    feature_columns = manifest.get("feature_columns")
    if (
        not isinstance(feature_columns, list)
        or not feature_columns
        or any(not isinstance(value, str) or not value for value in feature_columns)
        or len(set(feature_columns)) != len(feature_columns)
    ):
        raise ValueError("Stage B v2 feature columns schema mismatch")
    frame = pq.read_table(matrix_path).to_pandas()
    if len(frame) != manifest.get("row_count") or not _LABEL_COLUMNS.issubset(frame.columns):
        raise ValueError("Stage B v2 materialized row schema mismatch")
    if any(column not in frame.columns for column in feature_columns):
        raise ValueError("Stage B v2 materialized feature coverage mismatch")
    rows = tuple(
        CrossSectionalBaselineRow(
            row_id=int(record.row_id),
            decision_time=record.decision_time.to_pydatetime(),
            instrument_id=str(record.instrument_id),
            horizon_sessions=int(record.horizon_sessions),
            features={column: float(getattr(record, column)) for column in feature_columns},
            cross_sectional_rank=float(record.cross_sectional_rank),
            market_excess_return=float(record.market_excess_return),
            training_eligible=bool(record.training_eligible),
        )
        for record in frame.itertuples(index=False)
    )
    if not rows:
        raise ValueError("Stage B v2 materialization has no rows")
    return manifest, rows


def _run_matrix(
    *,
    manifest: dict[str, Any],
    rows: tuple[CrossSectionalBaselineRow, ...],
    seeds: tuple[int, ...],
    minimum_fit_sessions: int,
    inner_valid_sessions: int,
    outer_test_sessions: int,
    fold_count: int,
    purge_sessions: int,
) -> dict[str, Any]:
    horizons = tuple(sorted({row.horizon_sessions for row in rows}))
    trials: list[dict[str, Any]] = []
    horizon_reports: dict[str, Any] = {}
    for horizon in horizons:
        horizon_rows = tuple(row for row in rows if row.horizon_sessions == horizon)
        timeline = tuple(sorted({row.decision_time for row in horizon_rows}))
        folds = build_cross_sectional_folds(
            timeline,
            horizons=horizons,
            minimum_fit_sessions=minimum_fit_sessions,
            inner_valid_sessions=inner_valid_sessions,
            outer_test_sessions=outer_test_sessions,
            fold_count=fold_count,
            purge_sessions=purge_sessions,
        )
        assignments = assign_cross_sectional_fold_rows(horizon_rows, folds)
        model_reports: dict[str, Any] = {}
        for model_kind in sorted(CrossSectionalModelKind, key=lambda value: value.value):
            completed: list[CrossSectionalBaselineResult] = []
            for seed in seeds:
                for assignment in assignments:
                    trial_id = f"h{horizon}-{model_kind.value.lower()}-s{seed}-{assignment.fold_id}"
                    try:
                        result = run_cross_sectional_baseline(
                            horizon_rows,
                            assignment=assignment,
                            model_kind=model_kind,
                            seed=seed,
                        )
                    except (ValueError, RuntimeError) as error:
                        trials.append(
                            {
                                "trial_id": trial_id,
                                "horizon_sessions": horizon,
                                "model": model_kind.value,
                                "seed": seed,
                                "fold_id": assignment.fold_id,
                                "status": "FAILED",
                                "error": str(error),
                            }
                        )
                        continue
                    completed.append(result)
                    trials.append(_trial_value(trial_id, result))
            model_reports[model_kind.value] = _model_summary(
                completed,
                seeds=seeds,
                fold_count=fold_count,
            )
        horizon_reports[str(horizon)] = {"models": model_reports}
    body: dict[str, Any] = {
        "schema_version": _REPORT_SCHEMA,
        "source_materialization_digest": manifest["content_digest"],
        "models": sorted(value.value for value in CrossSectionalModelKind),
        "seeds": list(seeds),
        "horizon_sessions": list(horizons),
        "fold_count": fold_count,
        "fold_policy": {
            "minimum_fit_sessions": minimum_fit_sessions,
            "inner_valid_sessions": inner_valid_sessions,
            "outer_test_sessions": outer_test_sessions,
            "purge_sessions": purge_sessions,
        },
        "trial_count": len(trials),
        "failed_trial_count": sum(item["status"] == "FAILED" for item in trials),
        "trials": trials,
        "horizons": horizon_reports,
    }
    return {"content_digest": _digest(canonical_json_bytes(body)), **body}


def _trial_value(trial_id: str, result: CrossSectionalBaselineResult) -> dict[str, Any]:
    return {
        "trial_id": trial_id,
        "horizon_sessions": result.horizon_sessions,
        "model": result.model_kind.value,
        "seed": result.seed,
        "fold_id": result.fold_id,
        "status": "COMPLETED",
        "fit_count": result.fit_count,
        "inner_valid_count": result.inner_valid_count,
        "outer_test_count": result.outer_test_count,
        "processor_digest": result.processor_digest,
        "calibrator_digest": result.calibrator_digest,
        "prediction_digest": result.prediction_digest,
        "evaluated_sessions": result.evaluated_sessions,
        "positive_rank_ic_sessions": result.positive_rank_ic_sessions,
        "mean_ic": result.mean_ic,
        "mean_rank_ic": result.mean_rank_ic,
        "mean_top_bottom_spread": result.mean_top_bottom_spread,
    }


def _model_summary(
    results: list[CrossSectionalBaselineResult],
    *,
    seeds: tuple[int, ...],
    fold_count: int,
) -> dict[str, Any]:
    expected = len(seeds) * fold_count
    if len(results) != expected:
        return {
            "status": "INCOMPLETE_TRIALS",
            "completed_trials": len(results),
            "expected_trials": expected,
        }
    fold_means = {
        fold_id: _mean(item.mean_rank_ic for item in results if item.fold_id == fold_id)
        for fold_id in sorted({item.fold_id for item in results})
    }
    seed_means = {
        str(seed): _mean(item.mean_rank_ic for item in results if item.seed == seed)
        for seed in seeds
    }
    mean_rank_ic = _mean(item.mean_rank_ic for item in results)
    positive_required = math.ceil(fold_count * 2 / 3)
    signal_pass = (
        mean_rank_ic >= 0.02
        and sum(value > 0 for value in fold_means.values()) >= positive_required
        and all(value > 0 for value in seed_means.values())
    )
    return {
        "status": "LEARNABLE_EDGE" if signal_pass else "NO_LEARNABLE_EDGE",
        "completed_trials": len(results),
        "expected_trials": expected,
        "mean_ic": _mean(item.mean_ic for item in results),
        "mean_rank_ic": mean_rank_ic,
        "mean_top_bottom_spread": _mean(item.mean_top_bottom_spread for item in results),
        "positive_fold_count": sum(value > 0 for value in fold_means.values()),
        "positive_fold_required": positive_required,
        "fold_mean_rank_ic": fold_means,
        "seed_mean_rank_ic": seed_means,
    }


def _canonical_seeds(values: Sequence[int]) -> tuple[int, ...]:
    seeds = tuple(sorted(set(values)))
    if (
        not seeds
        or len(seeds) != len(values)
        or any(isinstance(seed, bool) or seed < 0 for seed in seeds)
    ):
        raise ValueError("baseline seeds must be unique non-negative integers")
    return seeds


def _publish(output_root: Path, report: dict[str, Any]) -> None:
    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=output_root.parent,
        prefix=f".{output_root.name}-staging-",
        ignore_cleanup_errors=True,
    ) as staging_name:
        staging = Path(staging_name)
        (staging / "report.json").write_bytes(canonical_json_bytes(report) + b"\n")
        staging.replace(output_root)


def _mean(values: Sequence[float] | Any) -> float:
    exact = tuple(values)
    if not exact:
        raise ValueError("cannot average empty baseline metrics")
    return math.fsum(exact) / len(exact)


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


if __name__ == "__main__":
    raise SystemExit(main())

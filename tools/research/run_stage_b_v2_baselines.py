"""Run the deterministic Stage B v2 cross-sectional baseline matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_domain import RankPortfolioPolicy
from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.cross_sectional_baselines import (
    CrossSectionalBaselineResult,
    CrossSectionalBaselineRow,
    CrossSectionalModelKind,
    run_cross_sectional_baseline,
)
from astraquant_quant.cross_sectional_portfolio import (
    CrossSectionalPortfolioMetrics,
    CrossSectionalPortfolioRow,
    evaluate_cross_sectional_portfolio,
)
from astraquant_quant.cross_sectional_splits import (
    assign_cross_sectional_fold_rows,
    build_cross_sectional_folds,
)
from astraquant_quant.executable_backtest import ExecutionPolicy

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


@dataclass(frozen=True, slots=True)
class _PortfolioInput:
    raw_return: float
    trailing_volatility: float
    median_daily_turnover: Decimal
    tradable: bool


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
        manifest, rows, portfolio_inputs = _load_materialization(arguments.materialization_root)
        seeds = _canonical_seeds(arguments.seeds)
        report = _run_matrix(
            manifest=manifest,
            rows=rows,
            portfolio_inputs=portfolio_inputs,
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
) -> tuple[
    dict[str, Any],
    tuple[CrossSectionalBaselineRow, ...],
    dict[int, _PortfolioInput],
]:
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
    portfolio_features = {"volatility_20", "turnover_median_20_log"}
    if not portfolio_features.issubset(frame.columns):
        raise ValueError("Stage B v2 portfolio risk/liquidity features are missing")
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
    portfolio_inputs = {
        int(record.row_id): _PortfolioInput(
            raw_return=float(record.raw_return),
            trailing_volatility=max(float(record.volatility_20), 1e-12),
            median_daily_turnover=Decimal(
                str(max(math.expm1(float(record.turnover_median_20_log)), 1e-12))
            ),
            tradable=True,
        )
        for record in frame.itertuples(index=False)
    }
    return manifest, rows, portfolio_inputs


def _run_matrix(
    *,
    manifest: dict[str, Any],
    rows: tuple[CrossSectionalBaselineRow, ...],
    portfolio_inputs: dict[int, _PortfolioInput],
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
            completed: list[
                tuple[CrossSectionalBaselineResult, CrossSectionalPortfolioMetrics]
            ] = []
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
                    portfolio = _evaluate_trial_portfolio(
                        result,
                        portfolio_inputs=portfolio_inputs,
                    )
                    completed.append((result, portfolio))
                    trials.append(_trial_value(trial_id, result, portfolio))
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


def _trial_value(
    trial_id: str,
    result: CrossSectionalBaselineResult,
    portfolio: CrossSectionalPortfolioMetrics,
) -> dict[str, Any]:
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
        "portfolio": _portfolio_value(portfolio),
    }


def _model_summary(
    results: list[tuple[CrossSectionalBaselineResult, CrossSectionalPortfolioMetrics]],
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
        fold_id: _mean(result.mean_rank_ic for result, _ in results if result.fold_id == fold_id)
        for fold_id in sorted({result.fold_id for result, _ in results})
    }
    seed_means = {
        str(seed): _mean(result.mean_rank_ic for result, _ in results if result.seed == seed)
        for seed in seeds
    }
    mean_rank_ic = _mean(result.mean_rank_ic for result, _ in results)
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
        "mean_ic": _mean(result.mean_ic for result, _ in results),
        "mean_rank_ic": mean_rank_ic,
        "mean_top_bottom_spread": _mean(result.mean_top_bottom_spread for result, _ in results),
        "positive_fold_count": sum(value > 0 for value in fold_means.values()),
        "positive_fold_required": positive_required,
        "fold_mean_rank_ic": fold_means,
        "seed_mean_rank_ic": seed_means,
        "mean_gross_return": _mean(portfolio.gross_return for _, portfolio in results),
        "mean_net_return": _mean(portfolio.net_return for _, portfolio in results),
        "mean_one_way_turnover": _mean(portfolio.one_way_turnover for _, portfolio in results),
        "total_commission": float(
            sum((portfolio.commission for _, portfolio in results), start=Decimal("0"))
        ),
        "total_stamp_duty": float(
            sum((portfolio.stamp_duty for _, portfolio in results), start=Decimal("0"))
        ),
        "total_transfer_fee": float(
            sum((portfolio.transfer_fee for _, portfolio in results), start=Decimal("0"))
        ),
        "total_slippage_cost": float(
            sum((portfolio.slippage_cost for _, portfolio in results), start=Decimal("0"))
        ),
        "maximum_drawdown": max(portfolio.max_drawdown for _, portfolio in results),
        "capacity_breach_trials": sum(portfolio.capacity_breaches > 0 for _, portfolio in results),
    }


def _evaluate_trial_portfolio(
    result: CrossSectionalBaselineResult,
    *,
    portfolio_inputs: dict[int, _PortfolioInput],
) -> CrossSectionalPortfolioMetrics:
    return evaluate_cross_sectional_portfolio(
        tuple(
            CrossSectionalPortfolioRow(
                row_id=prediction.row_id,
                decision_time=prediction.decision_time,
                instrument_id=prediction.instrument_id,
                horizon_sessions=result.horizon_sessions,
                rank_score=prediction.rank_score,
                calibrated_expected_return=prediction.calibrated_expected_return,
                raw_return=portfolio_inputs[prediction.row_id].raw_return,
                trailing_volatility=portfolio_inputs[prediction.row_id].trailing_volatility,
                median_daily_turnover=portfolio_inputs[prediction.row_id].median_daily_turnover,
                tradable=portfolio_inputs[prediction.row_id].tradable,
            )
            for prediction in result.predictions
        ),
        portfolio_policy=RankPortfolioPolicy.stage_b_v2(),
        execution_policy=ExecutionPolicy(),
    )


def _portfolio_value(metrics: CrossSectionalPortfolioMetrics) -> dict[str, Any]:
    return {
        "content_digest": metrics.content_digest,
        "period_count": metrics.period_count,
        "gross_return": metrics.gross_return,
        "net_return": metrics.net_return,
        "one_way_turnover": metrics.one_way_turnover,
        "commission": float(metrics.commission),
        "stamp_duty": float(metrics.stamp_duty),
        "transfer_fee": float(metrics.transfer_fee),
        "slippage_cost": float(metrics.slippage_cost),
        "max_drawdown": metrics.max_drawdown,
        "capacity_breaches": metrics.capacity_breaches,
        "minimum_capacity_ratio": metrics.minimum_capacity_ratio,
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

"""Run the deterministic Stage B v2 cross-sectional baseline matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_domain import RankPortfolioPolicy
from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.cross_sectional_baselines import (
    CrossSectionalBaselineResult,
    CrossSectionalBaselineRow,
    CrossSectionalModelKind,
    run_cross_sectional_baseline,
    score_cross_sectional_predictions,
)
from astraquant_quant.cross_sectional_portfolio import (
    CrossSectionalPortfolioMetrics,
    CrossSectionalPortfolioRow,
    evaluate_cross_sectional_portfolio,
)
from astraquant_quant.cross_sectional_splits import (
    CrossSectionalFoldRows,
    assign_cross_sectional_fold_rows,
    build_cross_sectional_folds,
)
from astraquant_quant.executable_backtest import ExecutionPolicy

_SOURCE_SCHEMA = "astraquant.stage-b-v2-materialization/v1"
_REPORT_SCHEMA = "astraquant.stage-b-v2-baseline-report/v1"
_DOUBLE_REQUEST_SCHEMA = "astraquant.stage-b-v2-double-ensemble-request/v1"
_DOUBLE_RESPONSE_SCHEMA = "astraquant.stage-b-v2-double-ensemble-response/v1"
_QLIB_UPSTREAM_COMMIT = "79633dd9506ea689e5400dea0197717b5b3d74b7"
_LOCAL_MODELS = (
    CrossSectionalModelKind.LIGHTGBM,
    CrossSectionalModelKind.RIDGE,
)
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
    parser.add_argument("--qlib-project", type=Path, default=Path("runners/qlib"))
    parser.add_argument("--skip-double-ensemble", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.output_root.exists():
            raise ValueError("baseline output_root must not already exist")
        manifest, rows, portfolio_inputs = _load_materialization(arguments.materialization_root)
        seeds = _canonical_seeds(arguments.seeds)
        arguments.output_root.parent.mkdir(parents=True, exist_ok=True)
        auxiliary: dict[str, bytes] = {}
        external_trials: dict[str, dict[str, Any]] | None = None
        with tempfile.TemporaryDirectory(
            dir=arguments.output_root.parent,
            prefix=f".{arguments.output_root.name}-qlib-",
            ignore_cleanup_errors=True,
        ) as double_name:
            if not arguments.skip_double_ensemble:
                double_root = Path(double_name)
                request_path = _prepare_double_ensemble_request(
                    root=double_root,
                    manifest=manifest,
                    rows=rows,
                    seeds=seeds,
                    minimum_fit_sessions=arguments.minimum_fit_sessions,
                    inner_valid_sessions=arguments.inner_valid_sessions,
                    outer_test_sessions=arguments.outer_test_sessions,
                    fold_count=arguments.fold_count,
                    purge_sessions=arguments.purge_sessions,
                )
                response_path = double_root / "response.json"
                _execute_double_ensemble(
                    request_path,
                    response_path,
                    arguments.qlib_project,
                )
                external_trials = _load_double_ensemble_response(
                    response_path,
                    request_path=request_path,
                    source_materialization_digest=str(manifest["content_digest"]),
                )
                auxiliary = {
                    "qlib/request.json": request_path.read_bytes(),
                    "qlib/rows.parquet": (double_root / "rows.parquet").read_bytes(),
                    "qlib/response.json": response_path.read_bytes(),
                }
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
                external_trials=external_trials,
            )
            _publish(arguments.output_root, report, auxiliary=auxiliary)
    except (
        OSError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
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


def _prepare_double_ensemble_request(
    *,
    root: Path,
    manifest: dict[str, Any],
    rows: tuple[CrossSectionalBaselineRow, ...],
    seeds: tuple[int, ...],
    minimum_fit_sessions: int,
    inner_valid_sessions: int,
    outer_test_sessions: int,
    fold_count: int,
    purge_sessions: int,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    feature_columns = list(rows[0].features)
    table_rows = [
        {
            "row_id": row.row_id,
            "decision_time": row.decision_time,
            "instrument_id": row.instrument_id,
            **dict(row.features),
            "cross_sectional_rank": row.cross_sectional_rank,
            "training_eligible": row.training_eligible,
        }
        for row in rows
    ]
    rows_path = root / "rows.parquet"
    pq.write_table(
        pa.Table.from_pylist(table_rows),
        rows_path,
        compression="zstd",
        version="2.6",
    )
    trial_values: list[dict[str, Any]] = []
    for horizon in sorted({row.horizon_sessions for row in rows}):
        horizon_rows = tuple(row for row in rows if row.horizon_sessions == horizon)
        timeline = tuple(sorted({row.decision_time for row in horizon_rows}))
        folds = build_cross_sectional_folds(
            timeline,
            horizons=tuple(sorted({row.horizon_sessions for row in rows})),
            minimum_fit_sessions=minimum_fit_sessions,
            inner_valid_sessions=inner_valid_sessions,
            outer_test_sessions=outer_test_sessions,
            fold_count=fold_count,
            purge_sessions=purge_sessions,
        )
        assignments = assign_cross_sectional_fold_rows(horizon_rows, folds)
        for seed in seeds:
            for assignment in assignments:
                trial_values.append(
                    {
                        "trial_id": (f"h{horizon}-double_ensemble-s{seed}-{assignment.fold_id}"),
                        "seed": seed,
                        "fit_row_ids": [
                            horizon_rows[index].row_id for index in assignment.fit_indices
                        ],
                        "inner_valid_row_ids": [
                            horizon_rows[index].row_id for index in assignment.inner_valid_indices
                        ],
                        "outer_test_row_ids": [
                            horizon_rows[index].row_id for index in assignment.outer_test_indices
                        ],
                    }
                )
    body: dict[str, Any] = {
        "schema_version": _DOUBLE_REQUEST_SCHEMA,
        "upstream_commit": _QLIB_UPSTREAM_COMMIT,
        "source_materialization_digest": manifest["content_digest"],
        "feature_columns": feature_columns,
        "row_count": len(rows),
        "rows_file": {"path": "rows.parquet", "digest": _digest(rows_path.read_bytes())},
        "model_config": {
            "num_models": 3,
            "epochs": 28,
            "enable_sr": True,
            "enable_fs": True,
            "decay": 0.5,
        },
        "trials": trial_values,
    }
    request = {"content_digest": _digest(canonical_json_bytes(body)), **body}
    request_path = root / "request.json"
    request_path.write_bytes(canonical_json_bytes(request) + b"\n")
    return request_path


def _execute_double_ensemble(
    request_path: Path,
    response_path: Path,
    project: Path,
) -> None:
    subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project.resolve()),
            "--frozen",
            "python",
            "-m",
            "astraquant_qlib_runner",
            "--request",
            str(request_path.resolve()),
            "--output",
            str(response_path.resolve()),
        ],
        check=True,
    )


def _load_double_ensemble_response(
    response_path: Path,
    *,
    request_path: Path,
    source_materialization_digest: str,
) -> dict[str, dict[str, Any]]:
    request_value = json.loads(request_path.read_text(encoding="utf-8"))
    response_value = json.loads(response_path.read_text(encoding="utf-8"))
    if not isinstance(response_value, dict):
        raise ValueError("DoubleEnsemble response schema mismatch")
    body = {key: value for key, value in response_value.items() if key != "content_digest"}
    if (
        response_value.get("schema_version") != _DOUBLE_RESPONSE_SCHEMA
        or response_value.get("content_digest") != _digest(canonical_json_bytes(body))
        or response_value.get("request_content_digest") != request_value.get("content_digest")
        or response_value.get("source_materialization_digest") != source_materialization_digest
        or response_value.get("upstream_commit") != _QLIB_UPSTREAM_COMMIT
    ):
        raise ValueError("DoubleEnsemble response identity mismatch")
    trials = response_value.get("trials")
    if not isinstance(trials, list) or not trials:
        raise ValueError("DoubleEnsemble response trials are missing")
    result: dict[str, dict[str, Any]] = {}
    for trial in trials:
        if not isinstance(trial, dict) or not isinstance(trial.get("trial_id"), str):
            raise ValueError("DoubleEnsemble response trial schema mismatch")
        trial_id = trial["trial_id"]
        if trial_id in result:
            raise ValueError("DoubleEnsemble response trial identifiers must be unique")
        result[trial_id] = trial
    expected = {
        str(trial["trial_id"])
        for trial in request_value.get("trials", [])
        if isinstance(trial, dict) and isinstance(trial.get("trial_id"), str)
    }
    if set(result) != expected:
        raise ValueError("DoubleEnsemble response trial coverage mismatch")
    return result


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
    external_trials: dict[str, dict[str, Any]] | None,
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
        for model_kind in _LOCAL_MODELS:
            completed: list[
                tuple[
                    CrossSectionalBaselineResult,
                    dict[str, CrossSectionalPortfolioMetrics],
                ]
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
                    portfolios = _evaluate_trial_portfolios(
                        result,
                        portfolio_inputs=portfolio_inputs,
                    )
                    completed.append((result, portfolios))
                    trials.append(_trial_value(trial_id, result, portfolios))
            model_reports[model_kind.value] = _model_summary(
                completed,
                seeds=seeds,
                fold_count=fold_count,
            )
        if external_trials is not None:
            double_completed: list[
                tuple[
                    CrossSectionalBaselineResult,
                    dict[str, CrossSectionalPortfolioMetrics],
                ]
            ] = []
            for seed in seeds:
                for assignment in assignments:
                    trial_id = f"h{horizon}-double_ensemble-s{seed}-{assignment.fold_id}"
                    trial = external_trials[trial_id]
                    result = _score_double_ensemble_trial(
                        horizon_rows,
                        assignment=assignment,
                        seed=seed,
                        trial=trial,
                    )
                    portfolios = _evaluate_trial_portfolios(
                        result,
                        portfolio_inputs=portfolio_inputs,
                    )
                    double_completed.append((result, portfolios))
                    trials.append(_trial_value(trial_id, result, portfolios))
            model_reports[CrossSectionalModelKind.DOUBLE_ENSEMBLE.value] = _model_summary(
                double_completed,
                seeds=seeds,
                fold_count=fold_count,
            )
        _apply_relative_gate(model_reports)
        horizon_reports[str(horizon)] = {"models": model_reports}
    body: dict[str, Any] = {
        "schema_version": _REPORT_SCHEMA,
        "source_materialization_digest": manifest["content_digest"],
        "models": sorted(
            [
                *(value.value for value in _LOCAL_MODELS),
                *(
                    [CrossSectionalModelKind.DOUBLE_ENSEMBLE.value]
                    if external_trials is not None
                    else []
                ),
            ]
        ),
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


def _score_double_ensemble_trial(
    rows: tuple[CrossSectionalBaselineRow, ...],
    *,
    assignment: CrossSectionalFoldRows,
    seed: int,
    trial: dict[str, Any],
) -> CrossSectionalBaselineResult:
    if trial.get("seed") != seed:
        raise ValueError("DoubleEnsemble response seed mismatch")
    valid_rows = tuple(rows[index] for index in assignment.inner_valid_indices)
    test_rows = tuple(rows[index] for index in assignment.outer_test_indices)
    valid_scores = _external_scores(
        trial,
        "inner_valid_predictions",
        expected_row_ids=tuple(row.row_id for row in valid_rows),
    )
    test_scores = _external_scores(
        trial,
        "outer_test_predictions",
        expected_row_ids=tuple(row.row_id for row in test_rows),
    )
    processor_digest = trial.get("processor_digest")
    model_digest = trial.get("model_digest")
    if not isinstance(processor_digest, str) or not isinstance(model_digest, str):
        raise ValueError("DoubleEnsemble response digests are missing")
    return score_cross_sectional_predictions(
        rows,
        assignment=assignment,
        model_kind=CrossSectionalModelKind.DOUBLE_ENSEMBLE,
        seed=seed,
        valid_scores=valid_scores,
        test_scores=test_scores,
        processor_digest=processor_digest,
        model_digest=model_digest,
    )


def _external_scores(
    trial: dict[str, Any],
    key: str,
    *,
    expected_row_ids: tuple[int, ...],
) -> tuple[float, ...]:
    values = trial.get(key)
    if not isinstance(values, list) or len(values) != len(expected_row_ids):
        raise ValueError(f"DoubleEnsemble {key} coverage mismatch")
    row_ids: list[int] = []
    scores: list[float] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"DoubleEnsemble {key} schema mismatch")
        row_id = value.get("row_id")
        score = value.get("score")
        if (
            isinstance(row_id, bool)
            or not isinstance(row_id, int)
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            raise ValueError(f"DoubleEnsemble {key} schema mismatch")
        row_ids.append(row_id)
        scores.append(float(score))
    if tuple(row_ids) != expected_row_ids:
        raise ValueError(f"DoubleEnsemble {key} row order mismatch")
    return tuple(scores)


def _trial_value(
    trial_id: str,
    result: CrossSectionalBaselineResult,
    portfolios: dict[str, CrossSectionalPortfolioMetrics],
) -> dict[str, Any]:
    return {
        "trial_id": trial_id,
        "horizon_sessions": result.horizon_sessions,
        "model": result.model_kind.value,
        "seed": result.seed,
        "fold_id": result.fold_id,
        "fold_digest": result.fold_digest,
        "assignment_digest": result.assignment_digest,
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
        "portfolio": _portfolio_value(portfolios["BASE"]),
        "portfolio_profiles": {
            name: _portfolio_value(metrics) for name, metrics in portfolios.items()
        },
    }


def _model_summary(
    results: list[tuple[CrossSectionalBaselineResult, dict[str, CrossSectionalPortfolioMetrics]]],
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
    base_results = tuple((result, profiles["BASE"]) for result, profiles in results)
    adverse_results = tuple(profiles["ADVERSE"] for _, profiles in results)
    severe_results = tuple(profiles["SEVERE"] for _, profiles in results)
    fold_net = {
        fold_id: _mean(
            portfolio.net_return for result, portfolio in base_results if result.fold_id == fold_id
        )
        for fold_id in sorted({result.fold_id for result, _ in base_results})
    }
    seed_net = {
        str(seed): _mean(
            portfolio.net_return for result, portfolio in base_results if result.seed == seed
        )
        for seed in seeds
    }
    mean_net_return = _mean(portfolio.net_return for _, portfolio in base_results)
    trading_pass = (
        mean_net_return > 0
        and sum(value > 0 for value in fold_net.values()) >= positive_required
        and all(value > 0 for value in seed_net.values())
        and _mean(portfolio.net_return for portfolio in severe_results) > -0.02
    )
    return {
        "status": "LEARNABLE_EDGE" if signal_pass else "NO_LEARNABLE_EDGE",
        "gate_status": "NET_EDGE" if signal_pass and trading_pass else "NO_NET_EDGE",
        "completed_trials": len(results),
        "expected_trials": expected,
        "mean_ic": _mean(result.mean_ic for result, _ in results),
        "mean_rank_ic": mean_rank_ic,
        "mean_top_bottom_spread": _mean(result.mean_top_bottom_spread for result, _ in results),
        "positive_fold_count": sum(value > 0 for value in fold_means.values()),
        "positive_fold_required": positive_required,
        "fold_mean_rank_ic": fold_means,
        "seed_mean_rank_ic": seed_means,
        "mean_gross_return": _mean(portfolio.gross_return for _, portfolio in base_results),
        "mean_net_return": mean_net_return,
        "mean_adverse_net_return": _mean(portfolio.net_return for portfolio in adverse_results),
        "mean_severe_net_return": _mean(portfolio.net_return for portfolio in severe_results),
        "mean_one_way_turnover": _mean(portfolio.one_way_turnover for _, portfolio in base_results),
        "fold_mean_net_return": fold_net,
        "seed_mean_net_return": seed_net,
        "total_commission": float(
            sum(
                (portfolio.commission for _, portfolio in base_results),
                start=Decimal("0"),
            )
        ),
        "total_stamp_duty": float(
            sum(
                (portfolio.stamp_duty for _, portfolio in base_results),
                start=Decimal("0"),
            )
        ),
        "total_transfer_fee": float(
            sum(
                (portfolio.transfer_fee for _, portfolio in base_results),
                start=Decimal("0"),
            )
        ),
        "total_slippage_cost": float(
            sum(
                (portfolio.slippage_cost for _, portfolio in base_results),
                start=Decimal("0"),
            )
        ),
        "maximum_drawdown": max(portfolio.max_drawdown for _, portfolio in base_results),
        "capacity_breach_trials": sum(
            portfolio.capacity_breaches > 0 for _, portfolio in base_results
        ),
    }


def _evaluate_trial_portfolios(
    result: CrossSectionalBaselineResult,
    *,
    portfolio_inputs: dict[int, _PortfolioInput],
) -> dict[str, CrossSectionalPortfolioMetrics]:
    rows = tuple(
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
    )
    return {
        name: evaluate_cross_sectional_portfolio(
            rows,
            portfolio_policy=RankPortfolioPolicy.stage_b_v2(),
            execution_policy=policy,
        )
        for name, policy in _execution_profiles().items()
    }


def _execution_profiles() -> dict[str, ExecutionPolicy]:
    return {
        "ADVERSE": ExecutionPolicy(
            slippage_bps=Decimal("5"),
            participation_rate=Decimal("0.05"),
        ),
        "BASE": ExecutionPolicy(),
        "SEVERE": ExecutionPolicy(
            commission_rate=Decimal("0.0004"),
            stamp_duty_rate=Decimal("0.001"),
            transfer_fee_rate=Decimal("0.00002"),
            slippage_bps=Decimal("10"),
            participation_rate=Decimal("0.02"),
        ),
    }


def _apply_relative_gate(model_reports: dict[str, Any]) -> None:
    ridge = model_reports.get("RIDGE")
    if not isinstance(ridge, dict) or not isinstance(ridge.get("mean_net_return"), float):
        return
    ridge_net = ridge["mean_net_return"]
    ridge["delta_net_vs_ridge"] = 0.0
    for model_name, summary in model_reports.items():
        if model_name == "RIDGE" or not isinstance(summary, dict):
            continue
        net_return = summary.get("mean_net_return")
        if not isinstance(net_return, float):
            continue
        delta = net_return - ridge_net
        summary["delta_net_vs_ridge"] = delta
        if delta < 0.002:
            summary["gate_status"] = "NO_NET_EDGE"


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


def _publish(
    output_root: Path,
    report: dict[str, Any],
    *,
    auxiliary: dict[str, bytes],
) -> None:
    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=output_root.parent,
        prefix=f".{output_root.name}-staging-",
        ignore_cleanup_errors=True,
    ) as staging_name:
        staging = Path(staging_name)
        (staging / "report.json").write_bytes(canonical_json_bytes(report) + b"\n")
        for relative_path, content in auxiliary.items():
            path = staging / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
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

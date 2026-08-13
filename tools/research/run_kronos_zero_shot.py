"""Prepare and evaluate Kronos under the shared executable panel contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from astraquant_data.exports.kronos import (
    KRONOS_MODEL_ID,
    KRONOS_MODEL_REVISION,
    KRONOS_TOKENIZER_ID,
    KRONOS_TOKENIZER_REVISION,
    KronosArtifact,
    KronosSource,
    export_kronos_request,
)
from astraquant_data.exports.qlib import QLIB_MODEL_DOUBLE_ENSEMBLE, export_qlib_request
from astraquant_domain import ScoreSemantics, TrainingTaskKind, TrainingTaskSpec
from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.baseline_matrix import WalkForwardFold
from astraquant_quant.executable_backtest import ExecutionPolicy, InstrumentKind
from astraquant_quant.panel_research import (
    PanelDataset,
    build_panel,
    panel_walk_forward,
    run_panel_executable_expected_returns,
)
from tools.research.build_training_set import build_features_json
from tools.research.compare_double_ensemble import (
    _read_folds,
    _ridge_predictions,
)
from tools.research.compare_double_ensemble import (
    _validate_response as validate_double_ensemble_response,
)
from tools.research.prepare_kronos_weights import PreparedArtifact, prepare_artifact
from tools.research.run_double_ensemble_panel import (
    _dataset_spec,
    _digest,
    _fold_regimes,
    _liquidity_buckets,
)
from tools.research.run_panel_executable_backtest import _instrument, _json_default

_CONTEXT_SCHEMA = "astraquant.kronos-unified-context/v1"
_REPORT_SCHEMA = "astraquant.kronos-unified-executable/v1"


class PanelForecastCalendar:
    def __init__(self, panel: PanelDataset) -> None:
        self._times = {
            item.instrument_id: tuple(bar.timestamp for bar in item.raw_bars)
            for item in panel.instruments
        }
        self._indices = {
            instrument_id: {value: index for index, value in enumerate(values)}
            for instrument_id, values in self._times.items()
        }
        self.calendar_snapshot_id = _canonical_digest(
            {
                "kind": "EXACT_PANEL_SESSION_TIMESTAMPS",
                "instruments": {
                    key: [value.isoformat() for value in values]
                    for key, values in sorted(self._times.items())
                },
            }
        )

    def future_times(
        self, *, instrument_id: str, decision_time: datetime, count: int
    ) -> Sequence[datetime]:
        values = self._times.get(instrument_id)
        index = self._indices.get(instrument_id, {}).get(decision_time)
        if values is None or index is None:
            raise ValueError("decision time is absent from the exact panel calendar")
        return values[index + 1 : index + 1 + count]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-kronos-zero-shot")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("dataset_specs", nargs="+")
    prepare.add_argument("--data-root", required=True, type=Path)
    prepare.add_argument("--runner-root", required=True, type=Path)
    prepare.add_argument("--output-root", required=True, type=Path)
    prepare.add_argument("--minimum-train-timestamps", type=int, default=5500)
    prepare.add_argument("--test-timestamp-count", type=int, default=1500)
    prepare.add_argument("--fold-count", type=int, default=3)
    prepare.add_argument("--holding-bars", type=int, default=5)
    prepare.add_argument("--context-length", type=int, default=128)
    prepare.add_argument("--sample-count", type=int, default=5)
    prepare.add_argument("--seed", type=int, default=7)
    prepare.add_argument("--commission-rate", type=Decimal, default=Decimal("0.00025"))
    prepare.add_argument("--minimum-edge", type=Decimal, default=Decimal("0"))

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--context", required=True, type=Path)
    evaluate.add_argument("--kronos-response", required=True, type=Path)
    evaluate.add_argument("--double-ensemble-response", required=True, type=Path)
    evaluate.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "prepare":
            _prepare(arguments)
        else:
            _evaluate(
                arguments.context,
                arguments.kronos_response,
                arguments.double_ensemble_response,
                arguments.output,
            )
    except (OSError, ValueError, TypeError, ArithmeticError, json.JSONDecodeError) as error:
        print(f"Kronos unified evaluation failed: {error}", file=sys.stderr)
        return 1
    return 0


def _prepare(arguments: argparse.Namespace) -> None:
    if arguments.output_root.exists():
        raise ValueError("output_root must not already exist")
    specs = tuple(_dataset_spec(value) for value in arguments.dataset_specs)
    if len({dataset_id for dataset_id, _ in specs}) != len(specs):
        raise ValueError("dataset specs must be unique")
    payloads = [
        build_features_json(
            arguments.data_root,
            dataset_id,
            horizon=arguments.holding_bars,
            threshold=Decimal("0.005"),
            snapshot_id=snapshot_id,
        )
        for dataset_id, snapshot_id in specs
    ]
    if any(payload.get("provider_id") != "eastmoney" for payload in payloads):
        raise ValueError("all Kronos panel inputs must be Eastmoney snapshots")
    panel = build_panel(tuple(_instrument(payload) for payload in payloads))
    folds = panel_walk_forward(
        panel,
        minimum_train_timestamps=arguments.minimum_train_timestamps,
        test_timestamp_count=arguments.test_timestamp_count,
        fold_count=arguments.fold_count,
        purge_timestamp_count=arguments.holding_bars + 1,
    )
    sources = tuple(
        {
            "dataset_id": payload["dataset_id"],
            "source_snapshot_id": payload["source_snapshot_id"],
            "instrument_id": payload["instrument_id"],
            "provider_id": payload["provider_id"],
            "bar_count": payload["bar_count"],
            "row_count": payload["row_count"],
            "date_range": payload["date_range"],
        }
        for payload in sorted(payloads, key=lambda item: str(item["instrument_id"]))
    )
    ancestry_digest = _digest(sources)
    task = TrainingTaskSpec(
        task_id="daily-expected-return-v1",
        kind=TrainingTaskKind.BASE_TARGET,
        label_name=f"next_open_return_{arguments.holding_bars}bars",
        horizon_bars=arguments.holding_bars,
        score_semantics=ScoreSemantics.EXPECTED_RETURN,
        universe_id=f"eastmoney-panel-{ancestry_digest[7:23]}",
        execution_policy_id="a-share-next-open-etf-v1",
        evaluation_metrics=("rank_ic", "executable_net_return", "max_drawdown"),
    )
    qlib_export = export_qlib_request(
        output_root=arguments.output_root / "qlib",
        dataset_id=task.universe_id,
        source_snapshot_id=ancestry_digest,
        provider_id="eastmoney",
        rows=panel.rows,
        folds=folds,
        fee_rate=arguments.commission_rate,
        prediction_threshold=None,
        seed=arguments.seed,
        training_task=task,
        model_kind=QLIB_MODEL_DOUBLE_ENSEMBLE,
        target_column="future_return",
    )
    runner_root = arguments.runner_root.resolve()
    model = _existing_artifact(runner_root, KRONOS_MODEL_ID, KRONOS_MODEL_REVISION)
    tokenizer = _existing_artifact(
        runner_root, KRONOS_TOKENIZER_ID, KRONOS_TOKENIZER_REVISION
    )
    kronos_export = export_kronos_request(
        output_root=arguments.output_root / "kronos",
        panel=panel,
        folds=folds,
        sources=tuple(
            KronosSource(
                dataset_id=str(item["dataset_id"]),
                instrument_id=str(item["instrument_id"]),
                source_snapshot_id=str(item["source_snapshot_id"]),
            )
            for item in sources
        ),
        model=_kronos_artifact(model, KRONOS_MODEL_ID, KRONOS_MODEL_REVISION, runner_root),
        tokenizer=_kronos_artifact(
            tokenizer, KRONOS_TOKENIZER_ID, KRONOS_TOKENIZER_REVISION, runner_root
        ),
        context_length=arguments.context_length,
        prediction_length=arguments.holding_bars,
        seed=arguments.seed,
        temperature=1.0,
        top_k=0,
        top_p=0.9,
        sample_count=arguments.sample_count,
        calendar=PanelForecastCalendar(panel),
    )
    context = {
        "schema_version": _CONTEXT_SCHEMA,
        "data_root": str(arguments.data_root.resolve()),
        "runner_root": str(runner_root),
        "sources": sources,
        "kronos_request_path": str(kronos_export.request_path.resolve()),
        "kronos_request_content_digest": kronos_export.content_digest,
        "qlib_request_path": str(qlib_export.request_path.resolve()),
        "qlib_request_content_digest": qlib_export.content_digest,
        "eligible_row_ids": list(kronos_export.eligible_row_ids),
        "fold_policy": {
            "minimum_train_timestamps": arguments.minimum_train_timestamps,
            "test_timestamp_count": arguments.test_timestamp_count,
            "fold_count": arguments.fold_count,
            "purge_timestamp_count": arguments.holding_bars + 1,
        },
        "execution_policy": {
            "holding_bars": arguments.holding_bars,
            "seed": arguments.seed,
            "commission_rate": str(arguments.commission_rate),
            "minimum_edge": str(arguments.minimum_edge),
            "initial_cash": "100000",
            "minimum_commission": "0",
            "slippage_bps": "2",
            "participation_rate": "0.10",
            "lot_size": 100,
        },
    }
    arguments.output_root.mkdir(parents=True, exist_ok=True)
    (arguments.output_root / "context.json").write_text(
        json.dumps(context, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _evaluate(
    context_path: Path,
    kronos_response_path: Path,
    double_response_path: Path,
    output_path: Path,
) -> None:
    context = _read_json(context_path)
    if context.get("schema_version") != _CONTEXT_SCHEMA:
        raise ValueError("Kronos unified context schema mismatch")
    kronos_request = _read_json(Path(_required_str(context, "kronos_request_path")))
    qlib_request = _read_json(Path(_required_str(context, "qlib_request_path")))
    if kronos_request.get("content_digest") != context.get("kronos_request_content_digest"):
        raise ValueError("Kronos request digest does not match context")
    if qlib_request.get("content_digest") != context.get("qlib_request_content_digest"):
        raise ValueError("Qlib request digest does not match context")
    kronos_response = _read_json(kronos_response_path)
    double_response = _read_json(double_response_path)
    forecasts = validate_kronos_response(kronos_response, kronos_request)
    validate_double_ensemble_response(double_response, qlib_request)
    panel, sources = _rebuild_panel(context)
    fold_policy = _required_mapping(context, "fold_policy")
    folds = panel_walk_forward(
        panel,
        minimum_train_timestamps=_required_int(fold_policy, "minimum_train_timestamps"),
        test_timestamp_count=_required_int(fold_policy, "test_timestamp_count"),
        fold_count=_required_int(fold_policy, "fold_count"),
        purge_timestamp_count=_required_int(fold_policy, "purge_timestamp_count"),
    )
    qlib_folds, fit_indices = _read_folds(qlib_request)
    if folds != qlib_folds:
        raise ValueError("rebuilt folds do not match Qlib request")
    eligible_keys = {_eligibility_key(item) for item in forecasts}
    restricted = restrict_folds_to_eligibility(folds, eligible_keys)
    kronos_predictions = [
        {
            "fold_id": item["fold_id"],
            "row_id": item["row_id"],
            "score": item["expected_return"],
        }
        for item in forecasts
    ]
    raw_double = double_response.get("predictions")
    if not isinstance(raw_double, list):
        raise ValueError("DoubleEnsemble predictions schema mismatch")
    double_predictions = _filter_predictions(raw_double, eligible_keys, "DoubleEnsemble")
    ridge_all = _ridge_predictions(list(panel.rows), folds=folds, fit_indices=fit_indices)
    ridge_predictions = _filter_predictions(ridge_all, eligible_keys, "Ridge")
    execution = _required_mapping(context, "execution_policy")
    commission = Decimal(_required_str(execution, "commission_rate"))
    minimum_score = float(
        Decimal(2) * commission + Decimal(_required_str(execution, "minimum_edge"))
    )
    policy = ExecutionPolicy(
        initial_cash=Decimal(_required_str(execution, "initial_cash")),
        commission_rate=commission,
        minimum_commission=Decimal(_required_str(execution, "minimum_commission")),
        stamp_duty_rate=Decimal("0"),
        transfer_fee_rate=Decimal("0"),
        slippage_bps=Decimal(_required_str(execution, "slippage_bps")),
        participation_rate=Decimal(_required_str(execution, "participation_rate")),
        lot_size=_required_int(execution, "lot_size"),
        instrument_kind=InstrumentKind.ETF,
    )
    predictions_by_model = {
        "KRONOS_ZERO_SHOT": kronos_predictions,
        "DOUBLE_ENSEMBLE": double_predictions,
        "RIDGE": ridge_predictions,
    }
    reports = {
        model_id: run_panel_executable_expected_returns(
            panel,
            folds=restricted,
            predictions=predictions,
            minimum_score=minimum_score,
            holding_bars=_required_int(execution, "holding_bars"),
            policy=policy,
            model_id=model_id,
        )
        for model_id, predictions in predictions_by_model.items()
    }
    liquidity = _liquidity_buckets(panel)
    regimes = _fold_regimes(panel, restricted)
    models: dict[str, object] = {}
    for model_id, report in reports.items():
        value = asdict(report)
        value["instruments"] = [
            {**item, "liquidity_bucket": liquidity[str(item["instrument_id"])]}
            for item in value["instruments"]
        ]
        value["folds"] = [
            {**item, "regime": regimes[str(item["fold_id"])]} for item in value["folds"]
        ]
        value["trade_concentration"] = _trade_concentration(value["instruments"])
        models[model_id] = value
    body: dict[str, object] = {
        "schema_version": _REPORT_SCHEMA,
        "fidelity": "BAR_NEXT_OPEN_CONSERVATIVE",
        "sources": sources,
        "shared_contract": {
            "score_semantics": "EXPECTED_RETURN",
            "eligible_rows": len(eligible_keys),
            "selection_minimum_score": minimum_score,
            "fold_policy": fold_policy,
            "execution_policy": execution,
        },
        "kronos_path_diagnostics": _path_diagnostics(
            panel,
            forecasts,
            forecast_horizon_bars=_required_int(execution, "holding_bars"),
        ),
        "models": models,
        "digests": {
            "kronos_input": kronos_request["content_digest"],
            "qlib_input": qlib_request["content_digest"],
            "folds": _digest(
                [
                    {
                        "fold_id": fold.fold_id,
                        "train_indices": fold.train_indices,
                        "test_indices": fold.test_indices,
                    }
                    for fold in restricted
                ]
            ),
            "kronos_predictions": _digest(kronos_predictions),
            "double_ensemble_predictions": _digest(double_predictions),
            "ridge_predictions": _digest(ridge_predictions),
        },
    }
    body["digests"]["report"] = _digest(body)  # type: ignore[index]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def validate_kronos_response(
    response: Mapping[str, object], request: Mapping[str, object]
) -> list[dict[str, object]]:
    if response.get("schema_version") != "astraquant.kronos-response/v1":
        raise ValueError("Kronos response schema mismatch")
    for key in ("request_content_digest", "upstream_commit"):
        expected_key = "content_digest" if key == "request_content_digest" else key
        if response.get(key) != request.get(expected_key):
            raise ValueError(f"Kronos response {key} mismatch")
    _validate_response_artifact(response, request, "model")
    _validate_response_artifact(response, request, "tokenizer")
    environment = _required_mapping(response, "environment")
    for environment_key in ("python", "torch", "device"):
        _required_str(environment, environment_key)
    raw_forecasts = response.get("forecasts")
    raw_rows = request.get("rows")
    if not isinstance(raw_forecasts, list) or not isinstance(raw_rows, list):
        raise ValueError("Kronos forecast coverage schema mismatch")
    forecasts: list[dict[str, object]] = []
    actual_keys = []
    for value in raw_forecasts:
        if not isinstance(value, dict):
            raise ValueError("Kronos forecast schema mismatch")
        item = dict(value)
        forecast_key = _forecast_key(item)
        actual_keys.append(forecast_key)
        expected_return = _finite(item.get("expected_return"), "expected return")
        p10 = _finite(item.get("terminal_return_p10"), "p10")
        p50 = _finite(item.get("terminal_return_p50"), "p50")
        p90 = _finite(item.get("terminal_return_p90"), "p90")
        if not p10 <= p50 <= p90:
            raise ValueError("Kronos terminal quantiles are not ordered")
        if expected_return != p50:
            raise ValueError("Kronos expected return must equal its terminal median")
        fraction = _finite(item.get("up_path_fraction"), "up path fraction")
        volatility = _finite(item.get("predicted_volatility"), "predicted volatility")
        width = _finite(item.get("uncertainty_width"), "uncertainty width")
        if not 0 <= fraction <= 1 or volatility < 0 or width < 0:
            raise ValueError("Kronos forecast diagnostics are out of range")
        forecasts.append(item)
    expected_keys = [_forecast_key(value) for value in raw_rows if isinstance(value, dict)]
    if len(expected_keys) != len(raw_rows) or actual_keys != expected_keys:
        raise ValueError("Kronos forecast coverage or order mismatch")
    supplied = response.get("content_digest")
    body = {key: value for key, value in response.items() if key != "content_digest"}
    if supplied != _canonical_digest(body):
        raise ValueError("Kronos response content digest mismatch")
    return forecasts


def restrict_folds_to_eligibility(
    folds: Sequence[WalkForwardFold], eligible: set[tuple[str, int]]
) -> tuple[WalkForwardFold, ...]:
    expected = {(fold.fold_id, row_id) for fold in folds for row_id in fold.test_indices}
    if not eligible or not eligible <= expected:
        raise ValueError("eligibility contains unknown fold rows")
    result = []
    for fold in folds:
        test = tuple(
            row_id for row_id in fold.test_indices if (fold.fold_id, row_id) in eligible
        )
        if not test:
            raise ValueError(f"eligibility removed every row from {fold.fold_id}")
        result.append(WalkForwardFold(fold.fold_id, fold.train_indices, test))
    if sum(len(fold.test_indices) for fold in result) != len(eligible):
        raise ValueError("eligibility contains duplicate row identities across folds")
    return tuple(result)


def _filter_predictions(
    values: Sequence[object], eligible: set[tuple[str, int]], name: str
) -> list[dict[str, object]]:
    result = []
    keys = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"{name} prediction schema mismatch")
        fold_id = value.get("fold_id")
        row_id = value.get("row_id")
        score = value.get("score")
        if (
            not isinstance(fold_id, str)
            or isinstance(row_id, bool)
            or not isinstance(row_id, int)
            or isinstance(score, bool)
            or not isinstance(score, int | float)
            or not math.isfinite(float(score))
        ):
            raise ValueError(f"{name} prediction schema mismatch")
        key = (fold_id, row_id)
        if key in eligible:
            if key in keys:
                raise ValueError(f"{name} prediction contains duplicate eligible rows")
            keys.add(key)
            result.append({"fold_id": fold_id, "row_id": row_id, "score": float(score)})
    if keys != eligible:
        raise ValueError(f"{name} prediction eligibility coverage mismatch")
    return result


def _path_diagnostics(
    panel: PanelDataset,
    forecasts: Sequence[Mapping[str, object]],
    *,
    forecast_horizon_bars: int,
) -> dict[str, float | int | str]:
    if forecast_horizon_bars <= 0:
        raise ValueError("Kronos diagnostic horizon must be positive")
    instruments = {item.instrument_id: item for item in panel.instruments}
    absolute_errors = []
    direction_hits = 0
    coverage_hits = 0
    widths = []
    for item in forecasts:
        row_id = item["row_id"]
        if isinstance(row_id, bool) or not isinstance(row_id, int):
            raise ValueError("Kronos diagnostic row_id mismatch")
        observation = panel.observations[row_id]
        instrument = instruments[observation.instrument_id]
        decision_index = instrument.row_bar_indices[observation.local_row_id]
        terminal_index = decision_index + forecast_horizon_bars
        if terminal_index >= len(instrument.raw_bars):
            raise ValueError("Kronos diagnostic terminal bar is unavailable")
        decision_close = instrument.raw_bars[decision_index].close
        terminal_close = instrument.raw_bars[terminal_index].close
        actual = float((terminal_close - decision_close) / decision_close)
        predicted = _finite(item.get("expected_return"), "expected return")
        lower = _finite(item.get("terminal_return_p10"), "p10")
        upper = _finite(item.get("terminal_return_p90"), "p90")
        absolute_errors.append(abs(predicted - actual))
        direction_hits += (predicted >= 0) == (actual >= 0)
        coverage_hits += lower <= actual <= upper
        widths.append(_finite(item.get("uncertainty_width"), "uncertainty width"))
    count = len(forecasts)
    return {
        "truth_basis": "DECISION_CLOSE_TO_TERMINAL_CLOSE",
        "forecast_horizon_bars": forecast_horizon_bars,
        "terminal_return_mae": sum(absolute_errors) / count,
        "direction_accuracy": direction_hits / count,
        "p10_p90_coverage": coverage_hits / count,
        "mean_uncertainty_width": sum(widths) / count,
    }


def _rebuild_panel(context: Mapping[str, object]) -> tuple[PanelDataset, list[dict[str, object]]]:
    raw_sources = context.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("Kronos context sources schema mismatch")
    data_root = Path(_required_str(context, "data_root"))
    execution = _required_mapping(context, "execution_policy")
    sources: list[dict[str, object]] = []
    instruments = []
    for raw in raw_sources:
        if not isinstance(raw, dict):
            raise ValueError("Kronos context source schema mismatch")
        source = dict(raw)
        dataset_id = _required_str(source, "dataset_id")
        snapshot_id = _required_str(source, "source_snapshot_id").removeprefix("sha256:")
        payload = build_features_json(
            data_root,
            dataset_id,
            horizon=_required_int(execution, "holding_bars"),
            threshold=Decimal("0.005"),
            snapshot_id=snapshot_id,
        )
        for key in ("dataset_id", "source_snapshot_id", "instrument_id", "provider_id"):
            if payload.get(key) != source.get(key):
                raise ValueError(f"rebuilt Kronos source {key} mismatch")
        sources.append(source)
        instruments.append(_instrument(payload))
    return build_panel(tuple(instruments)), sources


def _existing_artifact(root: Path, repo_id: str, revision: str) -> PreparedArtifact:
    def no_download(**kwargs: object) -> Path:
        raise ValueError("Kronos unified prepare never downloads weights")

    return prepare_artifact(
        repo_id=repo_id, revision=revision, root=root, downloader=no_download
    )


def _kronos_artifact(
    artifact: PreparedArtifact, repo_id: str, revision: str, root: Path
) -> KronosArtifact:
    path = artifact.directory / "model.safetensors"
    return KronosArtifact(
        artifact_id=repo_id,
        revision=revision,
        weights_path=path.relative_to(root).as_posix(),
        weights_digest=artifact.weights_digest,
    )


def _validate_response_artifact(
    response: Mapping[str, object], request: Mapping[str, object], name: str
) -> None:
    actual = _required_mapping(response, name)
    requested = _required_mapping(request, name)
    weights = _required_mapping(requested, "weights")
    expected = {
        "id": requested.get("id"),
        "revision": requested.get("revision"),
        "weights_digest": weights.get("digest"),
    }
    if actual != expected:
        raise ValueError(f"Kronos response {name} identity mismatch")


def _forecast_key(value: Mapping[str, object]) -> tuple[str, int, str, str]:
    fold_id = value.get("fold_id")
    row_id = value.get("row_id")
    instrument = value.get("instrument_id")
    decision = value.get("decision_time")
    if (
        not isinstance(fold_id, str)
        or isinstance(row_id, bool)
        or not isinstance(row_id, int)
        or not isinstance(instrument, str)
        or not isinstance(decision, str)
    ):
        raise ValueError("Kronos forecast identity schema mismatch")
    return fold_id, row_id, instrument, decision


def _eligibility_key(value: Mapping[str, object]) -> tuple[str, int]:
    fold_id = value.get("fold_id")
    row_id = value.get("row_id")
    if (
        not isinstance(fold_id, str)
        or isinstance(row_id, bool)
        or not isinstance(row_id, int)
    ):
        raise ValueError("Kronos eligibility identity schema mismatch")
    return fold_id, row_id


def _trade_concentration(instruments: object) -> float:
    if not isinstance(instruments, list):
        raise ValueError("instrument report schema mismatch")
    trades = [int(item["executed_trades"]) for item in instruments if isinstance(item, dict)]
    total = sum(trades)
    return 0.0 if total == 0 else max(trades) / total


def _canonical_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Kronos {name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Kronos {name} must be finite")
    return result


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _required_mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"{key} schema mismatch")
    return item


def _required_str(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} schema mismatch")
    return item


def _required_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{key} schema mismatch")
    return item


if __name__ == "__main__":
    raise SystemExit(main())

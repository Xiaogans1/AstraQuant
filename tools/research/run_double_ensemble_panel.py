"""Prepare and score an exact multi-instrument DoubleEnsemble experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

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
    _validate_response,
)
from tools.research.run_panel_executable_backtest import _instrument, _json_default

_CONTEXT_SCHEMA = "astraquant.double-ensemble-panel-context/v1"
_REPORT_SCHEMA = "astraquant.double-ensemble-panel-executable/v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-double-ensemble-panel")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("dataset_specs", nargs="+")
    prepare.add_argument("--data-root", required=True, type=Path)
    prepare.add_argument("--output-root", required=True, type=Path)
    prepare.add_argument("--minimum-train-timestamps", type=int, default=6000)
    prepare.add_argument("--test-timestamp-count", type=int, default=1500)
    prepare.add_argument("--fold-count", type=int, default=3)
    prepare.add_argument("--holding-bars", type=int, default=5)
    prepare.add_argument("--seed", type=int, default=7)
    prepare.add_argument("--commission-rate", type=Decimal, default=Decimal("0.00025"))
    prepare.add_argument("--minimum-edge", type=Decimal, default=Decimal("0"))

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--context", required=True, type=Path)
    evaluate.add_argument("--response", required=True, type=Path)
    evaluate.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "prepare":
            _prepare(arguments)
        else:
            _evaluate(arguments.context, arguments.response, arguments.output)
    except (OSError, ValueError, TypeError, ArithmeticError, json.JSONDecodeError) as error:
        print(f"DoubleEnsemble panel failed: {error}", file=sys.stderr)
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
        raise ValueError("all panel inputs must be Eastmoney snapshots")
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
    export = export_qlib_request(
        output_root=arguments.output_root / "export",
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
    context = {
        "schema_version": _CONTEXT_SCHEMA,
        "data_root": str(arguments.data_root.resolve()),
        "request_path": str(export.request_path.resolve()),
        "request_content_digest": export.content_digest,
        "sources": sources,
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


def _evaluate(context_path: Path, response_path: Path, output_path: Path) -> None:
    context = _read_json(context_path)
    if context.get("schema_version") != _CONTEXT_SCHEMA:
        raise ValueError("panel context schema mismatch")
    request_path = Path(_required_str(context, "request_path"))
    request = _read_json(request_path)
    response = _read_json(response_path)
    if request.get("content_digest") != context.get("request_content_digest"):
        raise ValueError("panel context request digest mismatch")
    _validate_response(response, request)
    panel, sources = _rebuild_panel(context)
    fold_policy = _required_mapping(context, "fold_policy")
    folds = panel_walk_forward(
        panel,
        minimum_train_timestamps=_required_int(fold_policy, "minimum_train_timestamps"),
        test_timestamp_count=_required_int(fold_policy, "test_timestamp_count"),
        fold_count=_required_int(fold_policy, "fold_count"),
        purge_timestamp_count=_required_int(fold_policy, "purge_timestamp_count"),
    )
    request_folds, fit_indices = _read_folds(request)
    if folds != request_folds:
        raise ValueError("rebuilt panel folds do not match frozen request")
    predictions = response.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("DoubleEnsemble predictions schema mismatch")
    ridge = _ridge_predictions(list(panel.rows), folds=folds, fit_indices=fit_indices)
    execution = _required_mapping(context, "execution_policy")
    commission_rate = Decimal(_required_str(execution, "commission_rate"))
    minimum_score = float(
        Decimal(2) * commission_rate + Decimal(_required_str(execution, "minimum_edge"))
    )
    policy = ExecutionPolicy(
        initial_cash=Decimal(_required_str(execution, "initial_cash")),
        commission_rate=commission_rate,
        minimum_commission=Decimal(_required_str(execution, "minimum_commission")),
        stamp_duty_rate=Decimal("0"),
        transfer_fee_rate=Decimal("0"),
        slippage_bps=Decimal(_required_str(execution, "slippage_bps")),
        participation_rate=Decimal(_required_str(execution, "participation_rate")),
        lot_size=_required_int(execution, "lot_size"),
        instrument_kind=InstrumentKind.ETF,
    )
    reports = {
        model_id: run_panel_executable_expected_returns(
            panel,
            folds=folds,
            predictions=model_predictions,
            minimum_score=minimum_score,
            holding_bars=_required_int(execution, "holding_bars"),
            policy=policy,
            model_id=model_id,
        )
        for model_id, model_predictions in (("RIDGE", ridge), ("DOUBLE_ENSEMBLE", predictions))
    }
    liquidity = _liquidity_buckets(panel)
    regimes = _fold_regimes(panel, folds)
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
        value["evidence_status"] = _evidence_status(report.executed_trades, report.net_return)
        models[model_id] = value
    body: dict[str, object] = {
        "schema_version": _REPORT_SCHEMA,
        "fidelity": "BAR_NEXT_OPEN_CONSERVATIVE",
        "sources": sources,
        "shared_contract": {
            "training_task_digest": request["training_task_digest"],
            "score_semantics": "EXPECTED_RETURN",
            "selection_minimum_score": minimum_score,
            "fold_policy": fold_policy,
            "execution_policy": execution,
            "regime_basis": "POST_HOC_MEAN_REALIZED_TEST_RETURN",
        },
        "models": models,
        "digests": {
            "input": request["content_digest"],
            "folds": _digest(request["folds"]),
            "predictions": _digest(predictions),
        },
    }
    body["digests"]["report"] = _digest(body)  # type: ignore[index]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _rebuild_panel(context: Mapping[str, object]) -> tuple[PanelDataset, list[dict[str, object]]]:
    raw_sources = context.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("panel context sources schema mismatch")
    data_root = Path(_required_str(context, "data_root"))
    execution = _required_mapping(context, "execution_policy")
    sources: list[dict[str, object]] = []
    instruments = []
    for source in raw_sources:
        if not isinstance(source, dict):
            raise ValueError("panel source schema mismatch")
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
                raise ValueError(f"rebuilt source {key} mismatch")
        sources.append(dict(source))
        instruments.append(_instrument(payload))
    return build_panel(tuple(instruments)), sources


def _dataset_spec(value: str) -> tuple[str, str]:
    dataset_id, separator, snapshot_id = value.rpartition("@")
    if not separator or not dataset_id or len(snapshot_id) != 64:
        raise ValueError("dataset spec must be dataset_id@64-char-snapshot-id")
    return dataset_id, snapshot_id


def _liquidity_buckets(panel: PanelDataset) -> dict[str, str]:
    values = {
        item.instrument_id: sum((bar.turnover for bar in item.raw_bars), start=Decimal("0"))
        / len(item.raw_bars)
        for item in panel.instruments
    }
    median = sorted(values.values())[(len(values) - 1) // 2]
    return {
        instrument: ("LOW" if value <= median else "HIGH")
        for instrument, value in values.items()
    }


def _fold_regimes(panel: PanelDataset, folds: Sequence[WalkForwardFold]) -> dict[str, str]:
    result = {}
    for fold in folds:
        fold_id = fold.fold_id
        indices = fold.test_indices
        mean_return = (
            sum(float(panel.rows[index]["future_return"]) for index in indices) / len(indices)
        )
        if mean_return > 0.001:
            result[fold_id] = "BULL"
        elif mean_return < -0.001:
            result[fold_id] = "BEAR"
        else:
            result[fold_id] = "SIDEWAYS"
    return result


def _evidence_status(trades: int, net_return: float) -> str:
    if trades < 30:
        return "INSUFFICIENT_EVIDENCE"
    return "CANDIDATE" if net_return > 0 else "NO_NET_EDGE"


def _digest(value: object) -> str:
    normalized = json.loads(json.dumps(value, default=_json_default))
    return f"sha256:{hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()}"


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

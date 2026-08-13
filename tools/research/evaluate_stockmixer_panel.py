"""Evaluate sealed StockMixer predictions with the shared executable ETF engine."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.baseline_matrix import WalkForwardFold
from astraquant_quant.executable_backtest import ExecutionPolicy, InstrumentKind
from astraquant_quant.panel_research import (
    PanelDataset,
    build_panel,
    run_panel_executable_expected_returns,
)
from tools.research.build_training_set import build_features_json
from tools.research.run_double_ensemble_panel import (
    _evidence_status,
    _fold_regimes,
    _liquidity_buckets,
)
from tools.research.run_panel_executable_backtest import _instrument, _json_default

_REQUEST_SCHEMA = "astraquant.stockmixer-request/v1"
_RESPONSE_SCHEMA = "astraquant.stockmixer-training-response/v1"
_REPORT_SCHEMA = "astraquant.stockmixer-panel-executable/v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evaluate-stockmixer-panel")
    parser.add_argument("request", type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--holding-bars", type=int, default=5)
    parser.add_argument("--minimum-score", type=float, default=0.0005)
    parser.add_argument("--initial-cash", type=Decimal, default=Decimal("100000"))
    parser.add_argument("--commission-rate", type=Decimal, default=Decimal("0.00025"))
    parser.add_argument("--minimum-commission", type=Decimal, default=Decimal("0"))
    parser.add_argument("--slippage-bps", type=Decimal, default=Decimal("2"))
    parser.add_argument("--participation-rate", type=Decimal, default=Decimal("0.10"))
    parser.add_argument("--lot-size", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        _evaluate(arguments)
    except (OSError, ValueError, TypeError, ArithmeticError, json.JSONDecodeError) as error:
        print(f"StockMixer evaluation failed: {error}", file=sys.stderr)
        return 1
    return 0


def _evaluate(arguments: argparse.Namespace) -> None:
    if arguments.output.exists():
        raise ValueError("output must not already exist")
    if arguments.holding_bars <= 0 or arguments.lot_size <= 0:
        raise ValueError("holding-bars and lot-size must be positive")
    if not math.isfinite(arguments.minimum_score):
        raise ValueError("minimum-score must be finite")
    request, samples = _load_request(arguments.request)
    instruments = tuple(_source_instruments(request))
    scores, artifact_digests = _load_artifacts(
        arguments.artifact_root,
        request=request,
        samples=samples,
        instruments=instruments,
    )
    panel, sources = _rebuild_panel(request, arguments.data_root, arguments.holding_bars)
    folds = _folds_from_samples(panel, samples)
    predictions = _map_predictions(panel, folds, scores)
    policy = ExecutionPolicy(
        initial_cash=arguments.initial_cash,
        commission_rate=arguments.commission_rate,
        minimum_commission=arguments.minimum_commission,
        stamp_duty_rate=Decimal("0"),
        transfer_fee_rate=Decimal("0"),
        slippage_bps=arguments.slippage_bps,
        participation_rate=arguments.participation_rate,
        lot_size=arguments.lot_size,
        instrument_kind=InstrumentKind.ETF,
    )
    report = run_panel_executable_expected_returns(
        panel,
        folds=folds,
        predictions=predictions,
        minimum_score=arguments.minimum_score,
        holding_bars=arguments.holding_bars,
        policy=policy,
        model_id="STOCKMIXER_DYNAMIC",
    )
    liquidity = _liquidity_buckets(panel)
    regimes = _fold_regimes(panel, folds)
    model = asdict(report)
    model["instruments"] = [
        {**item, "liquidity_bucket": liquidity[str(item["instrument_id"])]}
        for item in model["instruments"]
    ]
    model["folds"] = [
        {**item, "regime": regimes[str(item["fold_id"])]} for item in model["folds"]
    ]
    model["evidence_status"] = _evidence_status(report.executed_trades, report.net_return)
    execution = {
        "holding_bars": arguments.holding_bars,
        "minimum_score": arguments.minimum_score,
        "initial_cash": str(arguments.initial_cash),
        "commission_rate": str(arguments.commission_rate),
        "minimum_commission": str(arguments.minimum_commission),
        "slippage_bps": str(arguments.slippage_bps),
        "participation_rate": str(arguments.participation_rate),
        "lot_size": arguments.lot_size,
    }
    body: dict[str, object] = {
        "schema_version": _REPORT_SCHEMA,
        "fidelity": "BAR_NEXT_OPEN_CONSERVATIVE",
        "sources": sources,
        "shared_contract": {
            "score_semantics": "EXPECTED_RETURN",
            "execution_policy": execution,
            "outer_test_is_selection_locked": True,
            "regime_basis": "POST_HOC_MEAN_REALIZED_TEST_RETURN",
        },
        "model": model,
        "digests": {
            "request": request["content_digest"],
            "artifacts": _digest(artifact_digests),
            "predictions": _digest(predictions),
        },
    }
    body["digests"]["report"] = _digest(body)  # type: ignore[index]
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _load_request(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    request = _read_json(path)
    if request.get("schema_version") != _REQUEST_SCHEMA:
        raise ValueError("StockMixer request schema mismatch")
    if request.get("provider_id") != "eastmoney":
        raise ValueError("StockMixer evaluation requires Eastmoney request")
    supplied = request.get("content_digest")
    body = {key: value for key, value in request.items() if key != "content_digest"}
    if supplied != _digest(body):
        raise ValueError("StockMixer request content digest mismatch")
    request_files = (("panel_file", "panel.parquet"), ("samples_file", "samples.parquet"))
    for key, expected_path in request_files:
        value = request.get(key)
        if not isinstance(value, dict) or value.get("path") != expected_path:
            raise ValueError(f"StockMixer {key} schema mismatch")
        file_path = path.parent / expected_path
        if value.get("digest") != _file_digest(file_path):
            raise ValueError(f"StockMixer {key} digest mismatch")
    samples = pq.read_table(path.parent / "samples.parquet").to_pylist()
    if len(samples) != request.get("sample_count"):
        raise ValueError("StockMixer samples coverage mismatch")
    return request, samples


def _load_artifacts(
    root: Path,
    *,
    request: Mapping[str, object],
    samples: list[dict[str, Any]],
    instruments: tuple[str, ...],
) -> tuple[dict[tuple[str, int, str], float], list[dict[str, object]]]:
    folds = tuple(sorted({str(item["fold_id"]) for item in samples}))
    expected = {
        (
            str(sample["fold_id"]),
            round(sample["decision_time"].timestamp() * 1_000_000),
            instrument,
        )
        for sample in samples
        if sample["segment"] == "test"
        for instrument in instruments
    }
    scores: dict[tuple[str, int, str], float] = {}
    evidence = []
    shared_training_digest: str | None = None
    shared_code_digest: str | None = None
    for fold_id in folds:
        fold_root = root / fold_id
        response_path = fold_root / "response.json"
        response = _read_json(response_path)
        if response.get("schema_version") != _RESPONSE_SCHEMA:
            raise ValueError("StockMixer response schema mismatch")
        supplied = response.get("content_digest")
        body = {key: value for key, value in response.items() if key != "content_digest"}
        if supplied != _digest(body):
            raise ValueError("StockMixer response content digest mismatch")
        if response.get("request_content_digest") != request.get("content_digest"):
            raise ValueError("StockMixer response request digest mismatch")
        if response.get("fold_id") != fold_id:
            raise ValueError("StockMixer response fold mismatch")
        training_digest = _required_digest(response, "training_config_digest")
        code_digest = _required_digest(response, "code_digest")
        if shared_training_digest is None:
            shared_training_digest = training_digest
            shared_code_digest = code_digest
        elif (training_digest, code_digest) != (shared_training_digest, shared_code_digest):
            raise ValueError("StockMixer folds do not share training and code identity")
        files = response.get("files")
        if not isinstance(files, dict):
            raise ValueError("StockMixer response files schema mismatch")
        prediction_meta = files.get("predictions")
        model_meta = files.get("model")
        if (
            not isinstance(prediction_meta, dict)
            or prediction_meta.get("path") != "predictions.parquet"
            or not isinstance(model_meta, dict)
            or model_meta.get("path") != "model-state.bin"
        ):
            raise ValueError("StockMixer response file paths mismatch")
        prediction_path = fold_root / "predictions.parquet"
        model_path = fold_root / "model-state.bin"
        if prediction_meta.get("digest") != _file_digest(prediction_path):
            raise ValueError("StockMixer predictions digest mismatch")
        if model_meta.get("digest") != _file_digest(model_path):
            raise ValueError("StockMixer model digest mismatch")
        table = pq.read_table(prediction_path)
        if table.column_names != [
            "fold_id",
            "sample_id",
            "decision_time_us",
            "instrument_id",
            "score",
        ]:
            raise ValueError("StockMixer prediction columns mismatch")
        for row in table.to_pylist():
            key = (str(row["fold_id"]), int(row["decision_time_us"]), str(row["instrument_id"]))
            score = row["score"]
            if (
                key[0] != fold_id
                or key in scores
                or isinstance(score, bool)
                or not isinstance(score, int | float)
                or not math.isfinite(float(score))
            ):
                raise ValueError("StockMixer prediction row schema or identity mismatch")
            scores[key] = float(score)
        evidence.append(
            {
                "fold_id": fold_id,
                "response": str(supplied),
                "model": str(model_meta["digest"]),
                "predictions": str(prediction_meta["digest"]),
            }
        )
    if set(scores) != expected:
        raise ValueError("StockMixer prediction coverage mismatch")
    return scores, evidence


def _rebuild_panel(
    request: Mapping[str, object], data_root: Path, holding_bars: int
) -> tuple[PanelDataset, list[dict[str, object]]]:
    raw_sources = request.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("StockMixer request sources schema mismatch")
    sources: list[dict[str, object]] = []
    instruments = []
    for raw in raw_sources:
        if not isinstance(raw, dict):
            raise ValueError("StockMixer source must be an object")
        dataset_id = _required_text(raw, "dataset_id")
        snapshot_id = _required_text(raw, "source_snapshot_id")
        payload = build_features_json(
            data_root,
            dataset_id,
            horizon=holding_bars,
            threshold=Decimal("0.005"),
            snapshot_id=snapshot_id.removeprefix("sha256:"),
        )
        for key in ("dataset_id", "instrument_id"):
            if payload.get(key) != raw.get(key):
                raise ValueError(f"rebuilt StockMixer source {key} mismatch")
        if str(payload.get("source_snapshot_id", "")).removeprefix("sha256:") != (
            snapshot_id.removeprefix("sha256:")
        ):
            raise ValueError("rebuilt StockMixer source source_snapshot_id mismatch")
        if payload.get("provider_id") != "eastmoney":
            raise ValueError("rebuilt StockMixer source is not Eastmoney")
        sources.append(
            {
                **dict(raw),
                "provider_id": "eastmoney",
                "bar_count": payload["bar_count"],
                "row_count": payload["row_count"],
                "date_range": payload["date_range"],
            }
        )
        instruments.append(_instrument(payload))
    return build_panel(tuple(instruments)), sources


def _folds_from_samples(
    panel: PanelDataset, samples: list[dict[str, Any]]
) -> tuple[WalkForwardFold, ...]:
    folds = []
    for fold_id in sorted({str(item["fold_id"]) for item in samples}):
        train_times = {
            item["decision_time"]
            for item in samples
            if item["fold_id"] == fold_id and item["segment"] == "train"
        }
        test_times = {
            item["decision_time"]
            for item in samples
            if item["fold_id"] == fold_id and item["segment"] == "test"
        }
        if not train_times or not test_times or max(train_times) >= min(test_times):
            raise ValueError("StockMixer fold time coverage mismatch")
        folds.append(
            WalkForwardFold(
                fold_id=fold_id,
                train_indices=tuple(
                    index
                    for index, observation in enumerate(panel.observations)
                    if observation.timestamp in train_times
                ),
                test_indices=tuple(
                    index
                    for index, observation in enumerate(panel.observations)
                    if observation.timestamp in test_times
                ),
            )
        )
    if any(not fold.train_indices or not fold.test_indices for fold in folds):
        raise ValueError("rebuilt StockMixer fold contains no panel observations")
    return tuple(folds)


def _map_predictions(
    panel: PanelDataset,
    folds: tuple[WalkForwardFold, ...],
    scores: Mapping[tuple[str, int, str], float],
) -> tuple[dict[str, object], ...]:
    predictions = []
    for fold in folds:
        for row_id in fold.test_indices:
            observation = panel.observations[row_id]
            key = (
                fold.fold_id,
                round(observation.timestamp.timestamp() * 1_000_000),
                observation.instrument_id,
            )
            if key not in scores:
                raise ValueError("StockMixer predictions omit an executable panel row")
            predictions.append(
                {"fold_id": fold.fold_id, "row_id": row_id, "score": scores[key]}
            )
    return tuple(predictions)


def _source_instruments(request: Mapping[str, object]) -> list[str]:
    sources = request.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("StockMixer request sources schema mismatch")
    values = [
        _required_text(source, "instrument_id")
        for source in sources
        if isinstance(source, dict)
    ]
    if len(values) != len(sources) or values != sorted(set(values)):
        raise ValueError("StockMixer source instruments are not canonical")
    return values


def _required_text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be non-empty text")
    return item


def _required_digest(value: Mapping[str, object], key: str) -> str:
    item = _required_text(value, key)
    if len(item) != 71 or not item.startswith("sha256:"):
        raise ValueError(f"{key} must be an exact SHA-256 digest")
    return item


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _digest(value: object) -> str:
    normalized = json.loads(json.dumps(value, default=_json_default))
    return f"sha256:{hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()}"


if __name__ == "__main__":
    raise SystemExit(main())

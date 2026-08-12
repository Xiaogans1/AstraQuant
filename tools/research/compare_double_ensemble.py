"""Compare DoubleEnsemble with Ridge under one expected-return score contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]
from sklearn.linear_model import Ridge  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from astraquant_data.exports.qlib import QLIB_UPSTREAM_COMMIT
from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.baseline_matrix import (
    PredictionSummary,
    WalkForwardFold,
    score_expected_return_predictions,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compare-double-ensemble")
    parser.add_argument("request_json", type=Path)
    parser.add_argument("qlib_response_json", type=Path)
    parser.add_argument("--minimum-edge", type=Decimal, default=Decimal("0"))
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        request = _read_json(arguments.request_json)
        response = _read_json(arguments.qlib_response_json)
        _validate_request(request)
        _validate_response(response, request)
        rows = _read_rows(arguments.request_json.parent, request)
        folds, fit_indices = _read_folds(request)
        fee_rate = Decimal(_required_str(request, "fee_rate"))
        predictions = response.get("predictions")
        if not isinstance(predictions, list):
            raise ValueError("DoubleEnsemble predictions schema mismatch")
        challenger = score_expected_return_predictions(
            rows,
            folds=folds,
            predictions=predictions,
            fee_rate=fee_rate,
            minimum_edge=arguments.minimum_edge,
        )
        ridge_predictions = _ridge_predictions(
            rows,
            folds=folds,
            fit_indices=fit_indices,
        )
        ridge = score_expected_return_predictions(
            rows,
            folds=folds,
            predictions=ridge_predictions,
            fee_rate=fee_rate,
            minimum_edge=arguments.minimum_edge,
        )
        challenger_values = _summary(challenger)
        ridge_values = _summary(ridge)
        selection_cutoff = Decimal(2) * fee_rate + arguments.minimum_edge
        output = {
            "schema_version": "astraquant.double-ensemble-comparison/v1",
            "shared_contract": {
                "dataset_id": request["dataset_id"],
                "source_snapshot_id": request["source_snapshot_id"],
                "training_task_digest": request["training_task_digest"],
                "score_semantics": "EXPECTED_RETURN",
                "fold_count": len(folds),
                "test_rows": sum(len(fold.test_indices) for fold in folds),
                "selection_policy": {
                    "kind": "EXPECTED_RETURN_GTE_ROUND_TRIP_FEE_PLUS_EDGE",
                    "minimum_edge": str(arguments.minimum_edge),
                    "selection_cutoff": str(selection_cutoff),
                },
                "scoring_fidelity": "RESEARCH_RETURN_ONLY",
            },
            "ridge": ridge_values,
            "double_ensemble": challenger_values,
            "delta_double_ensemble_minus_ridge": {
                name: challenger_values[name] - ridge_values[name]
                for name in ("auc", "gross_return", "net_return", "trades")
            },
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError, ArithmeticError) as error:
        print(f"DoubleEnsemble comparison failed: {error}", file=sys.stderr)
        return 1
    return 0


def _validate_request(request: dict[str, Any]) -> None:
    if request.get("schema_version") != "astraquant.qlib-request/v1":
        raise ValueError("Qlib request schema mismatch")
    supplied = _required_str(request, "content_digest")
    body = {key: value for key, value in request.items() if key != "content_digest"}
    actual = f"sha256:{hashlib.sha256(canonical_json_bytes(body)).hexdigest()}"
    if supplied != actual:
        raise ValueError("Qlib request content digest mismatch")
    if request.get("upstream_commit") != QLIB_UPSTREAM_COMMIT:
        raise ValueError("Qlib request commit mismatch")
    if (
        request.get("model_kind") != "DOUBLE_ENSEMBLE"
        or request.get("target_column") != "future_return"
        or request.get("score_semantics") != "EXPECTED_RETURN"
        or request.get("prediction_threshold") is not None
    ):
        raise ValueError("DoubleEnsemble request semantics mismatch")


def _validate_response(response: dict[str, Any], request: dict[str, Any]) -> None:
    if response.get("schema_version") != "astraquant.qlib-response/v1":
        raise ValueError("Qlib response schema mismatch")
    for key in ("upstream_commit", "model_kind", "score_semantics", "training_task_digest"):
        expected = request.get(key)
        if key == "upstream_commit":
            expected = QLIB_UPSTREAM_COMMIT
        if response.get(key) != expected:
            raise ValueError(f"Qlib response {key} mismatch")
    if response.get("request_content_digest") != request.get("content_digest"):
        raise ValueError("Qlib response belongs to another request")


def _read_rows(root: Path, request: dict[str, Any]) -> list[dict[str, float | int]]:
    rows_file = request.get("rows_file")
    if not isinstance(rows_file, dict) or rows_file.get("path") != "rows.parquet":
        raise ValueError("Qlib rows file schema mismatch")
    path = root / "rows.parquet"
    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    if rows_file.get("digest") != digest:
        raise ValueError("Qlib rows digest mismatch")
    rows = pq.read_table(path).to_pylist()
    if len(rows) != request.get("row_count"):
        raise ValueError("Qlib row count mismatch")
    result: list[dict[str, float | int]] = []
    for row_id, raw in enumerate(rows):
        if raw.pop("row_id", None) != row_id:
            raise ValueError("Qlib row identity mismatch")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in raw.values()
        ):
            raise ValueError("Qlib row value schema mismatch")
        result.append(raw)
    return result


def _read_folds(
    request: dict[str, Any],
) -> tuple[tuple[WalkForwardFold, ...], dict[str, tuple[int, ...]]]:
    values = request.get("folds")
    if not isinstance(values, list) or not values:
        raise ValueError("Qlib folds schema mismatch")
    folds = []
    fit_indices = {}
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Qlib fold schema mismatch")
        fold_id = _required_str(value, "fold_id")
        train = _required_indices(value, "train_indices")
        fit = _required_indices(value, "fit_indices")
        validation = _required_indices(value, "validation_indices")
        test = _required_indices(value, "test_indices")
        if (*fit, *validation) != train:
            raise ValueError(f"Qlib inner validation split mismatch: {fold_id}")
        folds.append(WalkForwardFold(fold_id, train, test))
        fit_indices[fold_id] = fit
    return tuple(folds), fit_indices


def _ridge_predictions(
    rows: list[dict[str, float | int]],
    *,
    folds: tuple[WalkForwardFold, ...],
    fit_indices: dict[str, tuple[int, ...]],
) -> list[dict[str, object]]:
    feature_columns = [key for key in rows[0] if key not in {"label", "future_return"}]
    predictions: list[dict[str, object]] = []
    for fold in folds:
        fit = fit_indices[fold.fold_id]
        estimator = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        estimator.fit(
            [[float(rows[index][name]) for name in feature_columns] for index in fit],
            [float(rows[index]["future_return"]) for index in fit],
        )
        scores = estimator.predict(
            [[float(rows[index][name]) for name in feature_columns] for index in fold.test_indices]
        )
        predictions.extend(
            {"fold_id": fold.fold_id, "row_id": row_id, "score": float(score)}
            for row_id, score in zip(fold.test_indices, scores, strict=True)
        )
    return predictions


def _summary(value: PredictionSummary) -> dict[str, float | int]:
    return {
        "auc": value.auc,
        "gross_return": value.gross_return,
        "net_return": value.net_return,
        "trades": value.trades,
        "positive_folds": value.positive_folds,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _required_str(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} schema mismatch")
    return item


def _required_indices(value: dict[str, Any], key: str) -> tuple[int, ...]:
    item = value.get(key)
    if (
        not isinstance(item, list)
        or not item
        or any(isinstance(index, bool) or not isinstance(index, int) for index in item)
    ):
        raise ValueError(f"{key} schema mismatch")
    return tuple(item)


if __name__ == "__main__":
    raise SystemExit(main())

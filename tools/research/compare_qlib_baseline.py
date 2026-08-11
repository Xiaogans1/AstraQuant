"""Compare pinned Qlib predictions with native LightGBM under one score contract."""

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

from astraquant_data.exports.qlib import QLIB_UPSTREAM_COMMIT
from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.baseline_matrix import (
    PredictionSummary,
    WalkForwardFold,
    score_fold_predictions,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compare-qlib-baseline")
    parser.add_argument("request_json", type=Path)
    parser.add_argument("qlib_response_json", type=Path)
    parser.add_argument("native_report_json", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        request = _read_json(arguments.request_json)
        response = _read_json(arguments.qlib_response_json)
        native = _read_json(arguments.native_report_json)
        _validate_request(request)
        _validate_response(response, request)
        folds = _request_folds(request)
        rows = _request_rows(arguments.request_json.parent, request)
        fee_rate = Decimal(_required_str(request, "fee_rate"))
        threshold = _required_number(request, "prediction_threshold")
        predictions = response.get("predictions")
        if not isinstance(predictions, list):
            raise ValueError("Qlib response predictions schema mismatch")
        qlib = score_fold_predictions(
            rows,
            folds=folds,
            predictions=predictions,
            fee_rate=fee_rate,
            prediction_threshold=threshold,
        )
        native_lightgbm = _native_lightgbm(native, request, folds)
        qlib_values = _summary(qlib)
        output = {
            "schema_version": "astraquant.qlib-comparison/v1",
            "shared_contract": {
                "dataset_id": request["dataset_id"],
                "source_snapshot_id": request["source_snapshot_id"],
                "fee_rate": str(fee_rate),
                "prediction_threshold": threshold,
                "fold_count": len(folds),
                "test_rows": sum(len(fold.test_indices) for fold in folds),
            },
            "native_lightgbm": native_lightgbm,
            "qlib_lightgbm": qlib_values,
            "delta_qlib_minus_native": {
                name: qlib_values[name] - native_lightgbm[name]
                for name in ("auc", "gross_return", "net_return", "trades")
            },
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError, ArithmeticError) as error:
        print(f"Qlib comparison failed: {error}", file=sys.stderr)
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


def _validate_response(response: dict[str, Any], request: dict[str, Any]) -> None:
    if response.get("schema_version") != "astraquant.qlib-response/v1":
        raise ValueError("Qlib response schema mismatch")
    if response.get("upstream_commit") != QLIB_UPSTREAM_COMMIT:
        raise ValueError("Qlib response commit mismatch")
    if response.get("request_content_digest") != request["content_digest"]:
        raise ValueError("Qlib response belongs to another request")


def _request_rows(root: Path, request: dict[str, Any]) -> list[dict[str, float | int]]:
    rows_file = request.get("rows_file")
    if not isinstance(rows_file, dict) or rows_file.get("path") != "rows.parquet":
        raise ValueError("Qlib rows file schema mismatch")
    path = root / "rows.parquet"
    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    if rows_file.get("digest") != digest:
        raise ValueError("Qlib rows digest mismatch")
    raw_rows = pq.read_table(path).to_pylist()
    rows: list[dict[str, float | int]] = []
    for row_id, raw in enumerate(raw_rows):
        if raw.get("row_id") != row_id:
            raise ValueError("Qlib row identity mismatch")
        row: dict[str, float | int] = {}
        for key, value in raw.items():
            if key == "row_id":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Qlib row value schema mismatch")
            if not math.isfinite(float(value)):
                raise ValueError("Qlib row values must be finite")
            row[str(key)] = value
        rows.append(row)
    if len(rows) != request.get("row_count"):
        raise ValueError("Qlib row count mismatch")
    return rows


def _request_folds(request: dict[str, Any]) -> tuple[WalkForwardFold, ...]:
    values = request.get("folds")
    if not isinstance(values, list) or not values:
        raise ValueError("Qlib folds schema mismatch")
    folds = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Qlib fold schema mismatch")
        folds.append(
            WalkForwardFold(
                fold_id=_required_str(value, "fold_id"),
                train_indices=_required_indices(value, "train_indices"),
                test_indices=_required_indices(value, "test_indices"),
            )
        )
    return tuple(folds)


def _native_lightgbm(
    native: dict[str, Any],
    request: dict[str, Any],
    folds: tuple[WalkForwardFold, ...],
) -> dict[str, float | int]:
    if native.get("schema_version") != "astraquant.strategy-baseline-matrix/v1":
        raise ValueError("native baseline schema mismatch")
    for key in ("dataset_id", "source_snapshot_id", "provider_id", "seed"):
        if native.get(key) != request.get(key):
            raise ValueError(f"native baseline {key} mismatch")
    if str(native.get("fee_rate")) != _required_str(request, "fee_rate"):
        raise ValueError("native baseline fee rate mismatch")
    if native.get("prediction_threshold") != request.get("prediction_threshold"):
        raise ValueError("native baseline prediction threshold mismatch")
    models = native.get("models")
    if not isinstance(models, list):
        raise ValueError("native baseline models schema mismatch")
    matches = [
        model for model in models if isinstance(model, dict) and model.get("model") == "LIGHTGBM"
    ]
    if len(matches) != 1:
        raise ValueError("native baseline must contain exactly one LIGHTGBM result")
    model = matches[0]
    native_folds = model.get("folds")
    expected = [(fold.fold_id, len(fold.test_indices)) for fold in folds]
    if (
        not isinstance(native_folds, list)
        or [
            (fold.get("fold_id"), fold.get("test_rows"))
            for fold in native_folds
            if isinstance(fold, dict)
        ]
        != expected
    ):
        raise ValueError("native baseline fold coverage mismatch")
    return {
        "auc": _required_number(model, "auc"),
        "gross_return": _required_number(model, "gross_return"),
        "net_return": _required_number(model, "net_return"),
        "trades": _required_int(model, "trades"),
        "positive_folds": _required_int(model, "positive_folds"),
    }


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


def _required_indices(value: dict[str, Any], key: str) -> tuple[int, ...]:
    item = value.get(key)
    if (
        not isinstance(item, list)
        or not item
        or any(isinstance(index, bool) or not isinstance(index, int) for index in item)
    ):
        raise ValueError(f"{key} schema mismatch")
    return tuple(item)


def _required_str(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} schema mismatch")
    return item


def _required_number(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
        raise ValueError(f"{key} schema mismatch")
    return float(item)


def _required_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{key} schema mismatch")
    return item


if __name__ == "__main__":
    raise SystemExit(main())

"""Score Alpha158 predictions against the existing ten-feature LightGBM result."""

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
from astraquant_data.exports.qlib_alpha158 import ALPHA158_CONFIG_DIGEST
from astraquant_domain.run_manifest import canonical_json_bytes
from astraquant_quant.baseline_matrix import score_fold_predictions
from tools.research.compare_qlib_baseline import (
    _native_lightgbm,
    _read_json,
    _request_folds,
    _required_number,
    _required_str,
    _summary,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compare-alpha158")
    parser.add_argument("request_json", type=Path)
    parser.add_argument("alpha158_response_json", type=Path)
    parser.add_argument("native_report_json", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        request = _read_json(arguments.request_json)
        response = _read_json(arguments.alpha158_response_json)
        native = _read_json(arguments.native_report_json)
        _validate_request(request)
        _validate_response(response, request)
        folds = _request_folds(request)
        rows = _rows(arguments.request_json.parent, request)
        predictions = response.get("predictions")
        if not isinstance(predictions, list):
            raise ValueError("Alpha158 response predictions schema mismatch")
        fee_rate = Decimal(_required_str(request, "fee_rate"))
        threshold = _required_number(request, "prediction_threshold")
        alpha = score_fold_predictions(
            rows,
            folds=folds,
            predictions=predictions,
            fee_rate=fee_rate,
            prediction_threshold=threshold,
        )
        astra10 = _native_lightgbm(native, request, folds)
        alpha_values = _summary(alpha)
        output = {
            "schema_version": "astraquant.alpha158-comparison/v1",
            "shared_contract": {
                "dataset_id": request["dataset_id"],
                "source_snapshot_id": request["source_snapshot_id"],
                "fee_rate": str(fee_rate),
                "prediction_threshold": threshold,
                "fold_count": len(folds),
                "test_rows": sum(len(fold.test_indices) for fold in folds),
                "alpha158_feature_count": 158,
            },
            "astra10_lightgbm": astra10,
            "alpha158_lightgbm": alpha_values,
            "alpha158_minus_astra10": {
                name: alpha_values[name] - astra10[name]
                for name in ("auc", "gross_return", "net_return", "trades")
            },
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError, ArithmeticError) as error:
        print(f"Alpha158 comparison failed: {error}", file=sys.stderr)
        return 1
    return 0


def _validate_request(request: dict[str, Any]) -> None:
    if request.get("schema_version") != "astraquant.qlib-alpha158-request/v1":
        raise ValueError("Alpha158 request schema mismatch")
    if request.get("upstream_commit") != QLIB_UPSTREAM_COMMIT:
        raise ValueError("Alpha158 request commit mismatch")
    if request.get("alpha158_config_digest") != ALPHA158_CONFIG_DIGEST:
        raise ValueError("Alpha158 request config mismatch")
    supplied = _required_str(request, "content_digest")
    body = {key: value for key, value in request.items() if key != "content_digest"}
    actual = f"sha256:{hashlib.sha256(canonical_json_bytes(body)).hexdigest()}"
    if supplied != actual:
        raise ValueError("Alpha158 request content digest mismatch")


def _validate_response(response: dict[str, Any], request: dict[str, Any]) -> None:
    if response.get("schema_version") != "astraquant.qlib-alpha158-response/v1":
        raise ValueError("Alpha158 response schema mismatch")
    if response.get("request_content_digest") != request["content_digest"]:
        raise ValueError("Alpha158 response belongs to another request")
    if response.get("upstream_commit") != QLIB_UPSTREAM_COMMIT:
        raise ValueError("Alpha158 response commit mismatch")
    if response.get("alpha158_config_digest") != ALPHA158_CONFIG_DIGEST:
        raise ValueError("Alpha158 response config mismatch")


def _rows(root: Path, request: dict[str, Any]) -> list[dict[str, float | int]]:
    rows_file = request.get("rows_file")
    if not isinstance(rows_file, dict) or rows_file.get("path") != "rows.parquet":
        raise ValueError("Alpha158 rows file schema mismatch")
    path = root / "rows.parquet"
    if rows_file.get("digest") != f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}":
        raise ValueError("Alpha158 rows digest mismatch")
    values = pq.read_table(path).to_pylist()
    rows: list[dict[str, float | int]] = []
    for row_id, value in enumerate(values):
        if value.pop("row_id", None) != row_id:
            raise ValueError("Alpha158 row identity mismatch")
        row: dict[str, float | int] = {}
        for key, item in value.items():
            if (
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(item)
            ):
                raise ValueError("Alpha158 row value schema mismatch")
            row[str(key)] = item
        rows.append(row)
    if len(rows) != request.get("row_count"):
        raise ValueError("Alpha158 row count mismatch")
    return rows


if __name__ == "__main__":
    raise SystemExit(main())

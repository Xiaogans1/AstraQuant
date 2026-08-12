"""Pinned Qlib runner consuming AstraQuant's deterministic export contract."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from .dataset import AstraFoldDataset
from .models import create_double_ensemble_model

QLIB_UPSTREAM_COMMIT = "79633dd9506ea689e5400dea0197717b5b3d74b7"
REQUEST_SCHEMA = "astraquant.qlib-request/v1"
RESPONSE_SCHEMA = "astraquant.qlib-response/v1"
MODEL_LIGHTGBM_BINARY = "LIGHTGBM_BINARY"
MODEL_DOUBLE_ENSEMBLE = "DOUBLE_ENSEMBLE"

_TRACKING_ROOT: tempfile.TemporaryDirectory[str] | None = None
_QLIB_INITIALIZED = False


def run_request(request_path: Path, output_path: Path) -> dict[str, Any]:
    """Run fixed Qlib LightGBM folds and atomically publish prediction JSON."""
    request = _read_request(request_path)
    frame = _read_rows(request_path.parent, request)
    _ensure_qlib_initialized()

    from qlib.contrib.model.gbdt import LGBModel
    from qlib.workflow import R

    predictions: list[dict[str, object]] = []
    seed = _require_int(request, "seed")
    model_kind = _require_str(request, "model_kind")
    target_column = _require_str(request, "target_column")
    score_semantics = _require_str(request, "score_semantics")
    training_task_digest = _require_digest(request, "training_task_digest")
    if (model_kind, target_column, score_semantics) not in {
        (MODEL_LIGHTGBM_BINARY, "label", "PROBABILITY"),
        (MODEL_DOUBLE_ENSEMBLE, "future_return", "EXPECTED_RETURN"),
    }:
        raise ValueError("unsupported Qlib model/target/score contract")
    for fold in _require_list(request, "folds"):
        if not isinstance(fold, dict):
            raise ValueError("fold schema mismatch")
        fold_id = _require_str(fold, "fold_id")
        train_indices = _indices(fold, "train_indices", len(frame))
        test_indices = _indices(fold, "test_indices", len(frame))
        if set(train_indices) & set(test_indices) or max(train_indices) >= min(test_indices):
            raise ValueError(f"invalid fold: {fold_id}")
        fit_indices = train_indices
        valid_indices = None
        if model_kind == MODEL_DOUBLE_ENSEMBLE:
            validation_policy = request.get("validation_policy")
            if validation_policy != {
                "kind": "TRAIN_TAIL_FRACTION",
                "fraction": "0.2",
            }:
                raise ValueError("DoubleEnsemble validation_policy schema mismatch")
            fit_indices = _indices(fold, "fit_indices", len(frame))
            valid_indices = _indices(fold, "validation_indices", len(frame))
            expected_validation_count = math.ceil(len(train_indices) * 0.2)
            if (
                [*fit_indices, *valid_indices] != train_indices
                or set(fit_indices) & set(valid_indices)
                or max(fit_indices) >= min(valid_indices)
                or len(valid_indices) != expected_validation_count
            ):
                raise ValueError(f"invalid DoubleEnsemble validation split: {fold_id}")
        dataset = AstraFoldDataset(
            frame,
            feature_columns=_require_string_list(request, "feature_columns"),
            target_column=target_column,
            train_indices=fit_indices,
            valid_indices=valid_indices,
            test_indices=test_indices,
        )
        if model_kind == MODEL_LIGHTGBM_BINARY:
            model = LGBModel(
                loss="binary",
                learning_rate=0.05,
                num_leaves=15,
                max_depth=4,
                min_data_in_leaf=2,
                min_data_in_bin=1,
                feature_fraction=1.0,
                bagging_fraction=1.0,
                bagging_freq=0,
                seed=seed,
                feature_fraction_seed=seed,
                bagging_seed=seed,
                data_random_seed=seed,
                deterministic=True,
                force_col_wise=True,
                num_threads=1,
                num_boost_round=40,
                early_stopping_rounds=0,
            )
            model_identity = "qlib.contrib.model.gbdt.LGBModel"
        else:
            model_config = request.get("model_config")
            if not isinstance(model_config, dict):
                raise ValueError("DoubleEnsemble model_config schema mismatch")
            model = create_double_ensemble_model(model_config, seed=seed)
            model_identity = "qlib.contrib.model.double_ensemble.DEnsembleModel"
        with R.start(experiment_name="AstraQuantQlibRunner"), warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message="Only training set found, disabling early stopping."
            )
            if model_kind == MODEL_LIGHTGBM_BINARY:
                model.fit(dataset, verbose_eval=0)
            else:
                model.fit(dataset)
        values = model.predict(dataset, segment="test")
        if list(values.index) != test_indices:
            raise ValueError(f"Qlib prediction row order mismatch: {fold_id}")
        value_key = "probability" if score_semantics == "PROBABILITY" else "score"
        predictions.extend(
            {"fold_id": fold_id, "row_id": row_id, value_key: float(value)}
            for row_id, value in values.items()
        )

    response: dict[str, Any] = {
        "schema_version": RESPONSE_SCHEMA,
        "request_content_digest": _require_str(request, "content_digest"),
        "upstream_commit": QLIB_UPSTREAM_COMMIT,
        "model": model_identity,
        "model_kind": model_kind,
        "score_semantics": score_semantics,
        "training_task_digest": training_task_digest,
        "predictions": predictions,
    }
    encoded = _canonical_bytes(response) + b"\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(output_path)
    return response


def _read_request(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Qlib request JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("request schema mismatch")
    if value.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("request schema mismatch")
    if value.get("upstream_commit") != QLIB_UPSTREAM_COMMIT:
        raise ValueError("upstream commit mismatch")
    supplied_digest = _require_str(value, "content_digest")
    body = {key: item for key, item in value.items() if key != "content_digest"}
    if supplied_digest != _digest(_canonical_bytes(body)):
        raise ValueError("request content digest mismatch")
    if value.get("provider_id") != "eastmoney":
        raise ValueError("provider must be eastmoney")
    return value


def _read_rows(root: Path, request: dict[str, Any]) -> pd.DataFrame:
    rows_file = request.get("rows_file")
    if not isinstance(rows_file, dict) or rows_file.get("path") != "rows.parquet":
        raise ValueError("rows file schema mismatch")
    rows_path = root / "rows.parquet"
    if not rows_path.is_file() or _digest(rows_path.read_bytes()) != rows_file.get("digest"):
        raise ValueError("rows digest mismatch")
    frame = pq.read_table(rows_path).to_pandas()
    features = _require_string_list(request, "feature_columns")
    expected = ["row_id", *features, "label", "future_return"]
    if list(frame.columns) != expected or len(frame) != _require_int(request, "row_count"):
        raise ValueError("rows schema mismatch")
    if frame["row_id"].tolist() != list(range(len(frame))):
        raise ValueError("row identity mismatch")
    if not set(frame["label"].tolist()).issubset({0, 1}):
        raise ValueError("labels must be binary")
    numeric = frame.loc[:, [*features, "future_return"]]
    if not numeric.map(math.isfinite).to_numpy().all():
        raise ValueError("rows must contain finite values")
    return frame.set_index("row_id", drop=True)


def _ensure_qlib_initialized() -> None:
    global _QLIB_INITIALIZED, _TRACKING_ROOT
    if _QLIB_INITIALIZED:
        return
    import qlib

    _TRACKING_ROOT = tempfile.TemporaryDirectory(prefix="astraquant-qlib-")
    root = Path(_TRACKING_ROOT.name)
    provider = root / "provider"
    provider.mkdir()
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    qlib.init(
        provider_uri=str(provider),
        kernels=1,
        logging_level=logging.ERROR,
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {
                "uri": (root / "mlruns").as_uri(),
                "default_exp_name": "AstraQuantQlibRunner",
            },
        },
    )
    _QLIB_INITIALIZED = True


def _indices(value: dict[str, Any], key: str, row_count: int) -> list[int]:
    indices = value.get(key)
    if (
        not isinstance(indices, list)
        or not indices
        or any(isinstance(item, bool) or not isinstance(item, int) for item in indices)
        or len(indices) != len(set(indices))
        or min(indices) < 0
        or max(indices) >= row_count
    ):
        raise ValueError(f"invalid {key}")
    return indices


def _require_list(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key)
    if not isinstance(item, list) or not item:
        raise ValueError(f"{key} schema mismatch")
    return item


def _require_string_list(value: dict[str, Any], key: str) -> list[str]:
    item = _require_list(value, key)
    if any(not isinstance(entry, str) or not entry for entry in item):
        raise ValueError(f"{key} schema mismatch")
    return item


def _require_str(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} schema mismatch")
    return item


def _require_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{key} schema mismatch")
    return item


def _require_digest(value: dict[str, Any], key: str) -> str:
    item = _require_str(value, key)
    if (
        not item.startswith("sha256:")
        or len(item) != len("sha256:") + 64
        or any(character not in "0123456789abcdef" for character in item[7:])
        or set(item[7:]) == {"0"}
    ):
        raise ValueError(f"{key} schema mismatch")
    return item


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


__all__ = ["QLIB_UPSTREAM_COMMIT", "run_request"]

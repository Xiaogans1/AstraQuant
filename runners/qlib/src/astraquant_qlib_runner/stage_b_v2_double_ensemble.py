"""Pinned Qlib DoubleEnsemble runner for Stage B v2 fold contracts."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from . import QLIB_UPSTREAM_COMMIT, _canonical_bytes, _digest, _ensure_qlib_initialized
from .dataset import AstraFoldDataset
from .model_adapters import create_double_ensemble_model

REQUEST_SCHEMA = "astraquant.stage-b-v2-double-ensemble-request/v1"
RESPONSE_SCHEMA = "astraquant.stage-b-v2-double-ensemble-response/v1"


def run_double_ensemble_request(request_path: Path, output_path: Path) -> dict[str, Any]:
    """Fit isolated DoubleEnsemble trials and publish valid/test score vectors."""

    request = _read_request(request_path)
    frame = _read_rows(request_path.parent, request)
    feature_columns = _string_list(request, "feature_columns")
    config = request.get("model_config")
    if not isinstance(config, dict):
        raise ValueError("DoubleEnsemble model_config schema mismatch")
    trials = request.get("trials")
    if not isinstance(trials, list) or not trials:
        raise ValueError("DoubleEnsemble trials must not be empty")
    _ensure_qlib_initialized()
    from qlib.workflow import R

    results: list[dict[str, Any]] = []
    for raw_trial in trials:
        if not isinstance(raw_trial, dict):
            raise ValueError("DoubleEnsemble trial schema mismatch")
        trial_id = _text(raw_trial, "trial_id")
        seed = _integer(raw_trial, "seed", allow_zero=True)
        fit_row_ids = _row_ids(raw_trial, "fit_row_ids", frame)
        inner_valid_row_ids = _row_ids(raw_trial, "inner_valid_row_ids", frame)
        outer_test_row_ids = _row_ids(raw_trial, "outer_test_row_ids", frame)
        if (
            set(fit_row_ids) & set(inner_valid_row_ids)
            or set(fit_row_ids) & set(outer_test_row_ids)
            or set(inner_valid_row_ids) & set(outer_test_row_ids)
        ):
            raise ValueError(f"DoubleEnsemble trial segments overlap: {trial_id}")
        row_index = {int(row_id): index for index, row_id in enumerate(frame["row_id"])}
        eligible_fit_ids = tuple(
            row_id
            for row_id in fit_row_ids
            if bool(frame.iloc[row_index[row_id]]["training_eligible"])
        )
        if len(eligible_fit_ids) < 10:
            raise ValueError(f"DoubleEnsemble fit segment is too small: {trial_id}")
        processor = _fit_processor(frame, eligible_fit_ids, row_index, feature_columns)
        transformed = _transform(frame, processor, feature_columns)
        model_fit_ids, model_valid_ids = _internal_validation_ids(
            transformed,
            eligible_fit_ids,
            row_index,
        )
        model_fit = [row_index[row_id] for row_id in model_fit_ids]
        model_valid = [row_index[row_id] for row_id in model_valid_ids]
        inner_valid = [row_index[row_id] for row_id in inner_valid_row_ids]
        outer_test = [row_index[row_id] for row_id in outer_test_row_ids]
        inner_dataset = _dataset(
            transformed,
            feature_columns,
            model_fit,
            model_valid,
            inner_valid,
        )
        outer_dataset = _dataset(
            transformed,
            feature_columns,
            model_fit,
            model_valid,
            outer_test,
        )
        model = create_double_ensemble_model(config, seed=seed)
        with R.start(experiment_name="AstraQuantStageBV2DoubleEnsemble"), warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)
            model.fit(inner_dataset)
        inner_scores = model.predict(inner_dataset, segment="test")
        outer_scores = model.predict(outer_dataset, segment="test")
        if list(inner_scores.index) != inner_valid or list(outer_scores.index) != outer_test:
            raise ValueError(f"DoubleEnsemble prediction order mismatch: {trial_id}")
        processor_digest = processor["processor_digest"]
        model_digest = _object_digest(
            {
                "config": config,
                "processor_digest": processor_digest,
                "schema_version": "astraquant.stage-b-v2-double-ensemble-model/v1",
                "seed": seed,
                "upstream_commit": QLIB_UPSTREAM_COMMIT,
            }
        )
        results.append(
            {
                "trial_id": trial_id,
                "seed": seed,
                "processor_digest": processor_digest,
                "model_digest": model_digest,
                "inner_valid_predictions": _predictions(inner_valid_row_ids, inner_scores),
                "outer_test_predictions": _predictions(outer_test_row_ids, outer_scores),
            }
        )
    body: dict[str, Any] = {
        "schema_version": RESPONSE_SCHEMA,
        "request_content_digest": request["content_digest"],
        "source_materialization_digest": request["source_materialization_digest"],
        "upstream_commit": QLIB_UPSTREAM_COMMIT,
        "trials": results,
    }
    response = {"content_digest": _object_digest(body), **body}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output_path.parent,
        prefix=f".{output_path.name}-",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(_canonical_bytes(response) + b"\n")
    temporary.replace(output_path)
    return response


def _read_request(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("DoubleEnsemble request schema mismatch")
    if value.get("upstream_commit") != QLIB_UPSTREAM_COMMIT:
        raise ValueError("DoubleEnsemble upstream commit mismatch")
    body = {key: item for key, item in value.items() if key != "content_digest"}
    if value.get("content_digest") != _object_digest(body):
        raise ValueError("DoubleEnsemble request digest mismatch")
    return value


def _read_rows(root: Path, request: dict[str, Any]) -> pd.DataFrame:
    value = request.get("rows_file")
    if not isinstance(value, dict) or value.get("path") != "rows.parquet":
        raise ValueError("DoubleEnsemble rows file schema mismatch")
    path = root / "rows.parquet"
    if not path.is_file() or value.get("digest") != _digest(path.read_bytes()):
        raise ValueError("DoubleEnsemble rows digest mismatch")
    frame = pq.read_table(path).to_pandas()
    features = _string_list(request, "feature_columns")
    expected = [
        "row_id",
        "decision_time",
        "instrument_id",
        *features,
        "cross_sectional_rank",
        "training_eligible",
    ]
    if list(frame.columns) != expected or len(frame) != _integer(request, "row_count"):
        raise ValueError("DoubleEnsemble rows schema mismatch")
    if frame["row_id"].duplicated().any():
        raise ValueError("DoubleEnsemble row identifiers must be unique")
    numeric = frame[[*features, "cross_sectional_rank"]].to_numpy(dtype=np.float64)
    if np.isinf(numeric).any() or not np.isfinite(frame["cross_sectional_rank"]).all():
        raise ValueError("DoubleEnsemble rows contain invalid numeric values")
    return frame


def _fit_processor(
    frame: pd.DataFrame,
    fit_row_ids: tuple[int, ...],
    row_index: dict[int, int],
    columns: list[str],
) -> dict[str, Any]:
    matrix = frame.iloc[[row_index[row_id] for row_id in fit_row_ids]][columns].to_numpy(
        dtype=np.float64
    )
    medians = np.zeros(len(columns), dtype=np.float64)
    scales = np.ones(len(columns), dtype=np.float64)
    for index in range(len(columns)):
        finite = matrix[np.isfinite(matrix[:, index]), index]
        if len(finite) == 0:
            continue
        center = float(np.median(finite))
        mad = float(np.median(np.abs(finite - center)))
        medians[index] = center
        scales[index] = max(1.4826 * mad, 1e-12)
    body = {
        "clip": [-3.0, 3.0],
        "columns": columns,
        "medians": [value.hex() for value in medians],
        "scales": [value.hex() for value in scales],
        "schema_version": "astraquant.cross-sectional-fold-processor/v1",
    }
    return {
        "medians": medians,
        "scales": scales,
        "processor_digest": _object_digest(body),
    }


def _transform(
    frame: pd.DataFrame,
    processor: dict[str, Any],
    columns: list[str],
) -> pd.DataFrame:
    transformed = frame.copy()
    matrix = transformed[columns].to_numpy(dtype=np.float64)
    medians = processor["medians"]
    scales = processor["scales"]
    matrix = np.where(np.isnan(matrix), medians, matrix)
    transformed.loc[:, columns] = np.clip((matrix - medians) / scales, -3.0, 3.0)
    transformed["future_return"] = transformed["cross_sectional_rank"]
    return transformed


def _internal_validation_ids(
    frame: pd.DataFrame,
    fit_row_ids: tuple[int, ...],
    row_index: dict[int, int],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    sessions = tuple(
        sorted({frame.iloc[row_index[row_id]]["decision_time"] for row_id in fit_row_ids})
    )
    validation_count = max(1, math.ceil(len(sessions) * 0.2))
    if validation_count >= len(sessions):
        raise ValueError("DoubleEnsemble internal validation leaves no fit sessions")
    validation_sessions = set(sessions[-validation_count:])
    fit = tuple(
        row_id
        for row_id in fit_row_ids
        if frame.iloc[row_index[row_id]]["decision_time"] not in validation_sessions
    )
    valid = tuple(row_id for row_id in fit_row_ids if row_id not in set(fit))
    return fit, valid


def _dataset(
    frame: pd.DataFrame,
    columns: list[str],
    fit_indices: list[int],
    valid_indices: list[int],
    test_indices: list[int],
) -> AstraFoldDataset:
    return AstraFoldDataset(
        frame,
        feature_columns=columns,
        target_column="future_return",
        train_indices=fit_indices,
        valid_indices=valid_indices,
        test_indices=test_indices,
    )


def _predictions(row_ids: tuple[int, ...], scores: pd.Series) -> list[dict[str, object]]:
    values = [float(value) for value in scores]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("DoubleEnsemble produced non-finite scores")
    return [
        {"row_id": row_id, "score": score} for row_id, score in zip(row_ids, values, strict=True)
    ]


def _row_ids(value: dict[str, Any], key: str, frame: pd.DataFrame) -> tuple[int, ...]:
    item = value.get(key)
    valid_ids = {int(row_id) for row_id in frame["row_id"]}
    if (
        not isinstance(item, list)
        or not item
        or any(isinstance(entry, bool) or not isinstance(entry, int) for entry in item)
        or len(set(item)) != len(item)
        or not set(item).issubset(valid_ids)
    ):
        raise ValueError(f"DoubleEnsemble {key} schema mismatch")
    return tuple(item)


def _string_list(value: dict[str, Any], key: str) -> list[str]:
    item = value.get(key)
    if (
        not isinstance(item, list)
        or not item
        or any(not isinstance(entry, str) or not entry for entry in item)
        or len(set(item)) != len(item)
    ):
        raise ValueError(f"DoubleEnsemble {key} schema mismatch")
    return item


def _text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"DoubleEnsemble {key} schema mismatch")
    return item


def _integer(value: dict[str, Any], key: str, *, allow_zero: bool = False) -> int:
    item = value.get(key)
    minimum = 0 if allow_zero else 1
    if isinstance(item, bool) or not isinstance(item, int) or item < minimum:
        raise ValueError(f"DoubleEnsemble {key} schema mismatch")
    return item


def _object_digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(_canonical_bytes(value)).hexdigest()}"

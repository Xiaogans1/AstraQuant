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

from . import QLIB_UPSTREAM_COMMIT, _canonical_bytes, _ensure_qlib_initialized
from .dataset import AstraFoldDataset
from .model_adapters import create_double_ensemble_model

REQUEST_SCHEMA = "astraquant.stage-b-v2-double-ensemble-request/v1"
RESPONSE_SCHEMA = "astraquant.stage-b-v2-double-ensemble-response/v1"
TRIAL_CHECKPOINT_SCHEMA = "astraquant.stage-b-v2-double-ensemble-trial/v1"


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
    row_index = {int(row_id): index for index, row_id in enumerate(frame["row_id"])}
    valid_row_ids = set(row_index)
    training_eligible = {
        int(row_id): bool(eligible)
        for row_id, eligible in zip(
            frame["row_id"],
            frame["training_eligible"],
            strict=True,
        )
    }
    decision_times = {
        int(row_id): decision_time
        for row_id, decision_time in zip(
            frame["row_id"],
            frame["decision_time"],
            strict=True,
        )
    }
    cached_fit_ids: tuple[int, ...] | None = None
    cached_processor: dict[str, Any] | None = None
    cached_transformed: pd.DataFrame | None = None
    cached_model_fit_ids: tuple[int, ...] | None = None
    cached_model_valid_ids: tuple[int, ...] | None = None
    checkpoint_root = output_path.parent / "trial-checkpoints"
    for raw_trial in trials:
        if not isinstance(raw_trial, dict):
            raise ValueError("DoubleEnsemble trial schema mismatch")
        trial_id = _text(raw_trial, "trial_id")
        seed = _integer(raw_trial, "seed", allow_zero=True)
        fit_row_ids = _row_ids(raw_trial, "fit_row_ids", valid_row_ids)
        inner_valid_row_ids = _row_ids(raw_trial, "inner_valid_row_ids", valid_row_ids)
        outer_test_row_ids = _row_ids(raw_trial, "outer_test_row_ids", valid_row_ids)
        if (
            set(fit_row_ids) & set(inner_valid_row_ids)
            or set(fit_row_ids) & set(outer_test_row_ids)
            or set(inner_valid_row_ids) & set(outer_test_row_ids)
        ):
            raise ValueError(f"DoubleEnsemble trial segments overlap: {trial_id}")
        checkpoint_path = checkpoint_root / f"{hashlib.sha256(trial_id.encode()).hexdigest()}.json"
        checkpoint = _load_trial_checkpoint(
            checkpoint_path,
            request_content_digest=_text(request, "content_digest"),
            trial_id=trial_id,
            seed=seed,
            inner_valid_row_ids=inner_valid_row_ids,
            outer_test_row_ids=outer_test_row_ids,
        )
        if checkpoint is not None:
            results.append(checkpoint)
            continue
        eligible_fit_ids = tuple(
            row_id
            for row_id in fit_row_ids
            if training_eligible[row_id]
        )
        if len(eligible_fit_ids) < 10:
            raise ValueError(f"DoubleEnsemble fit segment is too small: {trial_id}")
        if eligible_fit_ids != cached_fit_ids:
            cached_processor = _fit_processor(
                frame,
                eligible_fit_ids,
                row_index,
                feature_columns,
            )
            cached_transformed = _transform(frame, cached_processor, feature_columns)
            cached_model_fit_ids, cached_model_valid_ids = _internal_validation_ids(
                eligible_fit_ids,
                decision_times,
            )
            cached_fit_ids = eligible_fit_ids
        if (
            cached_processor is None
            or cached_transformed is None
            or cached_model_fit_ids is None
            or cached_model_valid_ids is None
        ):
            raise RuntimeError("DoubleEnsemble fold preprocessing cache is incomplete")
        processor = cached_processor
        transformed = cached_transformed
        model_fit_ids = cached_model_fit_ids
        model_valid_ids = cached_model_valid_ids
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
        trial_result = {
            "trial_id": trial_id,
            "seed": seed,
            "processor_digest": processor_digest,
            "model_digest": model_digest,
            "inner_valid_predictions": _predictions(inner_valid_row_ids, inner_scores),
            "outer_test_predictions": _predictions(outer_test_row_ids, outer_scores),
        }
        _write_trial_checkpoint(
            checkpoint_path,
            request_content_digest=_text(request, "content_digest"),
            trial=trial_result,
        )
        results.append(trial_result)
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


def _load_trial_checkpoint(
    path: Path,
    *,
    request_content_digest: str,
    trial_id: str,
    seed: int,
    inner_valid_row_ids: tuple[int, ...],
    outer_test_row_ids: tuple[int, ...],
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("DoubleEnsemble trial checkpoint schema mismatch")
    body = {key: item for key, item in value.items() if key != "content_digest"}
    trial = value.get("trial")
    if (
        value.get("content_digest") != _object_digest(body)
        or value.get("schema_version") != TRIAL_CHECKPOINT_SCHEMA
        or value.get("request_content_digest") != request_content_digest
        or not isinstance(trial, dict)
        or trial.get("trial_id") != trial_id
        or trial.get("seed") != seed
        or _prediction_row_ids(trial.get("inner_valid_predictions"))
        != inner_valid_row_ids
        or _prediction_row_ids(trial.get("outer_test_predictions"))
        != outer_test_row_ids
    ):
        raise ValueError("DoubleEnsemble trial checkpoint identity mismatch")
    return trial


def _write_trial_checkpoint(
    path: Path,
    *,
    request_content_digest: str,
    trial: dict[str, Any],
) -> None:
    body = {
        "schema_version": TRIAL_CHECKPOINT_SCHEMA,
        "request_content_digest": request_content_digest,
        "trial": trial,
    }
    value = {"content_digest": _object_digest(body), **body}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}-",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(_canonical_bytes(value) + b"\n")
    temporary.replace(path)


def _prediction_row_ids(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ValueError("DoubleEnsemble trial checkpoint predictions are missing")
    result: list[int] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("DoubleEnsemble trial checkpoint prediction schema mismatch")
        row_id = item.get("row_id")
        score = item.get("score")
        if (
            isinstance(row_id, bool)
            or not isinstance(row_id, int)
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            raise ValueError("DoubleEnsemble trial checkpoint prediction schema mismatch")
        result.append(row_id)
    return tuple(result)


def _read_rows(root: Path, request: dict[str, Any]) -> pd.DataFrame:
    value = request.get("rows_file")
    if not isinstance(value, dict) or value.get("path") != "rows.parquet":
        raise ValueError("DoubleEnsemble rows file schema mismatch")
    path = root / "rows.parquet"
    if not path.is_file() or value.get("digest") != _digest_file(path):
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
    fit_row_ids: tuple[int, ...],
    decision_times: dict[int, Any],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    sessions = tuple(sorted({decision_times[row_id] for row_id in fit_row_ids}))
    validation_count = max(1, math.ceil(len(sessions) * 0.2))
    if validation_count >= len(sessions):
        raise ValueError("DoubleEnsemble internal validation leaves no fit sessions")
    validation_sessions = set(sessions[-validation_count:])
    fit = tuple(
        row_id
        for row_id in fit_row_ids
        if decision_times[row_id] not in validation_sessions
    )
    fit_set = set(fit)
    valid = tuple(row_id for row_id in fit_row_ids if row_id not in fit_set)
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


def _row_ids(value: dict[str, Any], key: str, valid_ids: set[int]) -> tuple[int, ...]:
    item = value.get(key)
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


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"

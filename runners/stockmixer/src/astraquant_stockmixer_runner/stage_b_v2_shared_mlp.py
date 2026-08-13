"""Deterministic Shared MLP runner for the Stage B v2 wide panel."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import torch
from torch import Tensor

from .shared_mlp import CrossSectionalSharedMLP

REQUEST_SCHEMA = "astraquant.stage-b-v2-shared-mlp-request/v1"
RESPONSE_SCHEMA = "astraquant.stage-b-v2-shared-mlp-response/v1"
TRIAL_CHECKPOINT_SCHEMA = "astraquant.stage-b-v2-shared-mlp-trial/v1"
MODEL_SCHEMA = "astraquant.stage-b-v2-shared-mlp-model/v1"
_MODEL_CONFIG = {
    "hidden_dim": 64,
    "market_dim": 32,
    "encoder_layers": 2,
    "dropout": 0,
    "learning_rate": "0.001",
    "weight_decay": "0.0001",
    "epochs": 80,
    "patience": 8,
    "validation_fraction": "0.20",
    "internal_purge_sessions": 11,
    "session_batch_size": 16,
    "batch_semantics": "DECISION_DATE_CROSS_SECTION",
}


@dataclass(frozen=True, slots=True)
class _Rows:
    row_ids: np.ndarray
    decision_times: np.ndarray
    features: np.ndarray
    targets: np.ndarray
    training_eligible: np.ndarray
    row_index: dict[int, int]


@dataclass(frozen=True, slots=True)
class _Processor:
    medians: np.ndarray
    scales: np.ndarray
    digest: str


def run_shared_mlp_request(request_path: Path, output_path: Path) -> dict[str, Any]:
    """Train or resume every sealed trial and atomically publish its response."""

    request = _read_request(request_path)
    identity = _runner_identity(request)
    rows = _read_rows(request_path.parent, request)
    config = request.get("model_config")
    if config != _MODEL_CONFIG:
        raise ValueError("Shared MLP model_config mismatch")
    trials = request.get("trials")
    if not isinstance(trials, list) or not trials:
        raise ValueError("Shared MLP trials must not be empty")
    valid_ids = set(int(value) for value in rows.row_ids)
    checkpoint_root = output_path.parent / "trial-checkpoints"
    results: list[dict[str, Any]] = []
    processor_cache: dict[tuple[int, ...], tuple[_Processor, np.ndarray]] = {}
    for raw_trial in trials:
        if not isinstance(raw_trial, dict) or set(raw_trial) != {
            "trial_id",
            "seed",
            "fit_row_ids",
            "inner_valid_row_ids",
            "outer_test_row_ids",
        }:
            raise ValueError("Shared MLP trial schema mismatch")
        trial_id = _text(raw_trial, "trial_id")
        seed = _integer(raw_trial, "seed", allow_zero=True)
        fit_ids = _row_ids(raw_trial, "fit_row_ids", valid_ids)
        inner_ids = _row_ids(raw_trial, "inner_valid_row_ids", valid_ids)
        outer_ids = _row_ids(raw_trial, "outer_test_row_ids", valid_ids)
        if (
            set(fit_ids) & set(inner_ids)
            or set(fit_ids) & set(outer_ids)
            or set(inner_ids) & set(outer_ids)
        ):
            raise ValueError(f"Shared MLP trial segments overlap: {trial_id}")
        checkpoint_path = checkpoint_root / f"{hashlib.sha256(trial_id.encode()).hexdigest()}.json"
        restored = _load_trial_checkpoint(
            checkpoint_path,
            request_digest=_text(request, "content_digest"),
            trial_id=trial_id,
            seed=seed,
            inner_ids=inner_ids,
            outer_ids=outer_ids,
        )
        if restored is not None:
            results.append(restored)
            continue
        eligible_fit_ids = tuple(
            row_id for row_id in fit_ids if bool(rows.training_eligible[rows.row_index[row_id]])
        )
        if len(eligible_fit_ids) < 10:
            raise ValueError(f"Shared MLP fit segment is too small: {trial_id}")
        cached = processor_cache.get(eligible_fit_ids)
        if cached is None:
            processor = _fit_processor(rows, eligible_fit_ids, request["feature_columns"])
            transformed = _transform(rows.features, processor)
            processor_cache[eligible_fit_ids] = (processor, transformed)
        else:
            processor, transformed = cached
        trial = _fit_trial(
            trial_id=trial_id,
            seed=seed,
            rows=rows,
            transformed=transformed,
            processor=processor,
            fit_ids=eligible_fit_ids,
            inner_ids=inner_ids,
            outer_ids=outer_ids,
            config=config,
            device_name=identity["device"],
        )
        _write_trial_checkpoint(
            checkpoint_path,
            request_digest=_text(request, "content_digest"),
            trial=trial,
        )
        results.append(trial)
    body: dict[str, Any] = {
        "schema_version": RESPONSE_SCHEMA,
        "request_content_digest": request["content_digest"],
        "source_materialization_digest": request["source_materialization_digest"],
        "runner_identity": identity,
        "trials": results,
    }
    response = {"content_digest": _object_digest(body), **body}
    _atomic_json(output_path, response)
    return response


def _fit_trial(
    *,
    trial_id: str,
    seed: int,
    rows: _Rows,
    transformed: np.ndarray,
    processor: _Processor,
    fit_ids: tuple[int, ...],
    inner_ids: tuple[int, ...],
    outer_ids: tuple[int, ...],
    config: dict[str, Any],
    device_name: str,
) -> dict[str, Any]:
    _seed_everything(seed)
    device = torch.device(device_name)
    model_fit_ids, model_valid_ids = _internal_validation_ids(rows, fit_ids, config)
    model = CrossSectionalSharedMLP(
        feature_dim=transformed.shape[1],
        hidden_dim=config["hidden_dim"],
        market_dim=config["market_dim"],
        encoder_layers=config["encoder_layers"],
        dropout=float(config["dropout"]),
    ).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config["learning_rate"]),
        weight_decay=float(config["weight_decay"]),
    )
    train_batches = _session_batches(rows, transformed, model_fit_ids, device=device)
    valid_batches = _session_batches(rows, transformed, model_valid_ids, device=device)
    best_loss = math.inf
    best_state: dict[str, Tensor] | None = None
    stale_epochs = 0
    generator = torch.Generator(device="cpu").manual_seed(seed)
    for _epoch in range(config["epochs"]):
        model.train()
        order = torch.randperm(len(train_batches), generator=generator).tolist()
        batch_size = config["session_batch_size"]
        for start in range(0, len(order), batch_size):
            optimizer.zero_grad(set_to_none=True)
            losses = []
            for batch_index in order[start : start + batch_size]:
                features, mask, targets, target_mask = train_batches[batch_index]
                scores = model(features, mask)
                losses.append(torch.mean((scores[target_mask] - targets[target_mask]) ** 2))
            loss = torch.stack(losses).mean()
            loss.backward()
            optimizer.step()
        validation_loss = _mean_loss(model, valid_batches)
        if validation_loss < best_loss - 1e-12:
            best_loss = validation_loss
            best_state = {
                name: value.detach().cpu().clone() for name, value in model.state_dict().items()
            }
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= config["patience"]:
                break
    if best_state is None:
        raise RuntimeError("Shared MLP training did not produce a finite checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    model_digest = _state_digest(best_state, processor.digest, config, seed)
    return {
        "trial_id": trial_id,
        "seed": seed,
        "processor_digest": processor.digest,
        "model_digest": model_digest,
        "inner_valid_predictions": _predict(model, rows, transformed, inner_ids, device),
        "outer_test_predictions": _predict(model, rows, transformed, outer_ids, device),
    }


def _read_request(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("Shared MLP request schema mismatch")
    body = {key: item for key, item in value.items() if key != "content_digest"}
    if value.get("content_digest") != _object_digest(body):
        raise ValueError("Shared MLP request digest mismatch")
    return value


def _runner_identity(request: dict[str, Any]) -> dict[str, str]:
    requested = request.get("runner_identity")
    device = requested.get("device") if isinstance(requested, dict) else None
    expected = current_runner_identity(device)
    if requested != expected:
        raise ValueError("Shared MLP runner identity mismatch")
    return expected


def current_runner_identity(device: object) -> dict[str, str]:
    """Return the actual isolated runtime identity without importing it upstream."""

    if device not in {"cpu", "cuda"}:
        raise ValueError("Shared MLP device is unsupported")
    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA is unavailable; runner cannot report cuda")
    return {
        "package": "astraquant-stockmixer-runner",
        "version": version("astraquant-stockmixer-runner"),
        "torch_version": torch.__version__,
        "device": device,
    }


def _read_rows(root: Path, request: dict[str, Any]) -> _Rows:
    file_value = request.get("rows_file")
    if not isinstance(file_value, dict) or file_value.get("path") != "rows.parquet":
        raise ValueError("Shared MLP rows file schema mismatch")
    path = root / "rows.parquet"
    if not path.is_file() or file_value.get("digest") != _digest_file(path):
        raise ValueError("Shared MLP rows digest mismatch")
    table = pq.read_table(path)
    feature_columns = _string_list(request, "feature_columns")
    expected = [
        "row_id",
        "decision_time",
        "instrument_id",
        *feature_columns,
        "cross_sectional_rank",
        "training_eligible",
    ]
    if table.column_names != expected or table.num_rows != _integer(request, "row_count"):
        raise ValueError("Shared MLP rows schema mismatch")
    row_ids = np.asarray(table["row_id"].to_numpy(), dtype=np.int64)
    if len(np.unique(row_ids)) != len(row_ids):
        raise ValueError("Shared MLP row identifiers must be unique")
    decision_times = np.asarray(table["decision_time"].to_pylist(), dtype=object)
    features = np.column_stack(
        [
            np.asarray(
                [float("nan") if value is None else value for value in table[column].to_pylist()],
                dtype=np.float64,
            )
            for column in feature_columns
        ]
    )
    targets = np.asarray(table["cross_sectional_rank"].to_numpy(), dtype=np.float64)
    if np.isinf(features).any() or not np.isfinite(targets).all():
        raise ValueError("Shared MLP rows contain invalid numeric values")
    eligible = np.asarray(table["training_eligible"].to_numpy(), dtype=np.bool_)
    return _Rows(
        row_ids=row_ids,
        decision_times=decision_times,
        features=features,
        targets=targets,
        training_eligible=eligible,
        row_index={int(row_id): index for index, row_id in enumerate(row_ids)},
    )


def _fit_processor(rows: _Rows, fit_ids: tuple[int, ...], columns: list[str]) -> _Processor:
    matrix = rows.features[[rows.row_index[row_id] for row_id in fit_ids]]
    medians = np.zeros(matrix.shape[1], dtype=np.float64)
    scales = np.ones(matrix.shape[1], dtype=np.float64)
    for index in range(matrix.shape[1]):
        finite = matrix[np.isfinite(matrix[:, index]), index]
        if len(finite):
            medians[index] = np.median(finite)
            scales[index] = max(1.4826 * float(np.median(np.abs(finite - medians[index]))), 1e-12)
    body = {
        "schema_version": "astraquant.cross-sectional-fold-processor/v1",
        "columns": columns,
        "medians": [value.hex() for value in medians],
        "scales": [value.hex() for value in scales],
        "clip": [-3.0, 3.0],
    }
    return _Processor(medians, scales, _object_digest(body))


def _transform(features: np.ndarray, processor: _Processor) -> np.ndarray:
    matrix = np.where(np.isnan(features), processor.medians, features)
    return np.clip((matrix - processor.medians) / processor.scales, -3.0, 3.0).astype(np.float32)


def _internal_validation_ids(
    rows: _Rows, fit_ids: tuple[int, ...], config: dict[str, Any]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    sessions = tuple(sorted({rows.decision_times[rows.row_index[row_id]] for row_id in fit_ids}))
    validation_count = max(1, math.ceil(len(sessions) * float(config["validation_fraction"])))
    purge_count = config["internal_purge_sessions"]
    train_end = len(sessions) - validation_count - purge_count
    if train_end <= 0:
        raise ValueError("Shared MLP internal validation leaves no fit sessions")
    train_sessions = set(sessions[:train_end])
    valid_sessions = set(sessions[-validation_count:])
    train = tuple(
        row_id
        for row_id in fit_ids
        if rows.decision_times[rows.row_index[row_id]] in train_sessions
    )
    valid = tuple(
        row_id
        for row_id in fit_ids
        if rows.decision_times[rows.row_index[row_id]] in valid_sessions
    )
    if not train or not valid:
        raise ValueError("Shared MLP internal validation is empty")
    return train, valid


def _session_batches(
    rows: _Rows,
    transformed: np.ndarray,
    row_ids: tuple[int, ...],
    *,
    device: torch.device,
) -> list[tuple[Tensor, Tensor, Tensor, Tensor]]:
    grouped: dict[object, list[int]] = {}
    for row_id in row_ids:
        index = rows.row_index[row_id]
        grouped.setdefault(rows.decision_times[index], []).append(index)
    result = []
    for session in sorted(grouped):
        indices = grouped[session]
        features = torch.from_numpy(transformed[indices]).unsqueeze(0).to(device)
        targets = torch.from_numpy(rows.targets[indices].astype(np.float32)).unsqueeze(0).to(device)
        mask = torch.ones(targets.shape, dtype=torch.bool, device=device)
        result.append((features, mask, targets, mask))
    return result


def _mean_loss(
    model: CrossSectionalSharedMLP,
    batches: list[tuple[Tensor, Tensor, Tensor, Tensor]],
) -> float:
    model.eval()
    losses = []
    with torch.no_grad():
        for features, mask, targets, target_mask in batches:
            scores = model(features, mask)
            losses.append(float(torch.mean((scores[target_mask] - targets[target_mask]) ** 2)))
    value = float(np.mean(losses))
    if not math.isfinite(value):
        raise RuntimeError("Shared MLP validation loss is non-finite")
    return value


def _predict(
    model: CrossSectionalSharedMLP,
    rows: _Rows,
    transformed: np.ndarray,
    row_ids: tuple[int, ...],
    device: torch.device,
) -> list[dict[str, object]]:
    scores_by_id: dict[int, float] = {}
    model.eval()
    with torch.no_grad():
        grouped: dict[object, list[int]] = {}
        for row_id in row_ids:
            grouped.setdefault(rows.decision_times[rows.row_index[row_id]], []).append(row_id)
        for session in sorted(grouped):
            ids = grouped[session]
            indices = [rows.row_index[row_id] for row_id in ids]
            features = torch.from_numpy(transformed[indices]).unsqueeze(0).to(device)
            mask = torch.ones((1, len(ids)), dtype=torch.bool, device=device)
            values = model(features, mask).squeeze(0).cpu().tolist()
            scores_by_id.update(zip(ids, (float(value) for value in values), strict=True))
    result = [{"row_id": row_id, "score": scores_by_id[row_id]} for row_id in row_ids]
    if not all(math.isfinite(float(item["score"])) for item in result):
        raise RuntimeError("Shared MLP produced non-finite scores")
    return result


def _seed_everything(seed: int) -> None:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)


def _state_digest(
    state: dict[str, Tensor], processor_digest: str, config: dict[str, Any], seed: int
) -> str:
    digest = hashlib.sha256()
    digest.update(
        _canonical_bytes(
            {
                "schema_version": MODEL_SCHEMA,
                "processor_digest": processor_digest,
                "config": config,
                "seed": seed,
            }
        )
    )
    for name in sorted(state):
        value = state[name].detach().cpu().contiguous().numpy()
        digest.update(name.encode())
        digest.update(value.dtype.str.encode())
        digest.update(np.asarray(value.shape, dtype=np.int64).tobytes())
        digest.update(value.tobytes())
    return f"sha256:{digest.hexdigest()}"


def _load_trial_checkpoint(
    path: Path,
    *,
    request_digest: str,
    trial_id: str,
    seed: int,
    inner_ids: tuple[int, ...],
    outer_ids: tuple[int, ...],
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    body = (
        {key: item for key, item in value.items() if key != "content_digest"}
        if isinstance(value, dict)
        else {}
    )
    trial = value.get("trial") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("content_digest") != _object_digest(body)
        or value.get("schema_version") != TRIAL_CHECKPOINT_SCHEMA
        or value.get("request_content_digest") != request_digest
        or not isinstance(trial, dict)
        or trial.get("trial_id") != trial_id
        or trial.get("seed") != seed
        or _prediction_ids(trial.get("inner_valid_predictions")) != inner_ids
        or _prediction_ids(trial.get("outer_test_predictions")) != outer_ids
    ):
        raise ValueError("Shared MLP trial checkpoint identity mismatch")
    return trial


def _write_trial_checkpoint(path: Path, *, request_digest: str, trial: dict[str, Any]) -> None:
    body = {
        "schema_version": TRIAL_CHECKPOINT_SCHEMA,
        "request_content_digest": request_digest,
        "trial": trial,
    }
    _atomic_json(path, {"content_digest": _object_digest(body), **body})


def _prediction_ids(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ValueError("Shared MLP predictions are missing")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"row_id", "score"}:
            raise ValueError("Shared MLP prediction schema mismatch")
        row_id, score = item["row_id"], item["score"]
        if (
            isinstance(row_id, bool)
            or not isinstance(row_id, int)
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            raise ValueError("Shared MLP prediction schema mismatch")
        result.append(row_id)
    return tuple(result)


def _row_ids(value: dict[str, Any], key: str, valid_ids: set[int]) -> tuple[int, ...]:
    item = value.get(key)
    if (
        not isinstance(item, list)
        or not item
        or any(isinstance(entry, bool) or not isinstance(entry, int) for entry in item)
        or len(set(item)) != len(item)
        or not set(item).issubset(valid_ids)
    ):
        raise ValueError(f"Shared MLP {key} schema mismatch")
    return tuple(item)


def _string_list(value: dict[str, Any], key: str) -> list[str]:
    item = value.get(key)
    if (
        not isinstance(item, list)
        or not item
        or any(not isinstance(entry, str) or not entry for entry in item)
        or len(set(item)) != len(item)
    ):
        raise ValueError(f"Shared MLP {key} schema mismatch")
    return item


def _text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Shared MLP {key} schema mismatch")
    return item


def _integer(value: dict[str, Any], key: str, *, allow_zero: bool = False) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < (0 if allow_zero else 1):
        raise ValueError(f"Shared MLP {key} schema mismatch")
    return item


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}-", suffix=".tmp", delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(_canonical_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _object_digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(_canonical_bytes(value)).hexdigest()}"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"

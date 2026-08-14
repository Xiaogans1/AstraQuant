"""Deterministic and resumable StockMixer v2 Stage B runner."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import Tensor

from .loss import masked_stock_loss
from .stage_b_v2_shared_mlp import current_runner_identity
from .stockmixer_v2 import DynamicStockMixerV2
from .temporal_panel import (
    TEMPORAL_COLUMNS,
    TemporalBatch,
    TemporalPanel,
    build_temporal_batch,
    load_temporal_panel,
)

REQUEST_SCHEMA = "astraquant.stage-b-v2-stockmixer-v2-request/v1"
RESPONSE_SCHEMA = "astraquant.stage-b-v2-stockmixer-v2-response/v1"
CHECKPOINT_SCHEMA = "astraquant.stage-b-v2-stockmixer-v2-trial/v1"
MODEL_SCHEMA = "astraquant.stage-b-v2-stockmixer-v2-model/v1"
_MODEL_CONFIG = {
    "hidden_dim": 64,
    "market_dim": 32,
    "context_dim": 32,
    "scales": [1, 2, 4],
    "learning_rate": "0.001",
    "weight_decay": "0.0001",
    "ranking_weight": "0.1",
    "epochs": 80,
    "patience": 8,
    "validation_fraction": "0.20",
    "internal_purge_sessions": 11,
    "session_batch_size": 16,
    "batch_semantics": "DECISION_DATE_DYNAMIC_UNIVERSE",
}


@dataclass(frozen=True, slots=True)
class _Processor:
    temporal_means: np.ndarray
    temporal_scales: np.ndarray
    context_means: np.ndarray
    context_scales: np.ndarray
    digest: str


def run_stockmixer_v2_request(request_path: Path, output_path: Path) -> dict[str, Any]:
    """Train or restore every sealed trial and publish one canonical response."""

    request = _read_request(request_path)
    identity = _runner_identity(request)
    panel = load_temporal_panel(request_path.parent / "manifest.json")
    _validate_panel_identity(request, panel)
    config = request.get("model_config")
    if config != _MODEL_CONFIG:
        raise ValueError("StockMixer v2 model_config mismatch")
    horizon = _integer(request, "horizon_sessions")
    horizon_ids = set(int(row_id) for row_id in panel.row_ids[panel.row_horizons == horizon])
    if len(horizon_ids) != _integer(request, "row_count"):
        raise ValueError("StockMixer v2 request row count mismatch")
    raw_trials = request.get("trials")
    if not isinstance(raw_trials, list) or not raw_trials:
        raise ValueError("StockMixer v2 trials must not be empty")
    checkpoint_root = output_path.parent / "trial-checkpoints"
    results: list[dict[str, Any]] = []
    for raw_trial in raw_trials:
        trial_id, seed, fit_ids, inner_ids, outer_ids = _trial(raw_trial, horizon_ids)
        checkpoint_path = checkpoint_root / f"{hashlib.sha256(trial_id.encode()).hexdigest()}.json"
        restored = _load_checkpoint(
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
        trial = _fit_trial(
            trial_id=trial_id,
            seed=seed,
            panel=panel,
            fit_ids=fit_ids,
            inner_ids=inner_ids,
            outer_ids=outer_ids,
            config=config,
            device_name=identity["device"],
        )
        _write_checkpoint(
            checkpoint_path,
            request_digest=_text(request, "content_digest"),
            trial=trial,
        )
        results.append(trial)
    body: dict[str, Any] = {
        "schema_version": RESPONSE_SCHEMA,
        "request_content_digest": request["content_digest"],
        "source_materialization_digest": request["source_materialization_digest"],
        "source_raw_export_digest": request["source_raw_export_digest"],
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
    panel: TemporalPanel,
    fit_ids: tuple[int, ...],
    inner_ids: tuple[int, ...],
    outer_ids: tuple[int, ...],
    config: dict[str, Any],
    device_name: str,
) -> dict[str, Any]:
    _seed_everything(seed)
    model_fit_ids, model_valid_ids = _internal_validation_ids(panel, fit_ids, config)
    processor = _fit_processor(panel, model_fit_ids, config["session_batch_size"])
    device = torch.device(device_name)
    model = DynamicStockMixerV2(
        time_steps=panel.lookback,
        temporal_channels=len(TEMPORAL_COLUMNS),
        context_channels=len(panel.context_columns),
        hidden_dim=config["hidden_dim"],
        market_dim=config["market_dim"],
        context_dim=config["context_dim"],
        scales=tuple(config["scales"]),
    ).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config["learning_rate"]),
        weight_decay=float(config["weight_decay"]),
    )
    train_groups = _session_groups(panel, model_fit_ids)
    valid_groups = _session_groups(panel, model_valid_ids)
    best_loss = math.inf
    best_state: dict[str, Tensor] | None = None
    stale_epochs = 0
    generator = torch.Generator(device="cpu").manual_seed(seed)
    for _epoch in range(config["epochs"]):
        model.train()
        order = torch.randperm(len(train_groups), generator=generator).tolist()
        for start in range(0, len(order), config["session_batch_size"]):
            ids = tuple(
                row_id
                for group_index in order[start : start + config["session_batch_size"]]
                for row_id in train_groups[group_index]
            )
            batch = _prepared_batch(panel, ids, processor, device)
            optimizer.zero_grad(set_to_none=True)
            predictions = _forward(model, batch)
            target_mask = batch.label_mask & batch.training_eligible & batch.tradable_mask
            loss = masked_stock_loss(
                predictions,
                batch.labels,
                target_mask,
                ranking_weight=float(config["ranking_weight"]),
            ).total
            loss.backward()
            optimizer.step()
        validation_loss = _mean_loss(
            model,
            panel,
            valid_groups,
            processor,
            device,
            session_batch_size=config["session_batch_size"],
            ranking_weight=float(config["ranking_weight"]),
        )
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
        raise RuntimeError("StockMixer v2 training did not produce a finite checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    return {
        "trial_id": trial_id,
        "seed": seed,
        "processor_digest": processor.digest,
        "model_digest": _state_digest(best_state, processor.digest, config, seed),
        "inner_valid_predictions": _predict(model, panel, inner_ids, processor, device),
        "outer_test_predictions": _predict(model, panel, outer_ids, processor, device),
    }


def _fit_processor(
    panel: TemporalPanel,
    row_ids: tuple[int, ...],
    session_batch_size: int,
) -> _Processor:
    temporal_sum = np.zeros(len(TEMPORAL_COLUMNS), dtype=np.float64)
    temporal_square = np.zeros(len(TEMPORAL_COLUMNS), dtype=np.float64)
    temporal_count = np.zeros(len(TEMPORAL_COLUMNS), dtype=np.int64)
    context_sum = np.zeros(len(panel.context_columns), dtype=np.float64)
    context_square = np.zeros(len(panel.context_columns), dtype=np.float64)
    context_count = np.zeros(len(panel.context_columns), dtype=np.int64)
    groups = _session_groups(panel, row_ids)
    for ids in _group_chunks(groups, session_batch_size):
        batch = build_temporal_batch(panel, row_ids=ids)
        eligible = (batch.label_mask & batch.training_eligible).numpy()
        temporal_mask = batch.feature_mask.numpy() & eligible[..., None]
        temporal_values = batch.temporal_features.numpy()
        for channel in range(temporal_values.shape[-1]):
            values = temporal_values[..., channel][temporal_mask]
            temporal_sum[channel] += values.sum(dtype=np.float64)
            temporal_square[channel] += np.square(values, dtype=np.float64).sum(dtype=np.float64)
            temporal_count[channel] += len(values)
        context_mask = batch.context_mask.numpy() & eligible
        context_values = batch.current_context.numpy()
        for channel in range(context_values.shape[-1]):
            values = context_values[..., channel][context_mask]
            context_sum[channel] += values.sum(dtype=np.float64)
            context_square[channel] += np.square(values, dtype=np.float64).sum(dtype=np.float64)
            context_count[channel] += len(values)
    if np.any(temporal_count == 0) or np.any(context_count == 0):
        raise ValueError("StockMixer v2 processor has an empty training channel")
    temporal_means, temporal_scales = _moments(temporal_sum, temporal_square, temporal_count)
    context_means, context_scales = _moments(context_sum, context_square, context_count)
    body = {
        "schema_version": "astraquant.stockmixer-v2-fold-processor/v1",
        "temporal_columns": list(TEMPORAL_COLUMNS),
        "context_columns": list(panel.context_columns),
        "temporal_means": [value.hex() for value in temporal_means],
        "temporal_scales": [value.hex() for value in temporal_scales],
        "context_means": [value.hex() for value in context_means],
        "context_scales": [value.hex() for value in context_scales],
        "clip": [-3.0, 3.0],
    }
    return _Processor(
        temporal_means=temporal_means,
        temporal_scales=temporal_scales,
        context_means=context_means,
        context_scales=context_scales,
        digest=_object_digest(body),
    )


def _moments(
    sums: np.ndarray, squares: np.ndarray, counts: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    means = sums / counts
    variance = np.maximum(squares / counts - np.square(means), 0)
    return means, np.maximum(np.sqrt(variance), 1e-6)


def _prepared_batch(
    panel: TemporalPanel,
    row_ids: tuple[int, ...],
    processor: _Processor,
    device: torch.device,
) -> TemporalBatch:
    batch = build_temporal_batch(panel, row_ids=row_ids)
    temporal = np.clip(
        (batch.temporal_features.numpy() - processor.temporal_means) / processor.temporal_scales,
        -3.0,
        3.0,
    ).astype(np.float32)
    temporal[~batch.feature_mask.numpy()] = 0
    context = np.clip(
        (batch.current_context.numpy() - processor.context_means) / processor.context_scales,
        -3.0,
        3.0,
    ).astype(np.float32)
    context[~batch.context_mask.numpy()] = 0
    return TemporalBatch(
        temporal_features=torch.from_numpy(temporal).to(device),
        current_context=torch.from_numpy(context).to(device),
        feature_mask=batch.feature_mask.to(device),
        context_mask=batch.context_mask.to(device),
        presence_mask=batch.presence_mask.to(device),
        tradable_mask=batch.tradable_mask.to(device),
        labels=batch.labels.to(device),
        label_mask=batch.label_mask.to(device),
        training_eligible=batch.training_eligible.to(device),
        row_ids=batch.row_ids.to(device),
        decision_time_us=batch.decision_time_us.to(device),
    )


def _forward(model: DynamicStockMixerV2, batch: TemporalBatch) -> Tensor:
    return model(
        batch.temporal_features,
        batch.current_context,
        batch.presence_mask,
        batch.feature_mask,
        batch.context_mask,
    )


def _mean_loss(
    model: DynamicStockMixerV2,
    panel: TemporalPanel,
    groups: tuple[tuple[int, ...], ...],
    processor: _Processor,
    device: torch.device,
    *,
    session_batch_size: int,
    ranking_weight: float,
) -> float:
    model.eval()
    losses = []
    with torch.no_grad():
        for ids in _group_chunks(groups, session_batch_size):
            batch = _prepared_batch(panel, ids, processor, device)
            target_mask = batch.label_mask & batch.training_eligible & batch.tradable_mask
            losses.append(
                float(
                    masked_stock_loss(
                        _forward(model, batch),
                        batch.labels,
                        target_mask,
                        ranking_weight=ranking_weight,
                    ).total
                )
            )
    value = float(np.mean(losses))
    if not math.isfinite(value):
        raise RuntimeError("StockMixer v2 validation loss is non-finite")
    return value


def _predict(
    model: DynamicStockMixerV2,
    panel: TemporalPanel,
    row_ids: tuple[int, ...],
    processor: _Processor,
    device: torch.device,
) -> list[dict[str, object]]:
    scores: dict[int, float] = {}
    wanted = set(row_ids)
    groups = _session_groups(panel, row_ids)
    model.eval()
    with torch.no_grad():
        for ids in _group_chunks(groups, 16):
            batch = _prepared_batch(panel, ids, processor, device)
            values = _forward(model, batch).cpu().numpy()
            matrix_ids = batch.row_ids.cpu().numpy()
            for row, value in zip(matrix_ids.ravel(), values.ravel(), strict=True):
                row_id = int(row)
                if row_id in wanted:
                    scores[row_id] = float(value)
    if set(scores) != wanted or not all(math.isfinite(value) for value in scores.values()):
        raise RuntimeError("StockMixer v2 produced incomplete or non-finite scores")
    return [{"row_id": row_id, "score": scores[row_id]} for row_id in row_ids]


def _internal_validation_ids(
    panel: TemporalPanel,
    fit_ids: tuple[int, ...],
    config: dict[str, Any],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    sessions = sorted({int(panel.row_decision_time_us[row_id]) for row_id in fit_ids})
    validation_count = max(1, math.ceil(len(sessions) * float(config["validation_fraction"])))
    train_end = len(sessions) - validation_count - config["internal_purge_sessions"]
    if train_end <= 0:
        raise ValueError("StockMixer v2 internal validation leaves no fit sessions")
    train_sessions = set(sessions[:train_end])
    valid_sessions = set(sessions[-validation_count:])
    train = tuple(
        row_id for row_id in fit_ids if int(panel.row_decision_time_us[row_id]) in train_sessions
    )
    valid = tuple(
        row_id for row_id in fit_ids if int(panel.row_decision_time_us[row_id]) in valid_sessions
    )
    if not train or not valid:
        raise ValueError("StockMixer v2 internal validation is empty")
    return train, valid


def _session_groups(panel: TemporalPanel, row_ids: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    grouped: dict[tuple[int, int], list[int]] = {}
    for row_id in row_ids:
        key = (
            int(panel.row_decision_time_us[row_id]),
            int(panel.row_horizons[row_id]),
        )
        grouped.setdefault(key, []).append(row_id)
    result = tuple(tuple(sorted(grouped[key])) for key in sorted(grouped))
    for group in result:
        build_temporal_batch(panel, row_ids=group)
    return result


def _group_chunks(groups: tuple[tuple[int, ...], ...], size: int) -> tuple[tuple[int, ...], ...]:
    if size <= 0:
        raise ValueError("StockMixer v2 session batch size must be positive")
    return tuple(
        tuple(row_id for group in groups[start : start + size] for row_id in group)
        for start in range(0, len(groups), size)
    )


def _read_request(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("StockMixer v2 request schema mismatch")
    body = {key: item for key, item in value.items() if key != "content_digest"}
    if value.get("content_digest") != _object_digest(body):
        raise ValueError("StockMixer v2 request digest mismatch")
    return value


def _runner_identity(request: dict[str, Any]) -> dict[str, str]:
    requested = request.get("runner_identity")
    device = requested.get("device") if isinstance(requested, dict) else None
    expected = current_runner_identity(device)
    if requested != expected:
        raise ValueError("StockMixer v2 runner identity mismatch")
    return expected


def _validate_panel_identity(request: dict[str, Any], panel: TemporalPanel) -> None:
    if request.get("source_raw_export_digest") != panel.source_raw_export_digest:
        raise ValueError("StockMixer v2 raw export identity mismatch")
    if request.get("source_materialization_digest") != panel.source_materialization_digest:
        raise ValueError("StockMixer v2 materialization identity mismatch")
    if request.get("instrument_count") != len(panel.instrument_ids):
        raise ValueError("StockMixer v2 instrument count mismatch")
    if request.get("temporal_panel_file") != _manifest_file("temporal_panel_file", panel):
        raise ValueError("StockMixer v2 temporal panel request mismatch")
    if request.get("rows_file") != _manifest_file("rows_file", panel):
        raise ValueError("StockMixer v2 rows request mismatch")
    expected_spec = {
        "lookback": panel.lookback,
        "temporal_columns": list(TEMPORAL_COLUMNS),
        "context_columns": list(panel.context_columns),
        "price_transform": "PREVIOUS_CLOSE_RELATIVE_V1",
        "volume_transform": "LOG1P_DIFFERENCE_V1",
        "context_visibility": "DECISION_TIME_ONLY",
    }
    if request.get("feature_spec") != expected_spec:
        raise ValueError("StockMixer v2 feature spec mismatch")


def _manifest_file(key: str, panel: TemporalPanel) -> object:
    # The strict panel loader already verified these exact files and digests.
    manifest = json.loads(panel.manifest_path.read_text(encoding="utf-8"))
    return manifest.get(key)


def _trial(
    value: object,
    valid_ids: set[int],
) -> tuple[str, int, tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    if not isinstance(value, dict) or set(value) != {
        "trial_id",
        "seed",
        "fit_row_ids",
        "inner_valid_row_ids",
        "outer_test_row_ids",
    }:
        raise ValueError("StockMixer v2 trial schema mismatch")
    trial_id = _text(value, "trial_id")
    seed = _integer(value, "seed", allow_zero=True)
    fit = _row_ids(value, "fit_row_ids", valid_ids)
    inner = _row_ids(value, "inner_valid_row_ids", valid_ids)
    outer = _row_ids(value, "outer_test_row_ids", valid_ids)
    if set(fit) & set(inner) or set(fit) & set(outer) or set(inner) & set(outer):
        raise ValueError(f"StockMixer v2 trial segments overlap: {trial_id}")
    return trial_id, seed, fit, inner, outer


def _row_ids(value: dict[str, Any], key: str, valid_ids: set[int]) -> tuple[int, ...]:
    raw = value.get(key)
    if (
        not isinstance(raw, list)
        or not raw
        or any(isinstance(item, bool) or not isinstance(item, int) for item in raw)
        or len(set(raw)) != len(raw)
        or not set(raw).issubset(valid_ids)
    ):
        raise ValueError(f"StockMixer v2 {key} schema mismatch")
    return tuple(raw)


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


def _load_checkpoint(
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
        or value.get("schema_version") != CHECKPOINT_SCHEMA
        or value.get("request_content_digest") != request_digest
        or not isinstance(trial, dict)
        or trial.get("trial_id") != trial_id
        or trial.get("seed") != seed
        or _prediction_ids(trial.get("inner_valid_predictions")) != inner_ids
        or _prediction_ids(trial.get("outer_test_predictions")) != outer_ids
    ):
        raise ValueError("StockMixer v2 trial checkpoint identity mismatch")
    return trial


def _write_checkpoint(path: Path, *, request_digest: str, trial: dict[str, Any]) -> None:
    body = {
        "schema_version": CHECKPOINT_SCHEMA,
        "request_content_digest": request_digest,
        "trial": trial,
    }
    _atomic_json(path, {"content_digest": _object_digest(body), **body})


def _prediction_ids(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"row_id", "score"}:
            return ()
        row_id = item.get("row_id")
        score = item.get("score")
        if (
            isinstance(row_id, bool)
            or not isinstance(row_id, int)
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            return ()
        result.append(row_id)
    return tuple(result)


def _integer(value: dict[str, Any], key: str, *, allow_zero: bool = False) -> int:
    item = value.get(key)
    minimum = 0 if allow_zero else 1
    if isinstance(item, bool) or not isinstance(item, int) or item < minimum:
        raise ValueError(f"StockMixer v2 {key} schema mismatch")
    return item


def _text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"StockMixer v2 {key} schema mismatch")
    return item


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}-",
        suffix=".tmp",
        delete=False,
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
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()

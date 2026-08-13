"""Leakage-safe, deterministic per-fold training for DynamicStockMixer."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Literal

# Must be present before the first CUDA BLAS handle is created anywhere in this process.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch
from torch import Tensor
from torch.optim import AdamW
from torch.utils.data import DataLoader, Subset

from .contracts import STOCKMIXER_INPUT_COLUMNS, StockMixerRequest
from .dataset import FeatureNormalizer, PanelWindowDataset, StockMixerBatch
from .loss import masked_stock_loss
from .model import DynamicStockMixer


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    seed: int = 20260813
    epochs: int = 50
    batch_size: int = 64
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    ranking_weight: float = 0.1
    validation_time_count: int = 20
    purge_time_count: int = 1
    patience: int = 8
    minimum_improvement: float = 1e-8
    hidden_dim: int = 64
    market_dim: int = 32
    scales: tuple[int, ...] = (1, 2, 4)

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if min(
            self.epochs,
            self.batch_size,
            self.validation_time_count,
            self.patience,
            self.hidden_dim,
            self.market_dim,
        ) <= 0:
            raise ValueError("training dimensions and counts must be positive")
        if self.purge_time_count < 0:
            raise ValueError("purge_time_count must be non-negative")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("optimizer values are outside their valid range")
        if self.ranking_weight < 0 or self.minimum_improvement < 0:
            raise ValueError("loss and early-stop values must be non-negative")
        if not self.scales or any(scale <= 0 for scale in self.scales):
            raise ValueError("scales must contain positive integers")


@dataclass(frozen=True, slots=True)
class InnerValidationSplit:
    train_indices: tuple[int, ...]
    purged_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]
    train_end_time_us: int
    validation_start_time_us: int


@dataclass(frozen=True, slots=True)
class EpochMetrics:
    epoch: int
    train_loss: float
    validation_loss: float


@dataclass(frozen=True, slots=True)
class TrainedFold:
    fold_id: str
    model: DynamicStockMixer
    normalizer: FeatureNormalizer
    split: InnerValidationSplit
    best_epoch: int
    history: tuple[EpochMetrics, ...]
    model_state_digest: str
    test_sample_ids: tuple[int, ...]
    test_decision_times_us: tuple[int, ...]
    test_predictions: Tensor


def split_inner_validation(
    dataset: PanelWindowDataset,
    *,
    validation_time_count: int,
    purge_time_count: int,
) -> InnerValidationSplit:
    """Reserve the chronological tail for inner validation and purge its boundary."""

    if validation_time_count <= 0 or purge_time_count < 0:
        raise ValueError("validation_time_count must be positive and purge non-negative")
    times = tuple(sample.decision_time for sample in dataset.samples)
    unique_times = tuple(dict.fromkeys(times))
    required = validation_time_count + purge_time_count + 1
    if len(unique_times) < required:
        raise ValueError("training segment is too short for inner validation and purge")
    validation_times = set(unique_times[-validation_time_count:])
    purge_start = len(unique_times) - validation_time_count - purge_time_count
    purged_times = set(unique_times[purge_start : len(unique_times) - validation_time_count])
    train_indices = tuple(
        index
        for index, decision_time in enumerate(times)
        if decision_time not in validation_times and decision_time not in purged_times
    )
    purged_indices = tuple(
        index for index, decision_time in enumerate(times) if decision_time in purged_times
    )
    validation_indices = tuple(
        index for index, decision_time in enumerate(times) if decision_time in validation_times
    )
    if not train_indices or not validation_indices:
        raise ValueError("inner train and validation must both be non-empty")
    train_end = max(times[index] for index in train_indices)
    validation_start = min(times[index] for index in validation_indices)
    if train_end >= validation_start:
        raise ValueError("inner validation is not strictly after inner train")
    return InnerValidationSplit(
        train_indices=train_indices,
        purged_indices=purged_indices,
        validation_indices=validation_indices,
        train_end_time_us=round(train_end.timestamp() * 1_000_000),
        validation_start_time_us=round(validation_start.timestamp() * 1_000_000),
    )


def train_fold(
    request: StockMixerRequest,
    *,
    fold_id: str,
    config: TrainingConfig,
    device: Literal["cpu", "cuda"] = "cpu",
) -> TrainedFold:
    """Train with inner validation, then predict outer-test without reading its labels."""

    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    if any(request.lookback % scale for scale in config.scales):
        raise ValueError("all training scales must divide request lookback")
    torch.manual_seed(config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config.seed)
    torch.use_deterministic_algorithms(True)
    compute_device = torch.device(device)

    raw_train = PanelWindowDataset(request, fold_id=fold_id, segment="train")
    split = split_inner_validation(
        raw_train,
        validation_time_count=config.validation_time_count,
        purge_time_count=config.purge_time_count,
    )
    normalizer = _fit_normalizer(raw_train, split)
    train_dataset = raw_train.with_normalizer(normalizer)
    test_dataset = PanelWindowDataset(
        request,
        fold_id=fold_id,
        segment="test",
        normalizer=normalizer,
    )
    train_loader = _loader(
        train_dataset,
        split.train_indices,
        batch_size=config.batch_size,
        shuffle=True,
        seed=config.seed,
    )
    validation_loader = _loader(
        train_dataset,
        split.validation_indices,
        batch_size=config.batch_size,
        shuffle=False,
        seed=config.seed,
    )
    model = DynamicStockMixer(
        time_steps=request.lookback,
        channels=len(STOCKMIXER_INPUT_COLUMNS),
        hidden_dim=config.hidden_dim,
        market_dim=config.market_dim,
        scales=config.scales,
    ).to(compute_device)
    optimizer = AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    best_loss = float("inf")
    best_epoch = 0
    best_state: dict[str, Tensor] | None = None
    stale_epochs = 0
    history: list[EpochMetrics] = []
    for epoch in range(1, config.epochs + 1):
        train_loss = _train_epoch(
            model,
            train_loader,
            optimizer,
            compute_device,
            ranking_weight=config.ranking_weight,
        )
        validation_loss = _validation_loss(
            model,
            validation_loader,
            compute_device,
            ranking_weight=config.ranking_weight,
        )
        history.append(EpochMetrics(epoch, train_loss, validation_loss))
        if validation_loss < best_loss - config.minimum_improvement:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = {
                name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()
            }
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= config.patience:
                break
    if best_state is None:
        raise RuntimeError("training did not produce a finite validation checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    predictions, sample_ids, decision_times = _predict_test(
        model,
        test_dataset,
        batch_size=config.batch_size,
        device=compute_device,
    )
    return TrainedFold(
        fold_id=fold_id,
        model=model,
        normalizer=normalizer,
        split=split,
        best_epoch=best_epoch,
        history=tuple(history),
        model_state_digest=_state_digest(best_state),
        test_sample_ids=sample_ids,
        test_decision_times_us=decision_times,
        test_predictions=predictions,
    )


def _fit_normalizer(
    dataset: PanelWindowDataset, split: InnerValidationSplit
) -> FeatureNormalizer:
    from .dataset import fit_feature_normalizer

    return fit_feature_normalizer(dataset, sample_indices=split.train_indices)


def _loader(
    dataset: PanelWindowDataset,
    indices: tuple[int, ...],
    *,
    batch_size: int,
    shuffle: bool,
    seed: int,
) -> DataLoader[StockMixerBatch]:
    generator = torch.Generator().manual_seed(seed)
    return DataLoader(
        Subset(dataset, indices),
        batch_size=batch_size,
        shuffle=shuffle,
        generator=generator,
        num_workers=0,
    )


def _train_epoch(
    model: DynamicStockMixer,
    loader: DataLoader[StockMixerBatch],
    optimizer: AdamW,
    device: torch.device,
    *,
    ranking_weight: float,
) -> float:
    model.train()
    losses: list[float] = []
    for batch in loader:
        optimizer.zero_grad(set_to_none=True)
        prediction = _forward(model, batch, device)
        loss = masked_stock_loss(
            prediction,
            batch["labels"].to(device),
            batch["label_mask"].to(device),
            ranking_weight=ranking_weight,
        )
        loss.total.backward()
        optimizer.step()
        losses.append(float(loss.total.detach().cpu()))
    return _finite_mean(losses, "training")


def _validation_loss(
    model: DynamicStockMixer,
    loader: DataLoader[StockMixerBatch],
    device: torch.device,
    *,
    ranking_weight: float,
) -> float:
    model.eval()
    losses: list[float] = []
    with torch.inference_mode():
        for batch in loader:
            result = masked_stock_loss(
                _forward(model, batch, device),
                batch["labels"].to(device),
                batch["label_mask"].to(device),
                ranking_weight=ranking_weight,
            )
            losses.append(float(result.total.cpu()))
    return _finite_mean(losses, "validation")


def _predict_test(
    model: DynamicStockMixer,
    dataset: PanelWindowDataset,
    *,
    batch_size: int,
    device: torch.device,
) -> tuple[Tensor, tuple[int, ...], tuple[int, ...]]:
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    predictions: list[Tensor] = []
    sample_ids: list[int] = []
    decision_times: list[int] = []
    with torch.inference_mode():
        for batch in loader:
            predictions.append(_forward(model, batch, device).cpu())
            sample_ids.extend(int(value) for value in batch["sample_id"])
            decision_times.extend(int(value) for value in batch["decision_time_us"])
    return torch.cat(predictions), tuple(sample_ids), tuple(decision_times)


def _forward(
    model: DynamicStockMixer, batch: StockMixerBatch, device: torch.device
) -> Tensor:
    return model(
        batch["features"].to(device),
        batch["presence_mask"].to(device),
        batch["feature_mask"].to(device),
    )


def _finite_mean(values: list[float], stage: str) -> float:
    if not values:
        raise ValueError(f"{stage} loader produced no batches")
    result = sum(values) / len(values)
    if not torch.isfinite(torch.tensor(result)):
        raise RuntimeError(f"{stage} loss is non-finite")
    return result


def _state_digest(state: dict[str, Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        tensor = state[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(repr(tuple(tensor.shape)).encode("ascii"))
        digest.update(tensor.numpy().tobytes())
    return f"sha256:{digest.hexdigest()}"

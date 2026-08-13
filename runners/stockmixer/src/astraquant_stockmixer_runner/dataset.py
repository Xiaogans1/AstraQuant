"""Lazy tensor windows over the sealed shared StockMixer panel."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypedDict, cast

import numpy as np
import torch
from torch import Tensor
from torch.utils.data import Dataset

from .contracts import STOCKMIXER_INPUT_COLUMNS, StockMixerRequest


class StockMixerBatch(TypedDict):
    features: Tensor
    feature_mask: Tensor
    presence_mask: Tensor
    tradable_mask: Tensor
    label_mask: Tensor
    labels: Tensor
    sample_id: Tensor
    decision_time_us: Tensor


@dataclass(frozen=True, slots=True)
class FeatureNormalizer:
    """Per-indicator population statistics fitted on inner-train observations only."""

    mean: Tensor
    scale: Tensor
    count: int

    def __post_init__(self) -> None:
        if self.mean.ndim != 1 or self.scale.shape != self.mean.shape:
            raise ValueError("normalizer vectors must share one-dimensional shape")
        if self.count <= 0:
            raise ValueError("normalizer count must be positive")
        if not torch.isfinite(self.mean).all() or not torch.isfinite(self.scale).all():
            raise ValueError("normalizer statistics must be finite")
        if not self.scale.gt(0).all():
            raise ValueError("normalizer scale must be positive")


@dataclass(frozen=True, slots=True)
class _Sample:
    sample_id: int
    decision_time: datetime
    start: int
    end: int


class PanelWindowDataset(Dataset[StockMixerBatch]):
    """Select fold samples while sharing one dense time-by-stock panel in memory."""

    def __init__(
        self,
        request: StockMixerRequest,
        *,
        fold_id: str,
        segment: Literal["train", "test"],
        normalizer: FeatureNormalizer | None = None,
    ) -> None:
        if not fold_id:
            raise ValueError("fold_id must be non-empty")
        if segment not in {"train", "test"}:
            raise ValueError("segment must be train or test")
        stock_count = len(request.instrument_ids)
        if request.table.num_rows % stock_count:
            raise ValueError("panel row count is not divisible by instrument count")
        time_count = request.table.num_rows // stock_count
        self.request = request
        self.fold_id = fold_id
        self.segment = segment
        self.stock_count = stock_count
        self.time_count = time_count
        self.normalizer = normalizer

        columns = [
            np.asarray(request.table[name].to_numpy(zero_copy_only=False), dtype=np.float32)
            for name in STOCKMIXER_INPUT_COLUMNS
        ]
        self._features = np.stack(columns, axis=-1).reshape(time_count, stock_count, -1)
        self._feature_mask = np.asarray(
            request.table["feature_mask"].to_numpy(zero_copy_only=False), dtype=np.bool_
        ).reshape(time_count, stock_count)
        self._presence_mask = np.asarray(
            request.table["presence_mask"].to_numpy(zero_copy_only=False), dtype=np.bool_
        ).reshape(time_count, stock_count)
        self._tradable_mask = np.asarray(
            request.table["tradable_mask"].to_numpy(zero_copy_only=False), dtype=np.bool_
        ).reshape(time_count, stock_count)
        self._label_mask = np.asarray(
            request.table["label_mask"].to_numpy(zero_copy_only=False), dtype=np.bool_
        ).reshape(time_count, stock_count)
        self._labels = np.asarray(
            request.table["label"].to_numpy(zero_copy_only=False), dtype=np.float32
        ).reshape(time_count, stock_count)

        sample_rows = cast(list[dict[str, object]], request.samples.to_pylist())
        self._samples = tuple(
            _Sample(
                sample_id=int(row["sample_id"]),
                decision_time=cast(datetime, row["decision_time"]),
                start=int(row["window_start_index"]),
                end=int(row["window_end_index"]),
            )
            for row in sample_rows
            if row["fold_id"] == fold_id and row["segment"] == segment
        )
        if not self._samples:
            raise ValueError(f"no samples for {fold_id}/{segment}")
        if normalizer is not None and normalizer.mean.numel() != len(columns):
            raise ValueError("normalizer channel count mismatch")

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> StockMixerBatch:
        sample = self._samples[index]
        features = torch.from_numpy(self._features[sample.start : sample.end].copy()).transpose(
            0, 1
        )
        feature_mask = torch.from_numpy(
            self._feature_mask[sample.start : sample.end].copy()
        ).transpose(0, 1)
        if self.normalizer is not None:
            features = (features - self.normalizer.mean) / self.normalizer.scale
        features = torch.where(feature_mask.unsqueeze(-1), features, torch.zeros_like(features))
        endpoint = sample.end - 1
        return StockMixerBatch(
            features=features,
            feature_mask=feature_mask,
            presence_mask=torch.from_numpy(self._presence_mask[endpoint].copy()),
            tradable_mask=torch.from_numpy(self._tradable_mask[endpoint].copy()),
            label_mask=torch.from_numpy(self._label_mask[endpoint].copy()),
            labels=torch.from_numpy(self._labels[endpoint].copy()),
            sample_id=torch.tensor(sample.sample_id, dtype=torch.int64),
            decision_time_us=torch.tensor(
                round(sample.decision_time.timestamp() * 1_000_000), dtype=torch.int64
            ),
        )

    def with_normalizer(self, normalizer: FeatureNormalizer) -> PanelWindowDataset:
        return PanelWindowDataset(
            self.request,
            fold_id=self.fold_id,
            segment=self.segment,
            normalizer=normalizer,
        )

    @property
    def samples(self) -> tuple[_Sample, ...]:
        return self._samples


def fit_feature_normalizer(
    dataset: PanelWindowDataset,
    *,
    sample_indices: Sequence[int] | None = None,
    minimum_scale: float = 1e-6,
) -> FeatureNormalizer:
    """Fit once per unique panel observation reachable from selected samples."""

    if minimum_scale <= 0:
        raise ValueError("minimum_scale must be positive")
    indices = tuple(range(len(dataset))) if sample_indices is None else tuple(sample_indices)
    if not indices:
        raise ValueError("sample_indices must select at least one sample")
    selected_slots = np.zeros(dataset.time_count, dtype=np.bool_)
    for index in indices:
        if index < 0 or index >= len(dataset):
            raise IndexError("sample index is outside dataset")
        sample = dataset.samples[index]
        selected_slots[sample.start : sample.end] = True
    selected_features = dataset._features[selected_slots]
    selected_mask = dataset._feature_mask[selected_slots]
    values = selected_features[selected_mask]
    if not len(values):
        raise ValueError("selected training windows contain no valid features")
    tensor = torch.from_numpy(values.copy())
    return FeatureNormalizer(
        mean=tensor.mean(dim=0),
        scale=tensor.std(dim=0, correction=0).clamp_min(minimum_scale),
        count=len(values),
    )


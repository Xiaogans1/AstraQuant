"""Mask-aware regression and cross-sectional ranking objectives."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor
from torch.nn import functional as F


@dataclass(frozen=True, slots=True)
class StockLoss:
    total: Tensor
    regression: Tensor
    ranking: Tensor
    valid_labels: int
    valid_pairs: int


def masked_stock_loss(
    prediction: Tensor,
    target: Tensor,
    label_mask: Tensor,
    *,
    regression_weight: float = 1.0,
    ranking_weight: float = 0.1,
) -> StockLoss:
    """Combine valid-label MSE with pairwise logistic ordering per decision time."""

    if prediction.ndim != 2 or target.shape != prediction.shape:
        raise ValueError("prediction and target must share [batch, stock] shape")
    if label_mask.shape != prediction.shape or label_mask.dtype != torch.bool:
        raise ValueError("label_mask must be boolean and match prediction")
    if regression_weight < 0 or ranking_weight < 0:
        raise ValueError("loss weights must be non-negative")
    valid_labels = int(label_mask.sum().item())
    if valid_labels == 0:
        raise ValueError("batch must contain at least one valid label")
    if not torch.isfinite(prediction[label_mask]).all() or not torch.isfinite(
        target[label_mask]
    ).all():
        raise ValueError("valid predictions and labels must be finite")

    clean_prediction = torch.where(label_mask, prediction, torch.zeros_like(prediction))
    clean_target = torch.where(label_mask, target, torch.zeros_like(target))
    squared_error = (clean_prediction - clean_target).square()
    regression = squared_error[label_mask].mean()

    target_difference = clean_target.unsqueeze(2) - clean_target.unsqueeze(1)
    prediction_difference = clean_prediction.unsqueeze(2) - clean_prediction.unsqueeze(1)
    pair_mask = label_mask.unsqueeze(2) & label_mask.unsqueeze(1)
    pair_mask = pair_mask & target_difference.ne(0)
    valid_pairs = int(pair_mask.sum().item())
    if valid_pairs:
        signed_margin = target_difference.sign() * prediction_difference
        ranking = F.softplus(-signed_margin)[pair_mask].mean()
    else:
        ranking = prediction.sum() * 0.0
    total = regression_weight * regression + ranking_weight * ranking
    return StockLoss(
        total=total,
        regression=regression,
        ranking=ranking,
        valid_labels=valid_labels,
        valid_pairs=valid_pairs,
    )


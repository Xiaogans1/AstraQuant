"""Dynamic StockMixer v2 with causal history and decision-time context."""

from __future__ import annotations

from collections.abc import Sequence

import torch
from torch import Tensor, nn

from .model import IndicatorTimeMixer, MaskedMarketMixer


class DynamicStockMixerV2(nn.Module):
    """Fuse per-stock temporal history and current visible context before market mixing."""

    def __init__(
        self,
        *,
        time_steps: int,
        temporal_channels: int,
        context_channels: int,
        hidden_dim: int,
        market_dim: int,
        context_dim: int,
        scales: Sequence[int] = (1, 2, 4),
    ) -> None:
        super().__init__()
        if min(
            time_steps,
            temporal_channels,
            context_channels,
            hidden_dim,
            market_dim,
            context_dim,
        ) <= 0:
            raise ValueError("StockMixer v2 dimensions must be positive")
        self.time_steps = time_steps
        self.temporal_channels = temporal_channels
        self.context_channels = context_channels
        self.temporal = IndicatorTimeMixer(
            time_steps=time_steps,
            channels=temporal_channels,
            hidden_dim=hidden_dim,
            scales=scales,
        )
        self.context = nn.Sequential(
            nn.LayerNorm(context_channels),
            nn.Linear(context_channels, context_dim),
            nn.GELU(),
        )
        self.fusion = nn.Sequential(
            nn.Linear(hidden_dim + context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.market = MaskedMarketMixer(hidden_dim=hidden_dim, market_dim=market_dim)
        self.head = nn.Linear(hidden_dim, 1)

    def forward(
        self,
        temporal_features: Tensor,
        current_context: Tensor,
        presence_mask: Tensor,
        feature_mask: Tensor,
        context_mask: Tensor,
    ) -> Tensor:
        if temporal_features.ndim != 4 or temporal_features.shape[-2:] != (
            self.time_steps,
            self.temporal_channels,
        ):
            raise ValueError(
                "temporal_features must have shape [batch, stock, time, channel]"
            )
        if current_context.shape != (
            *temporal_features.shape[:2],
            self.context_channels,
        ):
            raise ValueError("current_context must have shape [batch, stock, context]")
        if presence_mask.shape != temporal_features.shape[:2] or presence_mask.dtype != torch.bool:
            raise ValueError("presence_mask must match [batch, stock]")
        if feature_mask.shape != temporal_features.shape[:3] or feature_mask.dtype != torch.bool:
            raise ValueError("feature_mask must match [batch, stock, time]")
        if context_mask.shape != temporal_features.shape[:2] or context_mask.dtype != torch.bool:
            raise ValueError("context_mask must match [batch, stock]")
        clean_temporal = torch.where(
            feature_mask.unsqueeze(-1), temporal_features, torch.zeros_like(temporal_features)
        )
        clean_context = torch.where(
            context_mask.unsqueeze(-1), current_context, torch.zeros_like(current_context)
        )
        if not torch.isfinite(clean_temporal).all() or not torch.isfinite(clean_context).all():
            raise ValueError("representable StockMixer v2 features must be finite")
        representation_mask = presence_mask & feature_mask.any(dim=-1) & context_mask
        if not representation_mask.any(dim=1).all():
            raise ValueError("each batch row must contain a representable security")
        weights = representation_mask.to(temporal_features.dtype).unsqueeze(-1)
        temporal_hidden = self.temporal(clean_temporal, feature_mask)
        context_hidden = self.context(clean_context)
        fused = self.fusion(torch.cat([temporal_hidden, context_hidden], dim=-1)) * weights
        mixed = self.market(fused, representation_mask)
        predictions = self.head(mixed).squeeze(-1)
        return predictions * representation_mask.to(predictions.dtype)

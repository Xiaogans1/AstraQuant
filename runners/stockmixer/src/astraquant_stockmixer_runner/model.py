"""Dynamic-universe adaptation of StockMixer's three mixing stages."""

from __future__ import annotations

from collections.abc import Sequence

import torch
from torch import Tensor, nn
from torch.nn import functional as F


class CausalTriangularMixer(nn.Module):
    """Learned causal time mixing equivalent to the official per-step TriU layers."""

    def __init__(self, time_steps: int) -> None:
        super().__init__()
        if time_steps <= 0:
            raise ValueError("time_steps must be positive")
        self.time_steps = time_steps
        self.weight = nn.Parameter(torch.empty(time_steps, time_steps))
        self.bias = nn.Parameter(torch.zeros(time_steps))
        self.register_buffer(
            "causal_mask",
            torch.tril(torch.ones(time_steps, time_steps, dtype=torch.bool)),
            persistent=False,
        )
        nn.init.xavier_uniform_(self.weight)

    def forward(self, inputs: Tensor) -> Tensor:
        if inputs.shape[-1] != self.time_steps:
            raise ValueError("causal mixer time dimension mismatch")
        weight = self.weight.masked_fill(~self.causal_mask, 0.0)
        return torch.matmul(inputs, weight.transpose(0, 1)) + self.bias


class IndicatorTimeMixer(nn.Module):
    """Mix indicators and causal multi-scale time representations per security."""

    def __init__(
        self,
        *,
        time_steps: int,
        channels: int,
        hidden_dim: int,
        scales: Sequence[int],
    ) -> None:
        super().__init__()
        exact_scales = tuple(scales)
        if min(time_steps, channels, hidden_dim) <= 0:
            raise ValueError("mixer dimensions must be positive")
        if not exact_scales or any(scale <= 0 or time_steps % scale for scale in exact_scales):
            raise ValueError("scales must be positive divisors of time_steps")
        self.time_steps = time_steps
        self.channels = channels
        self.scales = exact_scales
        self.indicator_norm = nn.LayerNorm(channels)
        self.indicator_mixer = nn.Sequential(
            nn.Linear(channels, hidden_dim),
            nn.Hardswish(),
            nn.Linear(hidden_dim, channels),
        )
        self.time_mixers = nn.ModuleList(
            CausalTriangularMixer(time_steps // scale) for scale in exact_scales
        )
        self.projection = nn.Linear(channels * len(exact_scales), hidden_dim)

    def forward(self, features: Tensor, feature_mask: Tensor) -> Tensor:
        if features.ndim != 4 or features.shape[-2:] != (self.time_steps, self.channels):
            raise ValueError("features must have shape [batch, stock, time, indicator]")
        if feature_mask.shape != features.shape[:-1] or feature_mask.dtype != torch.bool:
            raise ValueError("feature_mask must match [batch, stock, time]")
        clean = torch.where(feature_mask.unsqueeze(-1), features, torch.zeros_like(features))
        encoded = clean + self.indicator_mixer(self.indicator_norm(clean))
        encoded = encoded * feature_mask.unsqueeze(-1)
        branches = []
        for scale, time_mixer in zip(self.scales, self.time_mixers, strict=True):
            if scale == 1:
                pooled = encoded
                pooled_mask = feature_mask
            else:
                shape = (*encoded.shape[:-2], self.time_steps // scale, scale, self.channels)
                grouped = encoded.reshape(shape)
                grouped_mask = feature_mask.reshape(
                    *feature_mask.shape[:-1], self.time_steps // scale, scale
                )
                counts = grouped_mask.sum(dim=-1, keepdim=True).clamp_min(1)
                pooled = grouped.sum(dim=-2) / counts
                pooled_mask = grouped_mask.any(dim=-1)
            temporal = time_mixer(pooled.transpose(-1, -2)).transpose(-1, -2)
            temporal = F.hardswish(temporal) * pooled_mask.unsqueeze(-1)
            counts = pooled_mask.sum(dim=-1, keepdim=True).clamp_min(1)
            branches.append(temporal.sum(dim=-2) / counts)
        return self.projection(torch.cat(branches, dim=-1))


class MaskedMarketMixer(nn.Module):
    """Stock-to-market-to-stock mixing whose parameters do not depend on stock count."""

    def __init__(self, *, hidden_dim: int, market_dim: int) -> None:
        super().__init__()
        if min(hidden_dim, market_dim) <= 0:
            raise ValueError("market mixer dimensions must be positive")
        self.stock_to_market = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, market_dim),
            nn.Hardswish(),
        )
        self.market_to_stock = nn.Sequential(
            nn.Linear(hidden_dim + market_dim, hidden_dim),
            nn.Hardswish(),
            nn.Linear(hidden_dim, hidden_dim),
        )

    def forward(self, stock_hidden: Tensor, representation_mask: Tensor) -> Tensor:
        if stock_hidden.ndim != 3 or representation_mask.shape != stock_hidden.shape[:2]:
            raise ValueError("market mixer input shapes mismatch")
        if representation_mask.dtype != torch.bool:
            raise ValueError("representation_mask must be boolean")
        weights = representation_mask.to(stock_hidden.dtype).unsqueeze(-1)
        market = (self.stock_to_market(stock_hidden) * weights).sum(dim=1)
        market = market / weights.sum(dim=1).clamp_min(1.0)
        broadcast = market.unsqueeze(1).expand(-1, stock_hidden.shape[1], -1)
        update = self.market_to_stock(torch.cat([stock_hidden, broadcast], dim=-1))
        return (stock_hidden + update) * weights


class DynamicStockMixer(nn.Module):
    """Indicator, causal time and masked market mixing over any stock count."""

    def __init__(
        self,
        *,
        time_steps: int,
        channels: int,
        hidden_dim: int,
        market_dim: int,
        scales: Sequence[int] = (1, 2, 4),
    ) -> None:
        super().__init__()
        self.time_steps = time_steps
        self.channels = channels
        self.indicator_time = IndicatorTimeMixer(
            time_steps=time_steps,
            channels=channels,
            hidden_dim=hidden_dim,
            scales=scales,
        )
        self.market = MaskedMarketMixer(hidden_dim=hidden_dim, market_dim=market_dim)
        self.head = nn.Linear(hidden_dim, 1)

    def forward(
        self,
        features: Tensor,
        presence_mask: Tensor,
        feature_mask: Tensor,
    ) -> Tensor:
        if features.ndim != 4 or features.shape[-2:] != (self.time_steps, self.channels):
            raise ValueError("features must have shape [batch, stock, time, indicator]")
        if not torch.isfinite(features).all():
            raise ValueError("features must be finite")
        if presence_mask.shape != features.shape[:2] or presence_mask.dtype != torch.bool:
            raise ValueError("presence_mask must match [batch, stock]")
        if feature_mask.shape != features.shape[:3] or feature_mask.dtype != torch.bool:
            raise ValueError("feature_mask must match [batch, stock, time]")
        representation_mask = presence_mask & feature_mask.any(dim=-1)
        if not representation_mask.any(dim=1).all():
            raise ValueError("each batch row must contain a representable security")
        stock_hidden = self.indicator_time(features, feature_mask)
        mixed = self.market(stock_hidden, representation_mask)
        predictions = self.head(mixed).squeeze(-1)
        return predictions * representation_mask.to(predictions.dtype)

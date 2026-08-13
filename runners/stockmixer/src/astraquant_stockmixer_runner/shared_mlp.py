"""Dynamic-universe shared MLP baseline with masked market context."""

from __future__ import annotations

import torch
from torch import Tensor, nn


class CrossSectionalSharedMLP(nn.Module):
    """Encode every stock with shared weights and one masked market summary."""

    def __init__(
        self,
        *,
        feature_dim: int,
        hidden_dim: int,
        market_dim: int,
        encoder_layers: int,
        dropout: float,
    ) -> None:
        super().__init__()
        if min(feature_dim, hidden_dim, market_dim, encoder_layers) <= 0:
            raise ValueError("Shared MLP dimensions must be positive")
        if not 0 <= dropout < 1:
            raise ValueError("Shared MLP dropout must be in [0, 1)")
        encoder: list[nn.Module] = []
        input_dim = feature_dim
        for _ in range(encoder_layers):
            encoder.extend(
                [
                    nn.Linear(input_dim, hidden_dim),
                    nn.GELU(),
                    nn.LayerNorm(hidden_dim),
                    nn.Dropout(dropout),
                ]
            )
            input_dim = hidden_dim
        self.feature_dim = feature_dim
        self.encoder = nn.Sequential(*encoder)
        self.market_projection = nn.Sequential(
            nn.Linear(hidden_dim, market_dim),
            nn.GELU(),
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_dim + market_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, features: Tensor, presence_mask: Tensor) -> Tensor:
        if features.ndim != 3 or features.shape[-1] != self.feature_dim:
            raise ValueError("features must have shape [batch, stock, feature]")
        if presence_mask.shape != features.shape[:2] or presence_mask.dtype is not torch.bool:
            raise ValueError("presence_mask must match [batch, stock]")
        if not presence_mask.any(dim=1).all():
            raise ValueError("each batch row must contain a representable stock")
        weights = presence_mask.to(features.dtype).unsqueeze(-1)
        clean = torch.where(presence_mask.unsqueeze(-1), features, torch.zeros_like(features))
        if not torch.isfinite(clean).all():
            raise ValueError("representable stock features must be finite")
        hidden = self.encoder(clean) * weights
        market_values = self.market_projection(hidden) * weights
        market = market_values.sum(dim=1) / weights.sum(dim=1).clamp_min(1.0)
        broadcast = market.unsqueeze(1).expand(-1, hidden.shape[1], -1)
        scores = self.head(torch.cat([hidden, broadcast], dim=-1)).squeeze(-1)
        return scores * presence_mask.to(scores.dtype)

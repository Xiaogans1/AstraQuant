from __future__ import annotations

import pytest
import torch
from astraquant_stockmixer_runner.stockmixer_v2 import DynamicStockMixerV2


def _model() -> DynamicStockMixerV2:
    torch.manual_seed(20260814)
    model = DynamicStockMixerV2(
        time_steps=4,
        temporal_channels=6,
        context_channels=3,
        hidden_dim=8,
        market_dim=4,
        context_dim=4,
        scales=(1, 2),
    )
    model.eval()
    return model


def _inputs() -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    temporal = torch.randn(2, 3, 4, 6)
    context = torch.randn(2, 3, 3)
    presence = torch.tensor([[True, True, True], [True, False, True]])
    feature_mask = torch.ones(2, 3, 4, dtype=torch.bool)
    feature_mask[1, 1] = False
    context_mask = torch.tensor([[True, True, True], [True, False, True]])
    return temporal, context, presence, feature_mask, context_mask


def test_permuting_instruments_only_permutes_predictions() -> None:
    model = _model()
    temporal, context, presence, feature_mask, context_mask = _inputs()
    permutation = torch.tensor([2, 0, 1])

    expected = model(temporal, context, presence, feature_mask, context_mask)[:, permutation]
    actual = model(
        temporal[:, permutation],
        context[:, permutation],
        presence[:, permutation],
        feature_mask[:, permutation],
        context_mask[:, permutation],
    )

    torch.testing.assert_close(actual, expected)


def test_masked_padding_cannot_change_valid_predictions() -> None:
    model = _model()
    temporal, context, presence, feature_mask, context_mask = _inputs()
    base = model(temporal, context, presence, feature_mask, context_mask)
    padded_temporal = torch.cat(
        [temporal, torch.full((2, 1, 4, 6), 1e9)], dim=1
    )
    padded_context = torch.cat([context, torch.full((2, 1, 3), 1e9)], dim=1)
    padded_presence = torch.cat(
        [presence, torch.zeros(2, 1, dtype=torch.bool)], dim=1
    )
    padded_feature_mask = torch.cat(
        [feature_mask, torch.zeros(2, 1, 4, dtype=torch.bool)], dim=1
    )
    padded_context_mask = torch.cat(
        [context_mask, torch.zeros(2, 1, dtype=torch.bool)], dim=1
    )

    expanded = model(
        padded_temporal,
        padded_context,
        padded_presence,
        padded_feature_mask,
        padded_context_mask,
    )

    torch.testing.assert_close(expanded[:, :3], base)
    assert expanded[:, 3].eq(0).all()


def test_rejects_present_stock_without_current_context() -> None:
    model = _model()
    temporal, context, presence, feature_mask, context_mask = _inputs()
    context_mask[0] = False

    with pytest.raises(ValueError, match="representable security"):
        model(temporal, context, presence, feature_mask, context_mask)

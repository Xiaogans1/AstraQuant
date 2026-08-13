from __future__ import annotations

import pytest
import torch
from astraquant_stockmixer_runner.shared_mlp import CrossSectionalSharedMLP


def _model() -> CrossSectionalSharedMLP:
    torch.manual_seed(7)
    model = CrossSectionalSharedMLP(
        feature_dim=6,
        hidden_dim=8,
        market_dim=4,
        encoder_layers=2,
        dropout=0.0,
    )
    model.eval()
    return model


def test_shared_mlp_is_equivariant_to_stock_permutation() -> None:
    model = _model()
    features = torch.arange(24, dtype=torch.float32).reshape(1, 4, 6) / 10
    mask = torch.tensor([[True, True, True, True]])
    order = torch.tensor([2, 0, 3, 1])

    expected = model(features, mask)
    permuted = model(features[:, order], mask[:, order])

    assert torch.allclose(permuted, expected[:, order])


def test_masked_stock_cannot_change_valid_outputs() -> None:
    model = _model()
    features = torch.arange(18, dtype=torch.float32).reshape(1, 3, 6) / 10
    mask = torch.tensor([[True, True, True]])
    expected = model(features, mask)
    padded = torch.cat([features, torch.full((1, 1, 6), float("nan"))], dim=1)
    padded_mask = torch.tensor([[True, True, True, False]])

    actual = model(padded, padded_mask)

    assert torch.allclose(actual[:, :3], expected)
    assert actual[0, 3].item() == 0.0


def test_shared_mlp_accepts_variable_stock_count_and_rejects_empty_cohort() -> None:
    model = _model()

    assert model(torch.ones((2, 5, 6)), torch.ones((2, 5), dtype=torch.bool)).shape == (
        2,
        5,
    )
    with pytest.raises(ValueError, match="representable"):
        model(torch.ones((1, 2, 6)), torch.zeros((1, 2), dtype=torch.bool))

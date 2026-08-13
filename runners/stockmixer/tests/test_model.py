from __future__ import annotations

import pytest
import torch
from astraquant_stockmixer_runner.model import (
    CausalTriangularMixer,
    DynamicStockMixer,
)


def _model() -> DynamicStockMixer:
    torch.manual_seed(20260813)
    model = DynamicStockMixer(
        time_steps=4,
        channels=5,
        hidden_dim=8,
        market_dim=4,
        scales=(1, 2),
    )
    model.eval()
    return model


def test_masked_instrument_cannot_change_valid_predictions() -> None:
    model = _model()
    valid = torch.randn(1, 2, 4, 5)
    presence = torch.tensor([[True, True]])
    feature_mask = torch.ones(1, 2, 4, dtype=torch.bool)

    base = model(valid, presence, feature_mask)
    padded = torch.cat([valid, torch.full((1, 1, 4, 5), 1e9)], dim=1)
    padded_presence = torch.tensor([[True, True, False]])
    padded_feature_mask = torch.cat(
        [feature_mask, torch.zeros(1, 1, 4, dtype=torch.bool)], dim=1
    )
    expanded = model(padded, padded_presence, padded_feature_mask)

    torch.testing.assert_close(expanded[:, :2], base)
    assert expanded[0, 2].item() == 0.0


def test_permuting_instruments_only_permutes_predictions() -> None:
    model = _model()
    features = torch.randn(2, 3, 4, 5)
    presence = torch.tensor([[True, True, True], [True, False, True]])
    feature_mask = torch.tensor(
        [
            [[True, True, True, True]] * 3,
            [
                [True, True, True, True],
                [False, False, False, False],
                [False, True, True, True],
            ],
        ]
    )
    permutation = torch.tensor([2, 0, 1])

    expected = model(features, presence, feature_mask)[:, permutation]
    actual = model(
        features[:, permutation],
        presence[:, permutation],
        feature_mask[:, permutation],
    )

    torch.testing.assert_close(actual, expected)


def test_masked_time_slot_value_cannot_change_prediction() -> None:
    model = _model()
    features = torch.randn(1, 2, 4, 5)
    presence = torch.tensor([[True, True]])
    feature_mask = torch.ones(1, 2, 4, dtype=torch.bool)
    feature_mask[0, 1, 2] = False
    changed = features.clone()
    changed[0, 1, 2] = 1e9

    expected = model(features, presence, feature_mask)
    actual = model(changed, presence, feature_mask)

    torch.testing.assert_close(actual, expected)


def test_causal_mixer_earlier_outputs_ignore_later_inputs() -> None:
    mixer = CausalTriangularMixer(time_steps=4)
    with torch.no_grad():
        mixer.weight.fill_(1.0)
        mixer.bias.zero_()
    first = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
    changed_future = torch.tensor([[1.0, 2.0, 300.0, 400.0]])

    expected = mixer(first)
    actual = mixer(changed_future)

    torch.testing.assert_close(actual[:, :2], expected[:, :2])
    assert not torch.equal(actual[:, 2:], expected[:, 2:])


def test_rejects_batch_without_any_representable_security() -> None:
    model = _model()
    features = torch.zeros(1, 2, 4, 5)
    presence = torch.tensor([[True, True]])
    feature_mask = torch.zeros(1, 2, 4, dtype=torch.bool)

    with pytest.raises(ValueError, match="representable security"):
        model(features, presence, feature_mask)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is unavailable")
def test_cuda_forward_preserves_shape_and_finite_contract() -> None:
    model = _model().cuda()
    features = torch.randn(2, 3, 4, 5, device="cuda")
    presence = torch.tensor(
        [[True, True, True], [True, False, True]], dtype=torch.bool, device="cuda"
    )
    feature_mask = torch.ones(2, 3, 4, dtype=torch.bool, device="cuda")
    feature_mask[1, 1] = False

    predictions = model(features, presence, feature_mask)

    assert predictions.shape == (2, 3)
    assert torch.isfinite(predictions).all()
    assert predictions[1, 1].item() == 0.0

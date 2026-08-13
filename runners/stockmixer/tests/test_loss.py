from __future__ import annotations

import pytest
import torch
from astraquant_stockmixer_runner.loss import masked_stock_loss


def test_correct_cross_section_has_lower_ranking_loss_than_reversed() -> None:
    target = torch.tensor([[0.01, 0.02, 0.03]])
    mask = torch.ones_like(target, dtype=torch.bool)

    correct = masked_stock_loss(target, target, mask)
    reversed_order = masked_stock_loss(target.flip(dims=(1,)), target, mask)

    assert correct.ranking.item() < reversed_order.ranking.item()


def test_masked_labels_cannot_change_any_loss_component() -> None:
    prediction = torch.tensor([[0.1, 0.2, -9_999.0]])
    target = torch.tensor([[0.0, 0.3, 9_999.0]])
    mask = torch.tensor([[True, True, False]])

    expected = masked_stock_loss(prediction[:, :2], target[:, :2], mask[:, :2])
    actual = masked_stock_loss(prediction, target, mask)

    torch.testing.assert_close(actual.total, expected.total)
    torch.testing.assert_close(actual.regression, expected.regression)
    torch.testing.assert_close(actual.ranking, expected.ranking)


def test_single_valid_label_has_zero_ranking_loss() -> None:
    result = masked_stock_loss(
        torch.tensor([[0.1, 500.0]]),
        torch.tensor([[0.2, -500.0]]),
        torch.tensor([[True, False]]),
    )

    assert result.regression.item() == pytest.approx(0.01)
    assert result.ranking.item() == 0.0


def test_rejects_batch_without_valid_labels() -> None:
    values = torch.zeros(2, 3)
    with pytest.raises(ValueError, match="valid label"):
        masked_stock_loss(values, values, torch.zeros_like(values, dtype=torch.bool))


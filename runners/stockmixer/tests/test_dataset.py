from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pytest
import torch
from astraquant_stockmixer_runner.contracts import StockMixerRequest
from astraquant_stockmixer_runner.dataset import (
    PanelWindowDataset,
    fit_feature_normalizer,
)


def _request() -> StockMixerRequest:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    times = [start + timedelta(days=index) for index in range(4)]
    instruments = ("510300.SH", "510500.SH")
    rows: list[dict[str, object]] = []
    for slot, slot_time in enumerate(times):
        for stock, instrument_id in enumerate(instruments):
            value = float(slot * 10 + stock + 1)
            feature_mask = not (slot == 1 and stock == 1)
            rows.append(
                {
                    "slot_time": slot_time,
                    "instrument_id": instrument_id,
                    "event_time": slot_time if feature_mask else None,
                    "feature_mask": feature_mask,
                    "presence_mask": True,
                    "tradable_mask": feature_mask,
                    "label_mask": feature_mask,
                    "label": value / 100 if feature_mask else 0.0,
                    "open": value if feature_mask else 0.0,
                    "high": value + 1 if feature_mask else 0.0,
                    "low": value - 1 if feature_mask else 0.0,
                    "close": value + 0.5 if feature_mask else 0.0,
                    "volume": value * 100 if feature_mask else 0.0,
                }
            )
    samples = pa.Table.from_pylist(
        [
            {
                "fold_id": "fold-0",
                "segment": "train",
                "sample_id": 0,
                "decision_time": times[1],
                "window_start_index": 0,
                "window_end_index": 2,
            },
            {
                "fold_id": "fold-0",
                "segment": "train",
                "sample_id": 1,
                "decision_time": times[2],
                "window_start_index": 1,
                "window_end_index": 3,
            },
            {
                "fold_id": "fold-0",
                "segment": "test",
                "sample_id": 2,
                "decision_time": times[3],
                "window_start_index": 2,
                "window_end_index": 4,
            },
        ]
    )
    return StockMixerRequest(
        content_digest=f"sha256:{'1' * 64}",
        lookback=2,
        label_name="next_return",
        instrument_ids=instruments,
        sample_count=3,
        table=pa.Table.from_pylist(rows),
        samples=samples,
    )


def test_dataset_slices_shared_panel_into_stock_windows() -> None:
    dataset = PanelWindowDataset(_request(), fold_id="fold-0", segment="train")

    first = dataset[0]

    assert len(dataset) == 2
    assert first["features"].shape == (2, 2, 5)
    assert first["feature_mask"].tolist() == [[True, True], [True, False]]
    assert first["presence_mask"].tolist() == [True, True]
    assert first["label_mask"].tolist() == [True, False]
    assert first["labels"].tolist() == pytest.approx([0.11, 0.0])
    assert first["sample_id"].item() == 0
    assert first["decision_time_us"].item() > 0
    torch.testing.assert_close(
        first["features"][0, :, 0],
        torch.tensor([1.0, 11.0]),
    )


def test_normalizer_uses_only_selected_training_windows_once() -> None:
    dataset = PanelWindowDataset(_request(), fold_id="fold-0", segment="train")

    normalizer = fit_feature_normalizer(dataset, sample_indices=[0])
    normalized = dataset.with_normalizer(normalizer)[1]

    # sample 0 covers slots 0 and 1; the masked 510500 slot is excluded.
    assert normalizer.count == 3
    assert normalizer.mean[0].item() == pytest.approx((1 + 2 + 11) / 3)
    # Slot 2 was not used for fitting, so its much larger value remains far from zero.
    assert normalized["features"][0, 1, 0].item() > 2.0
    # Masked cells remain exactly zero after normalization.
    assert normalized["features"][1, 0].eq(0).all()


def test_rejects_missing_fold_or_empty_normalizer_selection() -> None:
    request = _request()
    with pytest.raises(ValueError, match="no samples"):
        PanelWindowDataset(request, fold_id="fold-x", segment="train")

    dataset = PanelWindowDataset(request, fold_id="fold-0", segment="train")
    with pytest.raises(ValueError, match="sample_indices"):
        fit_feature_normalizer(dataset, sample_indices=[])


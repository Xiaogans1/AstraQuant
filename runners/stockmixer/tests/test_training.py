from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pytest
import torch
from astraquant_stockmixer_runner.contracts import StockMixerRequest
from astraquant_stockmixer_runner.dataset import PanelWindowDataset
from astraquant_stockmixer_runner.training import (
    TrainingConfig,
    split_inner_validation,
    train_fold,
)


def _request(*, outer_label: float = 0.5) -> StockMixerRequest:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    times = [start + timedelta(days=index) for index in range(7)]
    instruments = ("510300.SH", "510500.SH")
    panel: list[dict[str, object]] = []
    for slot, slot_time in enumerate(times):
        for stock, instrument_id in enumerate(instruments):
            feature = float(1 + slot + stock / 10)
            label = (stock * 2 - 1) * feature / 100
            if slot >= 5:
                label = outer_label * (1 if stock else -1)
            panel.append(
                {
                    "slot_time": slot_time,
                    "instrument_id": instrument_id,
                    "event_time": slot_time,
                    "feature_mask": True,
                    "presence_mask": True,
                    "tradable_mask": True,
                    "label_mask": True,
                    "label": label,
                    "open": feature,
                    "high": feature + 0.2,
                    "low": feature - 0.2,
                    "close": feature + 0.1,
                    "volume": feature * 1_000,
                }
            )
    samples = []
    for sample_id, decision_time in enumerate(times):
        samples.append(
            {
                "fold_id": "fold-0",
                "segment": "train" if sample_id < 5 else "test",
                "sample_id": sample_id,
                "decision_time": decision_time,
                "window_start_index": sample_id,
                "window_end_index": sample_id + 1,
            }
        )
    return StockMixerRequest(
        content_digest=f"sha256:{'2' * 64}",
        lookback=1,
        label_name="next_return",
        instrument_ids=instruments,
        sample_count=len(samples),
        table=pa.Table.from_pylist(panel),
        samples=pa.Table.from_pylist(samples),
    )


def _config() -> TrainingConfig:
    return TrainingConfig(
        seed=20260813,
        epochs=4,
        batch_size=2,
        learning_rate=0.01,
        ranking_weight=0.1,
        validation_time_count=2,
        purge_time_count=1,
        patience=2,
        hidden_dim=8,
        market_dim=4,
        scales=(1,),
    )


def test_inner_validation_keeps_whole_times_and_purges_boundary() -> None:
    dataset = PanelWindowDataset(_request(), fold_id="fold-0", segment="train")

    split = split_inner_validation(
        dataset,
        validation_time_count=2,
        purge_time_count=1,
    )

    assert split.train_indices == (0, 1)
    assert split.purged_indices == (2,)
    assert split.validation_indices == (3, 4)
    assert split.train_end_time_us < split.validation_start_time_us


def test_training_is_deterministic_and_predicts_outer_test_after_freeze() -> None:
    first = train_fold(_request(), fold_id="fold-0", config=_config(), device="cpu")
    second = train_fold(_request(), fold_id="fold-0", config=_config(), device="cpu")

    assert first.model_state_digest == second.model_state_digest
    assert first.best_epoch == second.best_epoch
    assert first.test_sample_ids == (5, 6)
    torch.testing.assert_close(first.test_predictions, second.test_predictions, rtol=0, atol=0)
    assert first.test_predictions.shape == (2, 2)


def test_outer_test_labels_cannot_change_training_or_predictions() -> None:
    normal = train_fold(_request(outer_label=0.5), fold_id="fold-0", config=_config())
    poisoned = train_fold(_request(outer_label=50_000), fold_id="fold-0", config=_config())

    assert normal.model_state_digest == poisoned.model_state_digest
    assert normal.best_epoch == poisoned.best_epoch
    torch.testing.assert_close(normal.test_predictions, poisoned.test_predictions, rtol=0, atol=0)


def test_training_module_enables_deterministic_cublas_workspace() -> None:
    assert os.environ["CUBLAS_WORKSPACE_CONFIG"] in {":4096:8", ":16:8"}


def test_existing_cublas_workspace_value_is_not_overwritten(monkeypatch) -> None:
    monkeypatch.setenv("CUBLAS_WORKSPACE_CONFIG", ":16:8")
    # CPU training must not mutate CUDA process policy.
    train_fold(_request(), fold_id="fold-0", config=_config(), device="cpu")
    assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == ":16:8"


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is unavailable")
def test_small_fold_trains_with_deterministic_cuda() -> None:
    first = train_fold(_request(), fold_id="fold-0", config=_config(), device="cuda")
    second = train_fold(_request(), fold_id="fold-0", config=_config(), device="cuda")

    assert first.model_state_digest == second.model_state_digest
    torch.testing.assert_close(first.test_predictions, second.test_predictions, rtol=0, atol=0)

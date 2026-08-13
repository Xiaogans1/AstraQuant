from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]
import pytest
from astraquant_kronos_runner.contracts import KRONOS_UPSTREAM_COMMIT
from astraquant_kronos_runner.upstream_adapter import (
    OfficialKronosBackend,
    select_device,
    verify_upstream_source,
)


class FakeCuda:
    def __init__(self, available: bool) -> None:
        self.available = available
        self.seeds: list[int] = []

    def is_available(self) -> bool:
        return self.available

    def manual_seed_all(self, seed: int) -> None:
        self.seeds.append(seed)


class FakeTorch:
    __version__ = "2.7.1"

    def __init__(self, cuda_available: bool) -> None:
        self.cuda = FakeCuda(cuda_available)
        self.seeds: list[int] = []

    def manual_seed(self, seed: int) -> None:
        self.seeds.append(seed)


class FakePredictor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def predict(
        self,
        frame: pd.DataFrame,
        x_timestamp: pd.Series,
        y_timestamp: pd.Series,
        pred_len: int,
        *,
        T: float,
        top_k: int,
        top_p: float,
        sample_count: int,
        verbose: bool,
    ) -> pd.DataFrame:
        self.calls.append(
            {
                "frame": frame.copy(),
                "x_timestamp": x_timestamp.copy(),
                "y_timestamp": y_timestamp.copy(),
                "pred_len": pred_len,
                "temperature": T,
                "top_k": top_k,
                "top_p": top_p,
                "sample_count": sample_count,
                "verbose": verbose,
            }
        )
        call = len(self.calls)
        return pd.DataFrame(
            {"close": [10.0 + call / 10 + index / 100 for index in range(pred_len)]},
            index=y_timestamp,
        )


def _window() -> list[dict[str, object]]:
    start = datetime(2026, 8, 7, 6, 45, tzinfo=UTC)
    return [
        {
            "event_time": start + timedelta(minutes=index),
            "open": 10.0 + index / 10,
            "high": 10.2 + index / 10,
            "low": 9.8 + index / 10,
            "close": 10.1 + index / 10,
            "volume": 100_000.0,
            "amount": 1_000_000.0,
        }
        for index in range(3)
    ]


def test_select_device_obeys_explicit_fallback_policy() -> None:
    assert select_device("AUTO", allow_cpu_fallback=False, cuda_available=True) == "cuda:0"
    assert select_device("AUTO", allow_cpu_fallback=False, cuda_available=False) == "cpu"
    assert select_device("CPU", allow_cpu_fallback=False, cuda_available=True) == "cpu"
    assert select_device("CUDA", allow_cpu_fallback=True, cuda_available=False) == "cpu"
    with pytest.raises(ValueError, match="CUDA is unavailable"):
        select_device("CUDA", allow_cpu_fallback=False, cuda_available=False)


def test_retains_each_official_sample_path_and_seeds_it_repeatably() -> None:
    predictor = FakePredictor()
    torch_module = FakeTorch(cuda_available=True)
    backend = OfficialKronosBackend(
        predictor=predictor,
        torch_module=torch_module,
        device="cuda:0",
    )
    forecasts = tuple(
        datetime(2026, 8, 7, 6, 48 + index, tzinfo=UTC) for index in range(2)
    )

    first = backend.predict_paths(
        window=_window(),
        forecast_times=forecasts,
        seed=2**60,
        temperature=0.8,
        top_k=5,
        top_p=0.9,
        sample_count=3,
    )
    first_seeds = torch_module.seeds.copy()
    predictor.calls.clear()
    torch_module.seeds.clear()
    torch_module.cuda.seeds.clear()
    second = backend.predict_paths(
        window=_window(),
        forecast_times=forecasts,
        seed=2**60,
        temperature=0.8,
        top_k=5,
        top_p=0.9,
        sample_count=3,
    )

    assert first == second
    assert len(first) == 3
    assert first_seeds == torch_module.seeds
    assert len(set(first_seeds)) == 3
    assert all(call["sample_count"] == 1 for call in predictor.calls)
    assert all(call["verbose"] is False for call in predictor.calls)
    frame = predictor.calls[0]["frame"]
    x_timestamp = predictor.calls[0]["x_timestamp"]
    y_timestamp = predictor.calls[0]["y_timestamp"]
    assert isinstance(frame, pd.DataFrame)
    assert isinstance(x_timestamp, pd.Series)
    assert isinstance(y_timestamp, pd.Series)
    assert frame.columns.tolist() == [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    assert x_timestamp.dt.tz is not None
    assert y_timestamp.dt.tz is not None


def test_rejects_invalid_official_output() -> None:
    class BrokenPredictor(FakePredictor):
        def predict(self, *args: object, **kwargs: object) -> pd.DataFrame:
            return pd.DataFrame({"close": [float("nan")]})

    backend = OfficialKronosBackend(
        predictor=BrokenPredictor(),
        torch_module=FakeTorch(cuda_available=False),
        device="cpu",
    )
    with pytest.raises(ValueError, match="path length or values"):
        backend.predict_paths(
            window=_window(),
            forecast_times=[datetime(2026, 8, 7, 7, 0, tzinfo=UTC)],
            seed=7,
            temperature=1.0,
            top_k=0,
            top_p=0.9,
            sample_count=1,
        )


def test_checked_in_upstream_is_clean_and_at_frozen_commit() -> None:
    upstream = Path(__file__).parents[3] / "external" / "Kronos"
    assert verify_upstream_source(upstream) == KRONOS_UPSTREAM_COMMIT

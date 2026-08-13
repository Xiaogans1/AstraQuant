"""Read-only adapter over the pinned official Kronos implementation."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import random
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from .contracts import KRONOS_UPSTREAM_COMMIT, validate_request


class Predictor(Protocol):
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
    ) -> pd.DataFrame: ...

    def predict_batch(
        self,
        frames: list[pd.DataFrame],
        x_timestamps: list[pd.Series],
        y_timestamps: list[pd.Series],
        pred_len: int,
        *,
        T: float,
        top_k: int,
        top_p: float,
        sample_count: int,
        verbose: bool,
    ) -> list[pd.DataFrame]: ...


class OfficialKronosBackend:
    """Retain each sampled official path instead of averaging paths upstream."""

    def __init__(self, *, predictor: Predictor, torch_module: Any, device: str) -> None:
        self._predictor = predictor
        self._torch = torch_module
        self._device = device

    def environment_identity(self) -> dict[str, str]:
        return {
            "python": sys.version.split()[0],
            "torch": str(self._torch.__version__),
            "device": self._device,
        }

    def predict_paths(
        self,
        *,
        window: Sequence[dict[str, object]],
        forecast_times: Sequence[datetime],
        seed: int,
        temperature: float,
        top_k: int,
        top_p: float,
        sample_count: int,
    ) -> Sequence[Sequence[float]]:
        frame = pd.DataFrame.from_records(window)[
            ["open", "high", "low", "close", "volume", "amount"]
        ].astype("float64")
        x_timestamp = _timestamps([row["event_time"] for row in window], "window")
        y_timestamp = _timestamps(forecast_times, "forecast")
        paths: list[tuple[float, ...]] = []
        for sample_index in range(sample_count):
            path_seed = _path_seed(seed, sample_index)
            _seed_everything(path_seed, self._torch)
            prediction = self._predictor.predict(
                frame,
                x_timestamp,
                y_timestamp,
                len(y_timestamp),
                T=temperature,
                top_k=top_k,
                top_p=top_p,
                sample_count=1,
                verbose=False,
            )
            if not isinstance(prediction, pd.DataFrame) or "close" not in prediction:
                raise ValueError("official Kronos output must contain a close path")
            path = tuple(float(value) for value in prediction["close"].tolist())
            if len(path) != len(y_timestamp) or any(
                not math.isfinite(value) or value <= 0 for value in path
            ):
                raise ValueError("official Kronos path length or values are invalid")
            paths.append(path)
        return paths

    def predict_batch_paths(
        self,
        *,
        windows: Sequence[Sequence[dict[str, object]]],
        forecast_times: Sequence[Sequence[datetime]],
        seeds: Sequence[int],
        temperature: float,
        top_k: int,
        top_p: float,
        sample_count: int,
    ) -> Sequence[Sequence[Sequence[float]]]:
        if not windows or not (
            len(windows) == len(forecast_times) == len(seeds)
        ):
            raise ValueError("official Kronos batch input coverage mismatch")
        context_lengths = {len(window) for window in windows}
        horizon_lengths = {len(times) for times in forecast_times}
        if len(context_lengths) != 1 or len(horizon_lengths) != 1 or 0 in horizon_lengths:
            raise ValueError("official Kronos batch requires equal non-empty shapes")
        results: list[list[tuple[float, ...]]] = [[] for _ in windows]
        batch_size = 64
        for start in range(0, len(windows), batch_size):
            stop = min(start + batch_size, len(windows))
            chunk_windows = windows[start:stop]
            chunk_times = forecast_times[start:stop]
            chunk_seeds = seeds[start:stop]
            frames = [_frame(window) for window in chunk_windows]
            x_timestamps = [
                _timestamps([row["event_time"] for row in window], "window")
                for window in chunk_windows
            ]
            y_timestamps = [_timestamps(times, "forecast") for times in chunk_times]
            prediction_length = len(y_timestamps[0])
            for sample_index in range(sample_count):
                _seed_everything(
                    _batch_seed(chunk_seeds, sample_index), self._torch
                )
                predictions = self._predictor.predict_batch(
                    frames,
                    x_timestamps,
                    y_timestamps,
                    prediction_length,
                    T=temperature,
                    top_k=top_k,
                    top_p=top_p,
                    sample_count=1,
                    verbose=False,
                )
                if len(predictions) != len(chunk_windows):
                    raise ValueError("official Kronos batch output coverage mismatch")
                for offset, prediction in enumerate(predictions):
                    path = _close_path(prediction, prediction_length)
                    results[start + offset].append(path)
        return results


def select_device(
    preferred: str, *, allow_cpu_fallback: bool, cuda_available: bool
) -> str:
    if preferred == "CPU":
        return "cpu"
    if preferred == "AUTO":
        return "cuda:0" if cuda_available else "cpu"
    if preferred != "CUDA":
        raise ValueError("unsupported Kronos device policy")
    if cuda_available:
        return "cuda:0"
    if allow_cpu_fallback:
        return "cpu"
    raise ValueError("CUDA is unavailable and CPU fallback is disabled")


def verify_upstream_source(upstream_root: Path) -> str:
    root = upstream_root.resolve()
    if not (root / "model" / "kronos.py").is_file():
        raise ValueError("official Kronos source root is incomplete")
    commit = _git(root, "rev-parse", "HEAD")
    if commit != KRONOS_UPSTREAM_COMMIT:
        raise ValueError("official Kronos source commit mismatch")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("official Kronos source has tracked modifications")
    return commit


def create_official_backend(
    request_path: Path, *, root: Path, upstream_root: Path
) -> OfficialKronosBackend:
    request = validate_request(
        json.loads(request_path.read_text(encoding="utf-8")), root=root
    )
    verify_upstream_source(upstream_root)
    official = _load_official_module(upstream_root)
    torch_module = importlib.import_module("torch")
    policy = _object(request["device_policy"], "device_policy")
    device = select_device(
        str(policy["preferred"]),
        allow_cpu_fallback=bool(policy["allow_cpu_fallback"]),
        cuda_available=bool(torch_module.cuda.is_available()),
    )
    model = _load_artifact(official.Kronos, request["model"], root, "model")
    tokenizer = _load_artifact(
        official.KronosTokenizer, request["tokenizer"], root, "tokenizer"
    )
    model.eval()
    tokenizer.eval()
    predictor = official.KronosPredictor(
        model,
        tokenizer,
        device=device,
        max_context=_integer(request["context_length"], "context_length"),
    )
    return OfficialKronosBackend(
        predictor=predictor, torch_module=torch_module, device=device
    )


def _load_artifact(
    artifact_class: Any, value: object, root: Path, name: str
) -> Any:
    artifact = _object(value, name)
    weights = _object(artifact["weights"], f"{name} weights")
    weights_path = (root.resolve() / str(weights["path"])).resolve()
    return artifact_class.from_pretrained(str(weights_path.parent))


def _load_official_module(upstream_root: Path) -> Any:
    root = upstream_root.resolve()
    existing = sys.modules.get("model")
    if existing is not None:
        location = Path(str(getattr(existing, "__file__", ""))).resolve()
        if root not in location.parents:
            raise ValueError("Python module name 'model' is already owned by another package")
        return existing
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("model")
    finally:
        sys.path.remove(str(root))
    location = Path(str(getattr(module, "__file__", ""))).resolve()
    if root not in location.parents:
        raise ValueError("official Kronos import escaped the pinned source root")
    return module


def _timestamps(values: Sequence[object], name: str) -> pd.Series:
    timestamps = pd.Series(pd.to_datetime(list(values), utc=True))
    if timestamps.isna().any() or not timestamps.is_monotonic_increasing:
        raise ValueError(f"{name} timestamps must be valid and ordered")
    return timestamps


def _frame(window: Sequence[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame.from_records(window)[
        ["open", "high", "low", "close", "volume", "amount"]
    ].astype("float64")


def _close_path(prediction: object, prediction_length: int) -> tuple[float, ...]:
    if not isinstance(prediction, pd.DataFrame) or "close" not in prediction:
        raise ValueError("official Kronos output must contain a close path")
    path = tuple(float(value) for value in prediction["close"].tolist())
    if len(path) != prediction_length or any(
        not math.isfinite(value) or value <= 0 for value in path
    ):
        raise ValueError("official Kronos path length or values are invalid")
    return path


def _path_seed(seed: int, sample_index: int) -> int:
    encoded = json.dumps([seed, sample_index], separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")


def _batch_seed(seeds: Sequence[int], sample_index: int) -> int:
    if len(seeds) == 1:
        return _path_seed(seeds[0], sample_index)
    encoded = json.dumps([list(seeds), sample_index], separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")


def _seed_everything(seed: int, torch_module: Any) -> None:
    seed32 = seed % (2**32)
    seed63 = seed % (2**63 - 1)
    random.seed(seed)
    np.random.seed(seed32)
    torch_module.manual_seed(seed63)
    if torch_module.cuda.is_available():
        torch_module.cuda.manual_seed_all(seed63)


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value

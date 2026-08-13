from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime


class RecordingBackend:
    def __init__(self) -> None:
        self.seeds: list[int] = []

    def environment_identity(self) -> dict[str, str]:
        return {"python": "3.11-test", "torch": "fake", "device": "cpu"}

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
        del temperature, top_k, top_p
        self.seeds.append(seed)
        last_close = float(window[-1]["close"])
        terminal_returns = (-0.02, -0.01, 0.0, 0.01, 0.02)
        assert sample_count == len(terminal_returns)
        return tuple(
            tuple(
                last_close * (1 + terminal_return * step / len(forecast_times))
                for step in range(1, len(forecast_times) + 1)
            )
            for terminal_return in terminal_returns
        )


class NonFiniteBackend(RecordingBackend):
    def predict_paths(self, **kwargs):
        paths = [list(item) for item in super().predict_paths(**kwargs)]
        paths[0][-1] = float("nan")
        return paths

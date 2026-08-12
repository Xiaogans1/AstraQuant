"""Small DatasetH-compatible adapter over the frozen AstraQuant row set."""

from __future__ import annotations

from collections.abc import Sequence
from typing import overload

import pandas as pd


class AstraFoldDataset:
    """Expose one frozen walk-forward fold through Qlib's DatasetH protocol."""

    def __init__(
        self,
        frame: pd.DataFrame,
        *,
        feature_columns: Sequence[str],
        target_column: str,
        train_indices: Sequence[int],
        valid_indices: Sequence[int] | None = None,
        test_indices: Sequence[int],
    ) -> None:
        features = frame.loc[:, list(feature_columns)].copy()
        features.columns = pd.MultiIndex.from_product([["feature"], feature_columns])
        if target_column not in {"label", "future_return"}:
            raise ValueError(f"unsupported target_column: {target_column}")
        labels = frame.loc[:, [target_column]].copy()
        labels.columns = pd.MultiIndex.from_tuples([("label", "LABEL0")])
        self._frame = pd.concat([features, labels], axis=1)
        self._indices = {
            "train": tuple(train_indices),
            "test": tuple(test_indices),
        }
        if valid_indices is not None:
            self._indices["valid"] = tuple(valid_indices)
        self.segments = {segment: "frozen" for segment in self._indices}

    @overload
    def prepare(
        self,
        segment: str,
        col_set: str | Sequence[str] = "feature",
        data_key: str | None = None,
    ) -> pd.DataFrame: ...

    @overload
    def prepare(
        self,
        segment: Sequence[str],
        col_set: str | Sequence[str] = "feature",
        data_key: str | None = None,
    ) -> tuple[pd.DataFrame, ...]: ...

    def prepare(
        self,
        segment: str | Sequence[str],
        col_set: str | Sequence[str] = "feature",
        data_key: str | None = None,
    ) -> pd.DataFrame | tuple[pd.DataFrame, ...]:
        del data_key
        if not isinstance(segment, str):
            return tuple(self.prepare(item, col_set=col_set) for item in segment)
        if segment not in self._indices:
            raise KeyError(f"unknown segment: {segment}")
        columns = [col_set] if isinstance(col_set, str) else list(col_set)
        if not columns or not set(columns).issubset({"feature", "label"}):
            raise KeyError(f"unsupported col_set: {columns}")
        if isinstance(col_set, str):
            return self._frame.loc[list(self._indices[segment]), col_set].copy()
        return self._frame.loc[list(self._indices[segment]), columns].copy()

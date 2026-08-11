"""Small DatasetH-compatible adapter over the frozen AstraQuant row set."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


class AstraFoldDataset:
    """Expose one frozen walk-forward fold through Qlib's DatasetH protocol."""

    def __init__(
        self,
        frame: pd.DataFrame,
        *,
        feature_columns: Sequence[str],
        train_indices: Sequence[int],
        test_indices: Sequence[int],
    ) -> None:
        features = frame.loc[:, list(feature_columns)].copy()
        features.columns = pd.MultiIndex.from_product([["feature"], feature_columns])
        labels = frame.loc[:, ["label"]].copy()
        labels.columns = pd.MultiIndex.from_tuples([("label", "LABEL0")])
        self._frame = pd.concat([features, labels], axis=1)
        self._indices = {
            "train": tuple(train_indices),
            "test": tuple(test_indices),
        }
        self.segments = {"train": "frozen", "test": "frozen"}

    def prepare(
        self,
        segment: str,
        col_set: str | Sequence[str] = "feature",
        data_key: str | None = None,
    ) -> pd.DataFrame:
        del data_key
        if segment not in self._indices:
            raise KeyError(f"unknown segment: {segment}")
        columns = [col_set] if isinstance(col_set, str) else list(col_set)
        if not columns or not set(columns).issubset({"feature", "label"}):
            raise KeyError(f"unsupported col_set: {columns}")
        return self._frame.loc[list(self._indices[segment]), columns].copy()

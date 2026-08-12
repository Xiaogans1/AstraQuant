"""Pinned and deterministic Qlib DoubleEnsemble construction."""

from __future__ import annotations

from typing import Any

import numpy as np


def create_double_ensemble_model(config: dict[str, Any], *, seed: int) -> Any:
    from qlib.contrib.model.double_ensemble import DEnsembleModel

    class DeterministicDEnsembleModel(DEnsembleModel):
        def fit(self, dataset: Any) -> Any:
            state = np.random.get_state()
            try:
                np.random.seed(seed)
                return super().fit(dataset)
            finally:
                np.random.set_state(state)

        def feature_selection(self, df_train: Any, loss_values: Any) -> Any:
            selected = super().feature_selection(df_train, loss_values)
            selected_names = set(selected)
            columns = df_train["feature"].columns
            return columns[columns.isin(selected_names)]

    expected_keys = {"num_models", "epochs", "enable_sr", "enable_fs", "decay"}
    if set(config) != expected_keys:
        raise ValueError("DoubleEnsemble model_config schema mismatch")
    num_models = config["num_models"]
    epochs = config["epochs"]
    enable_sr = config["enable_sr"]
    enable_fs = config["enable_fs"]
    decay = config["decay"]
    if isinstance(num_models, bool) or not isinstance(num_models, int) or not 1 <= num_models <= 12:
        raise ValueError("DoubleEnsemble num_models must be between 1 and 12")
    if isinstance(epochs, bool) or not isinstance(epochs, int) or not 1 <= epochs <= 1000:
        raise ValueError("DoubleEnsemble epochs must be between 1 and 1000")
    if not isinstance(enable_sr, bool) or not isinstance(enable_fs, bool):
        raise ValueError("DoubleEnsemble feature flags must be boolean")
    if isinstance(decay, bool) or not isinstance(decay, (int, float)) or not 0 < decay <= 1:
        raise ValueError("DoubleEnsemble decay must be between zero and one")
    return DeterministicDEnsembleModel(
        base_model="gbm",
        loss="mse",
        num_models=num_models,
        epochs=epochs,
        enable_sr=enable_sr,
        enable_fs=enable_fs,
        decay=float(decay),
        learning_rate=0.05,
        num_leaves=15,
        max_depth=4,
        min_data_in_leaf=2,
        min_data_in_bin=1,
        feature_fraction=1.0,
        bagging_fraction=1.0,
        bagging_freq=0,
        seed=seed,
        feature_fraction_seed=seed,
        bagging_seed=seed,
        data_random_seed=seed,
        deterministic=True,
        force_col_wise=True,
        num_threads=1,
        verbosity=-1,
    )

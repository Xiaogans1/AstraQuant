"""Official Qlib Alpha158 expressions over frozen AstraQuant raw bars."""

from __future__ import annotations

import json
import math
import warnings
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from . import (
    QLIB_UPSTREAM_COMMIT,
    _canonical_bytes,
    _digest,
    _ensure_qlib_initialized,
    _indices,
    _require_int,
    _require_list,
    _require_str,
    _require_string_list,
)
from .dataset import AstraFoldDataset

ALPHA158_CONFIG_DIGEST = "sha256:e645c1f75957e9a564fc9b0b8da232b9aa6fd887f673c92addc8a0276f6f5644"
REQUEST_SCHEMA = "astraquant.qlib-alpha158-request/v1"
RESPONSE_SCHEMA = "astraquant.qlib-alpha158-response/v1"
_BAR_COLUMNS = ["bar_id", "timestamp", "open", "high", "low", "close", "volume", "vwap"]
_PRICE_COLUMNS = ["open", "high", "low", "close", "volume", "vwap"]


class _InMemoryFeatureProvider:
    def __init__(self, bars: pd.DataFrame) -> None:
        self._bars = bars

    def feature(
        self,
        instrument: str,
        field: str,
        start_index: pd.Timestamp,
        end_index: pd.Timestamp,
        freq: str,
    ) -> pd.Series:
        del instrument, freq
        name = str(field)[1:].lower()
        if name not in _PRICE_COLUMNS:
            raise KeyError(f"unsupported raw Alpha158 field: {name}")
        return self._bars.loc[start_index:end_index, name].copy()


def compute_alpha158_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute the pinned commit's official 158 expressions without Qlib sample data."""
    _ensure_qlib_initialized()
    exact_bars = _validate_bar_frame(bars)

    from qlib.contrib.data.loader import Alpha158DL
    from qlib.data.cache import H
    from qlib.data.data import ExpressionD, FeatureD, LocalExpressionProvider

    fields, names = Alpha158DL.get_feature_config()
    config_digest = _digest(_canonical_bytes({"fields": fields, "names": names}))
    if len(fields) != 158 or len(names) != 158 or config_digest != ALPHA158_CONFIG_DIGEST:
        raise ValueError("installed Qlib Alpha158 config does not match pinned contract")
    FeatureD.register(_InMemoryFeatureProvider(exact_bars))
    ExpressionD.register(LocalExpressionProvider(time2idx=False))
    H.clear()
    start = exact_bars.index[0]
    end = exact_bars.index[-1]
    values = {
        name: ExpressionD.expression("ASTRA", field, start, end, "1min")
        for field, name in zip(fields, names, strict=True)
    }
    result = pd.DataFrame(values, index=exact_bars.index)
    if result.shape != (len(exact_bars), 158) or list(result.columns) != names:
        raise ValueError("Qlib Alpha158 feature output schema mismatch")
    return result


def run_alpha158_request(request_path: Path, output_path: Path) -> dict[str, Any]:
    request = _read_request(request_path)
    rows = _read_rows(request_path.parent, request)
    bars = _read_bars(request_path.parent, request)
    mapping = _mapping(request, row_count=len(rows), bar_count=len(bars))
    alpha = compute_alpha158_features(bars).iloc[mapping].reset_index(drop=True)
    alpha["label"] = rows["label"].to_numpy()
    feature_columns = [str(name) for name in alpha.columns if name != "label"]

    from qlib.contrib.model.gbdt import LGBModel
    from qlib.workflow import R

    predictions: list[dict[str, object]] = []
    seed = _require_int(request, "seed")
    for fold in _require_list(request, "folds"):
        if not isinstance(fold, dict):
            raise ValueError("fold schema mismatch")
        fold_id = _require_str(fold, "fold_id")
        train_indices = _indices(fold, "train_indices", len(rows))
        test_indices = _indices(fold, "test_indices", len(rows))
        if set(train_indices) & set(test_indices) or max(train_indices) >= min(test_indices):
            raise ValueError(f"invalid fold: {fold_id}")
        dataset = AstraFoldDataset(
            alpha,
            feature_columns=feature_columns,
            target_column="label",
            train_indices=train_indices,
            test_indices=test_indices,
        )
        model = LGBModel(
            loss="binary",
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
            num_boost_round=40,
            early_stopping_rounds=0,
        )
        with R.start(experiment_name="AstraQuantAlpha158Runner"), warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message="Only training set found, disabling early stopping."
            )
            model.fit(dataset, verbose_eval=0)
        values = model.predict(dataset, segment="test")
        if list(values.index) != test_indices:
            raise ValueError(f"Alpha158 prediction row order mismatch: {fold_id}")
        predictions.extend(
            {
                "fold_id": fold_id,
                "row_id": row_id,
                "probability": float(probability),
            }
            for row_id, probability in values.items()
        )

    response: dict[str, Any] = {
        "schema_version": RESPONSE_SCHEMA,
        "request_content_digest": _require_str(request, "content_digest"),
        "upstream_commit": QLIB_UPSTREAM_COMMIT,
        "alpha158_config_digest": ALPHA158_CONFIG_DIGEST,
        "alpha158_feature_count": 158,
        "feature_set": "QLIB_ALPHA158",
        "model": "qlib.contrib.model.gbdt.LGBModel",
        "predictions": predictions,
    }
    encoded = _canonical_bytes(response) + b"\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(output_path)
    return response


def _read_request(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Alpha158 request JSON") from exc
    if not isinstance(value, dict) or value.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("Alpha158 request schema mismatch")
    if value.get("upstream_commit") != QLIB_UPSTREAM_COMMIT:
        raise ValueError("Alpha158 upstream commit mismatch")
    if value.get("alpha158_config_digest") != ALPHA158_CONFIG_DIGEST:
        raise ValueError("Alpha158 config digest mismatch")
    supplied = _require_str(value, "content_digest")
    body = {key: item for key, item in value.items() if key != "content_digest"}
    if supplied != _digest(_canonical_bytes(body)):
        raise ValueError("Alpha158 request content digest mismatch")
    return value


def _read_rows(root: Path, request: dict[str, Any]) -> pd.DataFrame:
    source_features = _require_string_list(request, "source_feature_columns")
    path = _verified_file(root, request, "rows_file", "rows.parquet", "rows")
    frame = pq.read_table(path).to_pandas()
    expected = ["row_id", *source_features, "label", "future_return"]
    if list(frame.columns) != expected or len(frame) != _require_int(request, "row_count"):
        raise ValueError("Alpha158 rows schema mismatch")
    if frame["row_id"].tolist() != list(range(len(frame))):
        raise ValueError("Alpha158 row identity mismatch")
    return frame


def _read_bars(root: Path, request: dict[str, Any]) -> pd.DataFrame:
    path = _verified_file(root, request, "bars_file", "bars.parquet", "bars")
    frame = pq.read_table(path).to_pandas()
    if list(frame.columns) != _BAR_COLUMNS or len(frame) != _require_int(request, "bar_count"):
        raise ValueError("Alpha158 bars schema mismatch")
    if frame["bar_id"].tolist() != list(range(len(frame))):
        raise ValueError("Alpha158 bar identity mismatch")
    return _validate_bar_frame(frame.drop(columns="bar_id").set_index("timestamp"))


def _validate_bar_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if list(frame.columns) != _PRICE_COLUMNS or frame.empty:
        raise ValueError("Alpha158 raw bar columns mismatch")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
        raise ValueError("Alpha158 raw bar timestamps must be unique datetimes")
    exact = frame.sort_index()
    if not exact.index.equals(frame.index):
        raise ValueError("Alpha158 raw bars must be time ordered")
    if not bool(
        exact.loc[:, _PRICE_COLUMNS].map(lambda value: math.isfinite(float(value))).to_numpy().all()
    ):
        raise ValueError("Alpha158 raw bars must be finite")
    if (exact[["open", "high", "low", "close", "vwap"]] <= 0).to_numpy().any():
        raise ValueError("Alpha158 prices must be positive")
    if (exact["volume"] < 0).any():
        raise ValueError("Alpha158 volume must not be negative")
    return exact


def _mapping(request: dict[str, Any], *, row_count: int, bar_count: int) -> list[int]:
    value = request.get("row_bar_indices")
    if (
        not isinstance(value, list)
        or len(value) != row_count
        or any(isinstance(index, bool) or not isinstance(index, int) for index in value)
        or any(left >= right for left, right in pairwise(value))
        or value[0] < 0
        or value[-1] >= bar_count
    ):
        raise ValueError("Alpha158 row-bar mapping mismatch")
    return value


def _verified_file(
    root: Path,
    request: dict[str, Any],
    key: str,
    expected_name: str,
    label: str,
) -> Path:
    value = request.get(key)
    if not isinstance(value, dict) or value.get("path") != expected_name:
        raise ValueError(f"{label} file schema mismatch")
    path = root / expected_name
    if not path.is_file() or _digest(path.read_bytes()) != value.get("digest"):
        raise ValueError(f"{label} digest mismatch")
    return path

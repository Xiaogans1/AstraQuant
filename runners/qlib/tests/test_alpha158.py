from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from astraquant_qlib_runner.__main__ import run_cli_request
from astraquant_qlib_runner.alpha158 import (
    ALPHA158_CONFIG_DIGEST,
    compute_alpha158_features,
    run_alpha158_request,
)

FEATURES = (
    "return_1",
    "return_3",
    "return_5",
    "return_10",
    "volatility_5",
    "vwap_deviation",
    "volume_ratio",
    "day_high_position",
    "ma5_gap",
    "ma20_gap",
)
COMMIT = "79633dd9506ea689e5400dea0197717b5b3d74b7"


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _bars(count: int = 100) -> pd.DataFrame:
    index = pd.date_range("2026-08-03 01:30", periods=count, freq="min", tz="UTC")
    close = pd.Series([10 + index / 100 for index in range(count)], index=index)
    return pd.DataFrame(
        {
            "open": close - 0.02,
            "high": close + 0.08,
            "low": close - 0.12,
            "close": close,
            "volume": [float(100 + index) for index in range(count)],
            "vwap": close - 0.01,
        },
        index=index,
    )


def test_official_alpha158_expression_engine_produces_exact_feature_set() -> None:
    bars = _bars(70)

    features = compute_alpha158_features(bars)

    assert features.shape == (70, 158)
    assert list(features.columns[:15]) == [
        "KMID",
        "KLEN",
        "KMID2",
        "KUP",
        "KUP2",
        "KLOW",
        "KLOW2",
        "KSFT",
        "KSFT2",
        "OPEN0",
        "HIGH0",
        "LOW0",
        "VWAP0",
        "ROC5",
        "ROC10",
    ]
    expected_kmid = (bars.iloc[0]["close"] - bars.iloc[0]["open"]) / bars.iloc[0]["open"]
    assert features.iloc[0]["KMID"] == pytest.approx(expected_kmid)
    assert features.iloc[0]["OPEN0"] == pytest.approx(bars.iloc[0]["open"] / bars.iloc[0]["close"])


def test_alpha158_rejects_non_finite_raw_bars() -> None:
    bars = _bars(70)
    bars.iloc[10, bars.columns.get_loc("volume")] = float("inf")

    with pytest.raises(ValueError, match="finite"):
        compute_alpha158_features(bars)


def _write_request(root: Path) -> Path:
    root.mkdir()
    bars = _bars()
    bars_table = pa.Table.from_pandas(
        bars.reset_index(names="timestamp").reset_index(names="bar_id"),
        preserve_index=False,
    )
    bars_path = root / "bars.parquet"
    pq.write_table(bars_table, bars_path)
    rows = [
        {
            "row_id": row_id,
            **{name: float(row_id) for name in FEATURES},
            "label": row_id % 2,
            "future_return": 0.01 if row_id % 2 else -0.01,
        }
        for row_id in range(60)
    ]
    rows_path = root / "rows.parquet"
    pq.write_table(pa.Table.from_pylist(rows), rows_path)
    body = {
        "schema_version": "astraquant.qlib-alpha158-request/v1",
        "upstream_commit": COMMIT,
        "alpha158_config_digest": ALPHA158_CONFIG_DIGEST,
        "alpha158_feature_count": 158,
        "feature_set": "QLIB_ALPHA158",
        "provider_id": "eastmoney",
        "dataset_id": "s1-fixture",
        "source_snapshot_id": "1" * 64,
        "source_feature_columns": list(FEATURES),
        "row_count": 60,
        "bar_count": 100,
        "rows_file": {"path": "rows.parquet", "digest": _digest(rows_path.read_bytes())},
        "bars_file": {"path": "bars.parquet", "digest": _digest(bars_path.read_bytes())},
        "row_bar_indices": list(range(30, 90)),
        "folds": [
            {
                "fold_id": "fold-1",
                "train_indices": list(range(40)),
                "test_indices": list(range(40, 50)),
            },
            {
                "fold_id": "fold-2",
                "train_indices": list(range(50)),
                "test_indices": list(range(50, 60)),
            },
        ],
        "fee_rate": "0.001",
        "prediction_threshold": 0.5,
        "seed": 7,
    }
    request_path = root / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "content_digest": _digest(
                    json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
                ),
                **body,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return request_path


def test_alpha158_runner_is_repeatable_and_keeps_all_test_rows(tmp_path: Path) -> None:
    request = _write_request(tmp_path / "input")

    first = run_alpha158_request(request, tmp_path / "first.json")
    second = run_alpha158_request(request, tmp_path / "second.json")

    assert first == second
    assert first["schema_version"] == "astraquant.qlib-alpha158-response/v1"
    assert first["alpha158_config_digest"] == ALPHA158_CONFIG_DIGEST
    assert first["alpha158_feature_count"] == 158
    assert [(item["fold_id"], item["row_id"]) for item in first["predictions"]] == [
        *(("fold-1", row_id) for row_id in range(40, 50)),
        *(("fold-2", row_id) for row_id in range(50, 60)),
    ]
    assert (tmp_path / "first.json").read_bytes() == (tmp_path / "second.json").read_bytes()


def test_alpha158_runner_rejects_tampered_bars(tmp_path: Path) -> None:
    request = _write_request(tmp_path / "input")
    with (request.parent / "bars.parquet").open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(ValueError, match="bars digest"):
        run_alpha158_request(request, tmp_path / "output.json")


def test_main_cli_dispatches_alpha158_contract(tmp_path: Path) -> None:
    request = _write_request(tmp_path / "input")

    result = run_cli_request(request, tmp_path / "output.json")

    assert result["schema_version"] == "astraquant.qlib-alpha158-response/v1"

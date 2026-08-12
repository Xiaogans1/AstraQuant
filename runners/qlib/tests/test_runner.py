from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from astraquant_qlib_runner import QLIB_UPSTREAM_COMMIT, run_request
from astraquant_qlib_runner.dataset import AstraFoldDataset
from astraquant_qlib_runner.model_adapters import create_double_ensemble_model

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


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _write_request(root: Path) -> Path:
    root.mkdir()
    rows = []
    for row_id in range(36):
        signal = -1.0 if row_id % 2 == 0 else 1.0
        rows.append(
            {
                "row_id": row_id,
                **{
                    feature: signal + feature_index * 0.001 + row_id * 0.0001
                    for feature_index, feature in enumerate(FEATURES)
                },
                "label": row_id % 2,
                "future_return": signal * 0.01,
            }
        )
    rows_path = root / "rows.parquet"
    pq.write_table(pa.Table.from_pylist(rows), rows_path)
    body = {
        "schema_version": "astraquant.qlib-request/v1",
        "upstream_commit": QLIB_UPSTREAM_COMMIT,
        "provider_id": "eastmoney",
        "dataset_id": "s1-fixture",
        "source_snapshot_id": "1" * 64,
        "feature_columns": list(FEATURES),
        "row_count": len(rows),
        "rows_file": {
            "path": "rows.parquet",
            "digest": _digest_bytes(rows_path.read_bytes()),
        },
        "folds": [
            {
                "fold_id": "fold-1",
                "train_indices": list(range(24)),
                "test_indices": list(range(24, 30)),
            },
            {
                "fold_id": "fold-2",
                "train_indices": list(range(30)),
                "test_indices": list(range(30, 36)),
            },
        ],
        "fee_rate": "0.001",
        "prediction_threshold": 0.55,
        "seed": 7,
        "training_task_digest": "sha256:" + "2" * 64,
        "model_kind": "LIGHTGBM_BINARY",
        "target_column": "label",
        "score_semantics": "PROBABILITY",
    }
    content_digest = _digest_bytes(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    request_path = root / "request.json"
    request_path.write_text(
        json.dumps(
            {"content_digest": content_digest, **body},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return request_path


def test_runner_is_deterministic_and_covers_every_test_row(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "input")

    first = run_request(request_path, tmp_path / "first.json")
    second = run_request(request_path, tmp_path / "second.json")

    assert first == second
    assert first["schema_version"] == "astraquant.qlib-response/v1"
    assert first["upstream_commit"] == QLIB_UPSTREAM_COMMIT
    assert first["training_task_digest"] == "sha256:" + "2" * 64
    assert first["model_kind"] == "LIGHTGBM_BINARY"
    assert first["score_semantics"] == "PROBABILITY"
    assert [(item["fold_id"], item["row_id"]) for item in first["predictions"]] == [
        *(("fold-1", row_id) for row_id in range(24, 30)),
        *(("fold-2", row_id) for row_id in range(30, 36)),
    ]
    assert all(0.0 <= item["probability"] <= 1.0 for item in first["predictions"])
    assert (tmp_path / "first.json").read_bytes() == (tmp_path / "second.json").read_bytes()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "astraquant.qlib-request/v0", "schema"),
        ("upstream_commit", "0" * 40, "commit"),
        ("content_digest", "sha256:" + "0" * 64, "content digest"),
    ],
)
def test_runner_rejects_contract_mismatch(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    request_path = _write_request(tmp_path / "input")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request[field] = value
    request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        run_request(request_path, tmp_path / "output.json")


def test_runner_rejects_tampered_rows(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "input")
    with (request_path.parent / "rows.parquet").open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(ValueError, match="rows digest"):
        run_request(request_path, tmp_path / "output.json")


def test_fold_dataset_uses_the_declared_regression_target() -> None:
    source = {
        "feature": [1.0, 2.0],
        "label": [0, 1],
        "future_return": [-0.02, 0.03],
    }
    dataset = AstraFoldDataset(
        pd.DataFrame(source),
        feature_columns=("feature",),
        target_column="future_return",
        train_indices=(0,),
        valid_indices=(1,),
        test_indices=(1,),
    )

    prepared = dataset.prepare("valid", col_set="label")
    assert prepared.iloc[0, 0] == pytest.approx(0.03)


def test_runner_rejects_incompatible_model_target_and_score_contract(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "input")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request.update(
        {
            "model_kind": "DOUBLE_ENSEMBLE",
            "target_column": "label",
            "score_semantics": "EXPECTED_RETURN",
        }
    )
    body = {key: value for key, value in request.items() if key != "content_digest"}
    request["content_digest"] = _digest_bytes(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    )
    request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(ValueError, match="model/target/score"):
        run_request(request_path, tmp_path / "output.json")


def test_double_ensemble_returns_deterministic_expected_return_scores(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "input")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    for fold in request["folds"]:
        train = fold["train_indices"]
        split = len(train) - math.ceil(len(train) * 0.2)
        fold["fit_indices"] = train[:split]
        fold["validation_indices"] = train[split:]
    request.update(
        {
            "model_kind": "DOUBLE_ENSEMBLE",
            "target_column": "future_return",
            "score_semantics": "EXPECTED_RETURN",
            "model_config": {
                "num_models": 2,
                "epochs": 10,
                "enable_sr": True,
                "enable_fs": True,
                "decay": 0.5,
            },
            "validation_policy": {
                "kind": "TRAIN_TAIL_FRACTION",
                "fraction": "0.2",
            },
        }
    )
    body = {key: value for key, value in request.items() if key != "content_digest"}
    request["content_digest"] = _digest_bytes(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    )
    request_path.write_text(json.dumps(request), encoding="utf-8")

    first = run_request(request_path, tmp_path / "first-double.json")
    np.random.seed(9917)
    np.random.random(1000)
    second = run_request(request_path, tmp_path / "second-double.json")

    assert first == second
    assert first["model_kind"] == "DOUBLE_ENSEMBLE"
    assert first["score_semantics"] == "EXPECTED_RETURN"
    assert all("score" in item and "probability" not in item for item in first["predictions"])


def test_double_ensemble_is_deterministic_across_fresh_processes(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "input")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    for fold in request["folds"]:
        train = fold["train_indices"]
        split = len(train) - math.ceil(len(train) * 0.2)
        fold["fit_indices"] = train[:split]
        fold["validation_indices"] = train[split:]
    request.update(
        {
            "model_kind": "DOUBLE_ENSEMBLE",
            "target_column": "future_return",
            "score_semantics": "EXPECTED_RETURN",
            "model_config": {
                "num_models": 2,
                "epochs": 10,
                "enable_sr": True,
                "enable_fs": True,
                "decay": 0.5,
            },
            "validation_policy": {"kind": "TRAIN_TAIL_FRACTION", "fraction": "0.2"},
        }
    )
    body = {key: value for key, value in request.items() if key != "content_digest"}
    request["content_digest"] = _digest_bytes(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    )
    request_path.write_text(json.dumps(request), encoding="utf-8")
    outputs = (tmp_path / "first-process.json", tmp_path / "second-process.json")
    for output in outputs:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "astraquant_qlib_runner",
                "--request",
                str(request_path),
                "--output",
                str(output),
            ],
            check=True,
        )

    assert outputs[0].read_bytes() == outputs[1].read_bytes()


def test_double_ensemble_adapter_resets_qlib_global_numpy_randomness(monkeypatch) -> None:
    from qlib.contrib.model.double_ensemble import DEnsembleModel

    observed: list[float] = []
    monkeypatch.setattr(
        DEnsembleModel,
        "fit",
        lambda self, dataset: observed.append(float(np.random.random())),
    )
    config = {
        "num_models": 2,
        "epochs": 10,
        "enable_sr": True,
        "enable_fs": True,
        "decay": 0.5,
    }
    first = create_double_ensemble_model(config, seed=7)
    second = create_double_ensemble_model(config, seed=7)

    np.random.seed(11)
    first.fit(None)
    np.random.seed(9917)
    np.random.random(1000)
    second.fit(None)

    assert observed[0] == observed[1]


def test_double_ensemble_adapter_preserves_canonical_feature_order(monkeypatch) -> None:
    from qlib.contrib.model.double_ensemble import DEnsembleModel

    monkeypatch.setattr(
        DEnsembleModel,
        "feature_selection",
        lambda self, df_train, loss_values: pd.Index(["feature_b", "feature_a"]),
    )
    model = create_double_ensemble_model(
        {
            "num_models": 2,
            "epochs": 2,
            "enable_sr": True,
            "enable_fs": True,
            "decay": 0.9,
        },
        seed=7,
    )
    frame = pd.DataFrame(
        {
            ("feature", "feature_a"): [1.0],
            ("feature", "feature_b"): [2.0],
            ("label", "future_return"): [0.1],
        }
    )

    selected = model.feature_selection(frame, pd.Series([0.0]))

    assert list(selected) == ["feature_a", "feature_b"]

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from astraquant_qlib_runner import QLIB_UPSTREAM_COMMIT, run_request

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

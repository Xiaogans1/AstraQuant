"""Deterministic S1 row/fold export consumed by the isolated Qlib runner."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_domain.run_manifest import canonical_json_bytes

QLIB_UPSTREAM_COMMIT = "79633dd9506ea689e5400dea0197717b5b3d74b7"
QLIB_EXPORT_SCHEMA = "astraquant.qlib-request/v1"
QLIB_FEATURE_COLUMNS = (
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
_DATASET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_DIGEST_PATTERN = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")


class FoldLike(Protocol):
    @property
    def fold_id(self) -> str: ...

    @property
    def train_indices(self) -> tuple[int, ...]: ...

    @property
    def test_indices(self) -> tuple[int, ...]: ...


@dataclass(frozen=True, slots=True)
class QlibExport:
    content_digest: str
    request_path: Path
    rows_path: Path


def export_qlib_request(
    *,
    output_root: Path,
    dataset_id: str,
    source_snapshot_id: str,
    provider_id: str,
    rows: Sequence[dict[str, float | int]],
    folds: Sequence[FoldLike],
    fee_rate: Decimal,
    prediction_threshold: float,
    seed: int,
) -> QlibExport:
    if provider_id != "eastmoney":
        raise ValueError("Qlib research input must come from Eastmoney")
    if not _DATASET_PATTERN.fullmatch(dataset_id):
        raise ValueError("invalid dataset_id")
    _validate_snapshot(source_snapshot_id)
    exact_rows = tuple(rows)
    _validate_rows(exact_rows)
    exact_folds = tuple(folds)
    fold_values = _validate_folds(exact_folds, row_count=len(exact_rows))
    if fee_rate < 0:
        raise ValueError("fee_rate must not be negative")
    if not 0 < prediction_threshold < 1:
        raise ValueError("prediction_threshold must be between zero and one")

    root = output_root.resolve()
    if root.exists():
        raise ValueError("Qlib export output_root must not already exist")
    root.mkdir(parents=True)
    rows_path = root / "rows.parquet"
    pq.write_table(_rows_table(exact_rows), rows_path, compression="zstd", version="2.6")
    rows_digest = _file_digest(rows_path)
    body: dict[str, object] = {
        "schema_version": QLIB_EXPORT_SCHEMA,
        "upstream_commit": QLIB_UPSTREAM_COMMIT,
        "provider_id": provider_id,
        "dataset_id": dataset_id,
        "source_snapshot_id": source_snapshot_id,
        "feature_columns": list(QLIB_FEATURE_COLUMNS),
        "row_count": len(exact_rows),
        "rows_file": {"path": "rows.parquet", "digest": rows_digest},
        "folds": fold_values,
        "fee_rate": str(fee_rate),
        "prediction_threshold": prediction_threshold,
        "seed": seed,
    }
    content_digest = _object_digest(body)
    request_path = root / "request.json"
    request_path.write_text(
        json.dumps(
            {"content_digest": content_digest, **body},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return QlibExport(
        content_digest=content_digest,
        request_path=request_path,
        rows_path=rows_path,
    )


def _validate_snapshot(value: str) -> None:
    match = _DIGEST_PATTERN.fullmatch(value)
    if match is None or set(match.group(1)) == {"0"}:
        raise ValueError("source snapshot must be a non-sentinel SHA-256 identity")


def _validate_rows(rows: tuple[dict[str, float | int], ...]) -> None:
    if not rows:
        raise ValueError("Qlib export rows must not be empty")
    required = {*QLIB_FEATURE_COLUMNS, "label", "future_return"}
    for row in rows:
        if set(row) != required:
            raise ValueError("Qlib export row schema does not match S1 features")
        values = [float(row[name]) for name in (*QLIB_FEATURE_COLUMNS, "future_return")]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Qlib export row values must be finite")
        if isinstance(row["label"], bool) or int(row["label"]) not in (0, 1):
            raise ValueError("Qlib export labels must be binary")


def _validate_folds(folds: tuple[FoldLike, ...], *, row_count: int) -> list[dict[str, object]]:
    if not folds or len({fold.fold_id for fold in folds}) != len(folds):
        raise ValueError("Qlib export folds must be non-empty and uniquely named")
    values: list[dict[str, object]] = []
    for fold in folds:
        train = tuple(fold.train_indices)
        test = tuple(fold.test_indices)
        indices = (*train, *test)
        if (
            not fold.fold_id
            or not train
            or not test
            or len(set(train)) != len(train)
            or len(set(test)) != len(test)
            or set(train) & set(test)
            or min(indices) < 0
            or max(indices) >= row_count
            or max(train) >= min(test)
        ):
            raise ValueError(f"invalid Qlib fold: {fold.fold_id}")
        values.append(
            {
                "fold_id": fold.fold_id,
                "train_indices": list(train),
                "test_indices": list(test),
            }
        )
    return values


def _rows_table(rows: tuple[dict[str, float | int], ...]) -> pa.Table:
    schema = pa.schema(
        [
            pa.field("row_id", pa.int64(), nullable=False),
            *(pa.field(name, pa.float64(), nullable=False) for name in QLIB_FEATURE_COLUMNS),
            pa.field("label", pa.int8(), nullable=False),
            pa.field("future_return", pa.float64(), nullable=False),
        ],
        metadata={b"schema_version": QLIB_EXPORT_SCHEMA.encode("ascii")},
    )
    return pa.Table.from_pylist(
        [
            {
                "row_id": row_id,
                **{name: float(row[name]) for name in QLIB_FEATURE_COLUMNS},
                "label": int(row["label"]),
                "future_return": float(row["future_return"]),
            }
            for row_id, row in enumerate(rows)
        ],
        schema=schema,
    )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _object_digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

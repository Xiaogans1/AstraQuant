from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from astraquant_data.exports.qlib import QLIB_UPSTREAM_COMMIT, export_qlib_request
from astraquant_domain import ScoreSemantics, TrainingTaskKind, TrainingTaskSpec
from astraquant_quant.baseline_matrix import WalkForwardFold, expanding_walk_forward
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS


def _snapshot(character: str = "a") -> str:
    return f"sha256:{character * 64}"


def _training_task(
    *,
    score_semantics: ScoreSemantics = ScoreSemantics.PROBABILITY,
) -> TrainingTaskSpec:
    return TrainingTaskSpec(
        task_id="daily-base-target-v1",
        kind=TrainingTaskKind.BASE_TARGET,
        label_name="next_open_up_1d",
        horizon_bars=1,
        score_semantics=score_semantics,
        universe_id="shared-panel-v1",
        execution_policy_id="a-share-next-open-v1",
        evaluation_metrics=("auc", "net_return"),
    )


def _rows(count: int = 80) -> list[dict[str, float | int]]:
    rows = []
    for index in range(count):
        label = index % 2
        row: dict[str, float | int] = {
            name: float(index + position) / 100
            for position, name in enumerate(MODEL_FEATURE_COLUMNS)
        }
        row.update(
            {
                "label": label,
                "future_return": 0.01 if label else -0.01,
            }
        )
        rows.append(row)
    return rows


def _folds(rows: list[dict[str, float | int]]) -> tuple[WalkForwardFold, ...]:
    return expanding_walk_forward(
        rows,
        minimum_train_size=40,
        test_size=10,
        fold_count=3,
    )


def _export(root: Path, **changes: object):  # type: ignore[no-untyped-def]
    rows = changes.pop("rows", _rows())
    assert isinstance(rows, list)
    values: dict[str, object] = {
        "output_root": root,
        "dataset_id": "cn-equity-159516-szse-1m-none",
        "source_snapshot_id": _snapshot(),
        "provider_id": "eastmoney",
        "rows": rows,
        "folds": _folds(rows),
        "fee_rate": Decimal("0.00025"),
        "prediction_threshold": 0.5,
        "seed": 7,
        "training_task": _training_task(),
        "model_kind": "LIGHTGBM_BINARY",
        "target_column": "label",
    }
    values.update(changes)
    return export_qlib_request(**values)  # type: ignore[arg-type]


def test_qlib_export_is_repeatable_and_preserves_the_shared_rows_and_folds(
    tmp_path: Path,
) -> None:
    first = _export(tmp_path / "first")
    second = _export(tmp_path / "second")

    assert first.content_digest == second.content_digest
    assert first.rows_path.read_bytes() == second.rows_path.read_bytes()
    request = json.loads(first.request_path.read_text(encoding="utf-8"))
    assert request["content_digest"] == first.content_digest
    assert request["upstream_commit"] == QLIB_UPSTREAM_COMMIT
    assert request["provider_id"] == "eastmoney"
    assert request["training_task_digest"] == _training_task().task_digest
    assert request["model_kind"] == "LIGHTGBM_BINARY"
    assert request["target_column"] == "label"
    assert request["score_semantics"] == "PROBABILITY"
    assert request["feature_columns"] == MODEL_FEATURE_COLUMNS
    assert request["folds"][0]["train_indices"] == list(range(50))
    assert request["folds"][0]["test_indices"] == list(range(50, 60))
    table = pq.read_table(first.rows_path)
    assert table.column_names == [
        "row_id",
        *MODEL_FEATURE_COLUMNS,
        "label",
        "future_return",
    ]
    assert table.column("row_id").to_pylist() == list(range(80))


def test_qlib_export_identity_changes_with_rows_folds_or_source_snapshot(tmp_path: Path) -> None:
    baseline = _export(tmp_path / "baseline")
    reversed_rows = list(reversed(_rows()))
    changed_feature_rows = _rows()
    changed_feature_rows[0] = {**changed_feature_rows[0], MODEL_FEATURE_COLUMNS[0]: 99.0}
    folds = _folds(_rows())
    changed_fold = (replace(folds[0], test_indices=tuple(range(51, 61))), *folds[1:])

    changed = [
        _export(tmp_path / "source", source_snapshot_id=_snapshot("b")),
        _export(tmp_path / "order", rows=reversed_rows),
        _export(tmp_path / "feature", rows=changed_feature_rows),
        _export(tmp_path / "fold", folds=changed_fold),
    ]

    assert all(item.content_digest != baseline.content_digest for item in changed)


def test_qlib_export_accepts_generated_rows_with_close_audit_field(tmp_path: Path) -> None:
    rows = [{**row, "close": 10.0 + index / 100} for index, row in enumerate(_rows())]

    exported = _export(tmp_path / "generated", rows=rows)

    assert pq.read_table(exported.rows_path).column_names == [
        "row_id",
        *MODEL_FEATURE_COLUMNS,
        "label",
        "future_return",
    ]


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        (
            {
                "model_kind": "DOUBLE_ENSEMBLE",
                "target_column": "label",
                "training_task": _training_task(score_semantics=ScoreSemantics.EXPECTED_RETURN),
            },
            "target_column",
        ),
        (
            {
                "model_kind": "LIGHTGBM_BINARY",
                "target_column": "label",
                "training_task": _training_task(score_semantics=ScoreSemantics.EXPECTED_RETURN),
            },
            "score semantics",
        ),
    ],
)
def test_qlib_export_rejects_incompatible_model_target_or_score_semantics(
    tmp_path: Path,
    changes: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        _export(tmp_path / "invalid-model", **changes)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"provider_id": "fixture"}, "Eastmoney"),
        ({"source_snapshot_id": _snapshot("0")}, "snapshot"),
        (
            {
                "folds": (
                    WalkForwardFold(
                        fold_id="fold-01",
                        train_indices=tuple(range(50)),
                        test_indices=(79, 80),
                    ),
                )
            },
            "fold",
        ),
    ],
)
def test_qlib_export_rejects_untrusted_or_invalid_inputs(
    tmp_path: Path,
    changes: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        _export(tmp_path / "invalid", **changes)

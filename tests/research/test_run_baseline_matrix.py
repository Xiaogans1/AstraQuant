from __future__ import annotations

import json
from pathlib import Path

import pytest

from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS
from tools.research.run_baseline_matrix import main


def _rows(count: int) -> list[dict[str, float | int]]:
    rows = []
    for index in range(count):
        label = 1 if index % 4 >= 2 else 0
        signal = 1.0 if label else -1.0
        row: dict[str, float | int] = {
            name: signal * (position + 1) / 10
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


def test_cli_writes_a_repeatable_eastmoney_baseline_report(tmp_path: Path) -> None:
    input_path = tmp_path / "features.json"
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    input_path.write_text(
        json.dumps(
            {
                "dataset_id": "cn-equity-159516-szse-1m-none",
                "source_snapshot_id": "snapshot-123",
                "provider_id": "eastmoney",
                "rows": _rows(120),
            }
        ),
        encoding="utf-8",
    )
    common = [
        str(input_path),
        "--minimum-train-size",
        "60",
        "--test-size",
        "20",
        "--fold-count",
        "3",
        "--seed",
        "7",
    ]

    assert main([*common, "--output", str(first_path)]) == 0
    assert main([*common, "--output", str(second_path)]) == 0

    first = json.loads(first_path.read_text(encoding="utf-8"))
    second = json.loads(second_path.read_text(encoding="utf-8"))
    assert first == second
    assert first["dataset_id"] == "cn-equity-159516-szse-1m-none"
    assert first["source_snapshot_id"] == "snapshot-123"
    assert first["status"] == "CHALLENGER"
    assert {model["model"] for model in first["models"]} == {
        "NO_SKILL",
        "LOGISTIC_REGRESSION",
        "LIGHTGBM",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"provider_id": "fixture", "rows": _rows(120)},
        {"provider_id": "eastmoney", "rows": []},
    ],
)
def test_cli_rejects_non_eastmoney_or_empty_training_data(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    input_path = tmp_path / "features.json"
    output_path = tmp_path / "report.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    assert main([str(input_path), "--output", str(output_path)]) == 1
    assert not output_path.exists()

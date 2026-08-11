from __future__ import annotations

import json
from pathlib import Path

from tools.research.plan_targets import main


def _write_s3_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "astraquant.executable-backtest/v1",
                "models": {
                    "ASTRA10_LIGHTGBM": {
                        "executed_trades": 2,
                        "net_return": -0.0098,
                    },
                    "QLIB_ALPHA158_LIGHTGBM": {
                        "executed_trades": 1,
                        "net_return": 0.0036,
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_s3_evidence_holds_models_and_emits_canonical_plans(tmp_path: Path) -> None:
    input_path = tmp_path / "s3.json"
    output_path = tmp_path / "targets.json"
    _write_s3_report(input_path)

    assert main([str(input_path), "--current-target", "600", "--output", str(output_path)]) == 0

    result = json.loads(output_path.read_text(encoding="utf-8"))
    astra = result["models"]["ASTRA10_LIGHTGBM"]
    alpha = result["models"]["QLIB_ALPHA158_LIGHTGBM"]
    assert result["schema_version"] == "astraquant.target-planning/v1"
    assert astra["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert astra["base_target"]["target_quantity"] == 600
    assert astra["base_target"]["reason"] == "INSUFFICIENT_EVIDENCE"
    assert alpha["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["canonical_validated_target"]["target_quantity"] == 1000
    assert result["canonical_t1"]["proposed_quantity"] == 1000
    assert result["canonical_t1"]["reachable_quantity"] == 1000
    assert result["canonical_t1"]["unreachable_quantity"] == 1000
    assert result["canonical_t1"]["reasons"] == ["T1_FROZEN", "RISK_REDUCTION_PARTIAL"]
    assert result["canonical_tplans"]["SELL_THEN_BUYBACK"]["planned_quantity"] == 800
    assert result["canonical_tplans"]["BUY_THEN_SELL_BASE"]["planned_quantity"] == 500


def test_target_plan_report_is_deterministic(tmp_path: Path) -> None:
    input_path = tmp_path / "s3.json"
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    _write_s3_report(input_path)

    assert main([str(input_path), "--output", str(first_path)]) == 0
    assert main([str(input_path), "--output", str(second_path)]) == 0

    assert first_path.read_bytes() == second_path.read_bytes()

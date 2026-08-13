from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from astraquant_domain.run_manifest import canonical_json_bytes
from tools.research.run_stage_b_v2_baselines import _load_materialization, main


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _materialization(root: Path, *, horizons: tuple[int, ...] = (5,)) -> Path:
    root.mkdir()
    start = datetime(2020, 1, 2, 7, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    row_id = 0
    for horizon in horizons:
        for session_index in range(80):
            decision_time = start + timedelta(days=session_index)
            for instrument_index in range(10):
                rank = instrument_index / 9
                rows.append(
                    {
                        "row_id": row_id,
                        "decision_time": decision_time,
                        "instrument_id": f"S{instrument_index:03d}.SSE",
                        "horizon_sessions": horizon,
                        "entry_time": decision_time + timedelta(days=1),
                        "exit_time": decision_time + timedelta(days=6),
                        "raw_return": (rank - 0.5) * 0.021,
                        "benchmark_return": 0.001,
                        "market_excess_return": (rank - 0.5) * 0.02,
                        "cross_sectional_rank": rank,
                        "downside_risk": max(0.0, 0.5 - rank) * 0.01,
                        "training_eligible": instrument_index not in (0, 9),
                        "signal": rank + session_index / 10000,
                        "missing": None if instrument_index % 4 == 0 else rank * 2,
                        "volatility_20": 0.1 + instrument_index / 100,
                        "turnover_median_20_log": 18.0,
                    }
                )
                row_id += 1
    matrix_path = root / "matrix.parquet"
    pq.write_table(pa.Table.from_pylist(rows), matrix_path, compression="zstd", version="2.6")
    body = {
        "schema_version": "astraquant.stage-b-v2-materialization/v1",
        "request_content_digest": "sha256:" + "1" * 64,
        "upstream_commit": "79633dd9506ea689e5400dea0197717b5b3d74b7",
        "alpha158_config_digest": "sha256:" + "2" * 64,
        "alpha158_feature_count": 158,
        "alpha158_missing_values": 200,
        "feature_columns": [
            "signal",
            "missing",
            "volatility_20",
            "turnover_median_20_log",
        ],
        "row_count": len(rows),
        "instrument_count": 10,
        "horizons": list(horizons),
        "matrix_file": {"path": "matrix.parquet", "digest": _digest(matrix_path.read_bytes())},
    }
    manifest = {"content_digest": _digest(canonical_json_bytes(body)), **body}
    (root / "manifest.json").write_bytes(canonical_json_bytes(manifest) + b"\n")
    return root


def _arguments(source: Path, output: Path) -> list[str]:
    return [
        str(source),
        "--output-root",
        str(output),
        "--minimum-fit-sessions",
        "20",
        "--inner-valid-sessions",
        "5",
        "--outer-test-sessions",
        "5",
        "--fold-count",
        "2",
        "--purge-sessions",
        "11",
        "--seeds",
        "7",
        "11",
        "--skip-double-ensemble",
    ]


def test_cli_runs_identical_ridge_lightgbm_matrix_and_freezes_report(tmp_path: Path) -> None:
    source = _materialization(tmp_path / "source")

    assert main(_arguments(source, tmp_path / "first")) == 0
    assert main(_arguments(source, tmp_path / "second")) == 0

    first = (tmp_path / "first" / "report.json").read_bytes()
    second = (tmp_path / "second" / "report.json").read_bytes()
    assert first == second
    report = json.loads(first)
    assert report["schema_version"] == "astraquant.stage-b-v2-baseline-report/v1"
    assert report["source_materialization_digest"].startswith("sha256:")
    assert report["models"] == ["LIGHTGBM", "RIDGE"]
    assert report["seeds"] == [7, 11]
    assert report["fold_count"] == 2
    assert report["trial_count"] == 8
    assert report["failed_trial_count"] == 0
    assert report["horizons"]["5"]["models"]["RIDGE"]["mean_rank_ic"] > 0.9
    assert report["horizons"]["5"]["models"]["LIGHTGBM"]["mean_rank_ic"] > 0.9
    ridge = report["horizons"]["5"]["models"]["RIDGE"]
    assert ridge["mean_net_return"] > 0
    assert ridge["mean_gross_return"] > ridge["mean_net_return"]
    assert ridge["mean_one_way_turnover"] > 0
    assert ridge["total_commission"] > 0
    assert ridge["total_stamp_duty"] > 0
    assert ridge["maximum_drawdown"] >= 0
    assert ridge["capacity_breach_trials"] == 0
    completed = next(item for item in report["trials"] if item["status"] == "COMPLETED")
    assert completed["fold_digest"].startswith("sha256:")
    assert completed["assignment_digest"].startswith("sha256:")
    assert completed["portfolio"]["net_return"] > 0
    assert completed["portfolio"]["period_count"] == 1
    assert set(completed["portfolio_profiles"]) == {"ADVERSE", "BASE", "SEVERE"}
    assert (
        completed["portfolio_profiles"]["BASE"]["net_return"]
        > completed["portfolio_profiles"]["ADVERSE"]["net_return"]
        > completed["portfolio_profiles"]["SEVERE"]["net_return"]
    )
    assert ridge["mean_severe_net_return"] < ridge["mean_net_return"]
    assert ridge["gate_status"] in {"NET_EDGE", "NO_NET_EDGE"}
    challenger = report["horizons"]["5"]["models"]["LIGHTGBM"]
    assert challenger["delta_net_vs_ridge"] == (
        challenger["mean_net_return"] - ridge["mean_net_return"]
    )
    assert report["content_digest"] == _digest(
        canonical_json_bytes(
            {key: value for key, value in report.items() if key != "content_digest"}
        )
    )


def test_cli_fails_closed_when_materialized_matrix_is_tampered(tmp_path: Path) -> None:
    source = _materialization(tmp_path / "source")
    with (source / "matrix.parquet").open("ab") as stream:
        stream.write(b"tampered")

    assert main(_arguments(source, tmp_path / "output")) == 1
    assert not (tmp_path / "output").exists()


def test_materialization_loader_reads_one_horizon_at_a_time(tmp_path: Path) -> None:
    source = _materialization(tmp_path / "source")

    manifest, rows, portfolio_inputs = _load_materialization(source, horizon=5)

    assert manifest["horizons"] == [5]
    assert rows
    assert {row.horizon_sessions for row in rows} == {5}
    assert set(portfolio_inputs) == {row.row_id for row in rows}


def test_cli_combines_independently_loaded_horizon_reports(tmp_path: Path) -> None:
    source = _materialization(tmp_path / "source", horizons=(1, 5))

    assert main(_arguments(source, tmp_path / "output")) == 0

    report = json.loads((tmp_path / "output" / "report.json").read_text(encoding="utf-8"))
    assert report["horizon_sessions"] == [1, 5]
    assert set(report["horizons"]) == {"1", "5"}
    assert report["trial_count"] == 16


def test_cli_runs_pinned_double_ensemble_through_same_folds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _materialization(tmp_path / "source")

    def fake_execute(request_path: Path, response_path: Path, project: Path) -> None:
        del project
        request = json.loads(request_path.read_text(encoding="utf-8"))
        rows = {
            int(row["row_id"]): float(row["signal"])
            for row in pq.read_table(request_path.parent / "rows.parquet").to_pylist()
        }
        trials = []
        for trial in request["trials"]:
            trials.append(
                {
                    "trial_id": trial["trial_id"],
                    "seed": trial["seed"],
                    "processor_digest": "sha256:" + "3" * 64,
                    "model_digest": "sha256:" + "4" * 64,
                    "inner_valid_predictions": [
                        {"row_id": row_id, "score": rows[row_id]}
                        for row_id in trial["inner_valid_row_ids"]
                    ],
                    "outer_test_predictions": [
                        {"row_id": row_id, "score": rows[row_id]}
                        for row_id in trial["outer_test_row_ids"]
                    ],
                }
            )
        body = {
            "schema_version": "astraquant.stage-b-v2-double-ensemble-response/v1",
            "request_content_digest": request["content_digest"],
            "source_materialization_digest": request["source_materialization_digest"],
            "upstream_commit": request["upstream_commit"],
            "trials": trials,
        }
        response = {"content_digest": _digest(canonical_json_bytes(body)), **body}
        response_path.write_bytes(canonical_json_bytes(response) + b"\n")

    monkeypatch.setattr(
        "tools.research.run_stage_b_v2_baselines._execute_double_ensemble",
        fake_execute,
    )
    arguments = _arguments(source, tmp_path / "output")
    arguments.remove("--skip-double-ensemble")

    assert main(arguments) == 0

    report = json.loads((tmp_path / "output" / "report.json").read_text(encoding="utf-8"))
    assert report["models"] == ["DOUBLE_ENSEMBLE", "LIGHTGBM", "RIDGE"]
    assert report["trial_count"] == 12
    double = report["horizons"]["5"]["models"]["DOUBLE_ENSEMBLE"]
    assert double["mean_rank_ic"] > 0.9
    assert (
        double["delta_net_vs_ridge"]
        == double["mean_net_return"] - report["horizons"]["5"]["models"]["RIDGE"]["mean_net_return"]
    )
    assert (tmp_path / "output" / "qlib" / "request.json").is_file()
    assert (tmp_path / "output" / "qlib" / "rows.parquet").is_file()
    assert (tmp_path / "output" / "qlib" / "response.json").is_file()

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from astraquant_domain.run_manifest import canonical_json_bytes
from tools.research.run_stage_b_v2_baselines import (
    _apply_relative_gate,
    _load_materialization,
    _prepare_stockmixer_v2_request,
    _select_batch_incumbent,
    main,
)


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
        "--skip-shared-mlp",
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


def test_prepares_stockmixer_request_from_one_shared_panel_without_copying_payload(
    tmp_path: Path,
) -> None:
    source = _materialization(tmp_path / "source")
    manifest, rows, _portfolio_inputs = _load_materialization(source, horizon=5)
    panel_root = tmp_path / "panel"
    panel_root.mkdir()
    panel_file = panel_root / "temporal-panel.parquet"
    rows_file = panel_root / "rows.parquet"
    panel_file.write_bytes(b"sealed-temporal-panel")
    rows_file.write_bytes(b"sealed-label-rows")
    panel_body = {
        "schema_version": "astraquant.stage-b-v2-stockmixer-panel/v1",
        "source_raw_export_digest": "sha256:" + "3" * 64,
        "source_materialization_digest": manifest["content_digest"],
        "horizons": [5],
        "lookback": 64,
        "price_transform": "PREVIOUS_CLOSE_RELATIVE_V1",
        "volume_transform": "LOG1P_DIFFERENCE_V1",
        "context_visibility": "DECISION_TIME_ONLY",
        "temporal_columns": [
            "open_relative",
            "high_relative",
            "low_relative",
            "close_relative",
            "log_volume_change",
            "log_turnover_change",
        ],
        "context_columns": ["signal", "volatility_20"],
        "instrument_count": 10,
        "session_count": 80,
        "panel_row_count": 800,
        "row_count": len(rows),
        "temporal_panel_file": {
            "path": "temporal-panel.parquet",
            "digest": _digest(panel_file.read_bytes()),
            "row_count": 800,
        },
        "rows_file": {"path": "rows.parquet", "digest": _digest(rows_file.read_bytes())},
    }
    (panel_root / "manifest.json").write_bytes(
        canonical_json_bytes(
            {"content_digest": _digest(canonical_json_bytes(panel_body)), **panel_body}
        )
        + b"\n"
    )
    identity = {
        "package": "astraquant-stockmixer-runner",
        "version": "0.1.0",
        "torch_version": "2.7.1+test",
        "device": "cpu",
    }

    request_path = _prepare_stockmixer_v2_request(
        root=tmp_path / "request",
        panel_root=panel_root,
        manifest=manifest,
        rows=rows,
        seeds=(7,),
        minimum_fit_sessions=20,
        inner_valid_sessions=5,
        outer_test_sessions=5,
        fold_count=2,
        purge_sessions=11,
        runner_identity=identity,
    )

    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["horizon_sessions"] == 5
    assert request["source_raw_export_digest"] == panel_body["source_raw_export_digest"]
    assert len(request["trials"]) == 2
    assert request["trials"][0]["trial_id"].startswith("h5-stockmixer_v2-s7-")
    assert (
        request_path.parent / "temporal-panel.parquet"
    ).stat().st_ino == panel_file.stat().st_ino
    assert (request_path.parent / "rows.parquet").stat().st_ino == rows_file.stat().st_ino


def test_cli_combines_independently_loaded_horizon_reports(tmp_path: Path) -> None:
    source = _materialization(tmp_path / "source", horizons=(1, 5))

    assert main(_arguments(source, tmp_path / "output")) == 0

    report = json.loads((tmp_path / "output" / "report.json").read_text(encoding="utf-8"))
    assert report["horizon_sessions"] == [1, 5]
    assert set(report["horizons"]) == {"1", "5"}
    assert report["trial_count"] == 16


def test_cli_resumes_completed_horizons_from_persistent_checkpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _materialization(tmp_path / "source", horizons=(1, 5))
    checkpoint = tmp_path / "checkpoints"
    first_arguments = [
        *_arguments(source, tmp_path / "first"),
        "--checkpoint-root",
        str(checkpoint),
    ]

    assert main(first_arguments) == 0
    assert (checkpoint / "h1" / "report.json").is_file()
    assert (checkpoint / "h5" / "report.json").is_file()

    def fail_if_retrained(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise AssertionError("completed horizon was retrained")

    monkeypatch.setattr(
        "tools.research.run_stage_b_v2_baselines._run_matrix",
        fail_if_retrained,
    )
    second_arguments = [
        *_arguments(source, tmp_path / "second"),
        "--checkpoint-root",
        str(checkpoint),
    ]

    assert main(second_arguments) == 0
    assert (tmp_path / "first" / "report.json").read_bytes() == (
        tmp_path / "second" / "report.json"
    ).read_bytes()


def test_cli_rejects_tampered_horizon_checkpoint(tmp_path: Path) -> None:
    source = _materialization(tmp_path / "source")
    checkpoint = tmp_path / "checkpoints"
    arguments = [
        *_arguments(source, tmp_path / "first"),
        "--checkpoint-root",
        str(checkpoint),
    ]
    assert main(arguments) == 0
    report_path = checkpoint / "h5" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["fold_count"] = 99
    report_path.write_text(json.dumps(report), encoding="utf-8")

    second = [
        *_arguments(source, tmp_path / "second"),
        "--checkpoint-root",
        str(checkpoint),
    ]
    assert main(second) == 1
    assert not (tmp_path / "second").exists()


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

    monkeypatch.setattr(
        "tools.research.run_stage_b_v2_baselines._execute_double_ensemble",
        lambda *args, **kwargs: pytest.fail("verified DoubleEnsemble trials must be reused"),
    )
    resumed = _arguments(source, tmp_path / "resumed")
    resumed.remove("--skip-double-ensemble")
    resumed.extend(
        [
            "--reuse-double-checkpoint-root",
            str(tmp_path / "output.checkpoints"),
        ]
    )

    assert main(resumed) == 0
    assert (tmp_path / "output" / "report.json").read_bytes() == (
        tmp_path / "resumed" / "report.json"
    ).read_bytes()


def test_cli_runs_shared_mlp_through_same_folds_and_cost_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _materialization(tmp_path / "source")
    identity = {
        "package": "astraquant-stockmixer-runner",
        "version": "0.1.0",
        "torch_version": "2.7.1+test",
        "device": "cpu",
    }
    monkeypatch.setattr(
        "tools.research.run_stage_b_v2_baselines._query_shared_mlp_identity",
        lambda project, device: identity,
    )

    def fake_execute(request_path: Path, response_path: Path, project: Path) -> None:
        del project
        request = json.loads(request_path.read_text(encoding="utf-8"))
        rows = {
            int(row["row_id"]): float(row["signal"])
            for row in pq.read_table(request_path.parent / "rows.parquet").to_pylist()
        }
        trials = [
            {
                "trial_id": trial["trial_id"],
                "seed": trial["seed"],
                "processor_digest": "sha256:" + "5" * 64,
                "model_digest": "sha256:" + "6" * 64,
                "inner_valid_predictions": [
                    {"row_id": row_id, "score": rows[row_id]}
                    for row_id in trial["inner_valid_row_ids"]
                ],
                "outer_test_predictions": [
                    {"row_id": row_id, "score": rows[row_id]}
                    for row_id in trial["outer_test_row_ids"]
                ],
            }
            for trial in request["trials"]
        ]
        body = {
            "schema_version": "astraquant.stage-b-v2-shared-mlp-response/v1",
            "request_content_digest": request["content_digest"],
            "source_materialization_digest": request["source_materialization_digest"],
            "runner_identity": identity,
            "trials": trials,
        }
        response_path.write_bytes(
            canonical_json_bytes({"content_digest": _digest(canonical_json_bytes(body)), **body})
            + b"\n"
        )

    monkeypatch.setattr(
        "tools.research.run_stage_b_v2_baselines._execute_shared_mlp",
        fake_execute,
    )
    arguments = _arguments(source, tmp_path / "output")
    arguments.remove("--skip-shared-mlp")

    assert main(arguments) == 0

    report = json.loads((tmp_path / "output" / "report.json").read_text(encoding="utf-8"))
    assert report["models"] == ["LIGHTGBM", "RIDGE", "SHARED_MLP"]
    assert report["trial_count"] == 12

    shared = report["horizons"]["5"]["models"]["SHARED_MLP"]
    assert shared["mean_rank_ic"] > 0.9
    assert shared["mean_net_return"] > 0
    assert set(report["trials"][-1]["portfolio_profiles"]) == {
        "ADVERSE",
        "BASE",
        "SEVERE",
    }
    assert (tmp_path / "output" / "shared-mlp" / "request.json").is_file()
    assert (tmp_path / "output" / "shared-mlp" / "rows.parquet").is_file()
    assert (tmp_path / "output" / "shared-mlp" / "response.json").is_file()


def test_shared_mlp_relative_gate_requires_severe_profit_and_seed_stability() -> None:
    reports: dict[str, Any] = {
        "RIDGE": {"mean_net_return": 0.01},
        "SHARED_MLP": {
            "gate_status": "NET_EDGE",
            "mean_net_return": 0.013,
            "mean_severe_net_return": -0.0001,
            "positive_fold_count": 6,
            "positive_fold_required": 4,
            "seed_mean_net_return": {"7": 0.02, "29": 0.01, "53": 0.009},
        },
    }

    _apply_relative_gate(reports)

    assert reports["SHARED_MLP"]["delta_net_vs_ridge"] == pytest.approx(0.003)
    assert reports["SHARED_MLP"]["gate_status"] == "NO_NET_EDGE"


def test_batch_incumbent_uses_one_aggregate_policy_across_horizons() -> None:
    def summary(
        *,
        net: float,
        rank_ic: float,
        severe: float,
        seed_net: tuple[float, float, float] = (0.01, 0.01, 0.01),
        positive_folds: int = 6,
    ) -> dict[str, Any]:
        return {
            "status": "LEARNABLE_EDGE",
            "mean_net_return": net,
            "mean_rank_ic": rank_ic,
            "mean_severe_net_return": severe,
            "positive_fold_count": positive_folds,
            "positive_fold_required": 4,
            "seed_mean_net_return": {
                "7": seed_net[0],
                "29": seed_net[1],
                "53": seed_net[2],
            },
        }

    horizons = {
        "1": {
            "models": {
                "RIDGE": summary(net=0.010, rank_ic=0.050, severe=0.004),
                "SHARED_MLP": summary(net=0.016, rank_ic=0.052, severe=0.008),
                "DOUBLE_ENSEMBLE": summary(net=0.020, rank_ic=0.045, severe=0.010),
            }
        },
        "5": {
            "models": {
                "RIDGE": summary(net=0.010, rank_ic=0.055, severe=0.005),
                "SHARED_MLP": summary(net=0.011, rank_ic=0.056, severe=0.006),
                "DOUBLE_ENSEMBLE": summary(net=0.011, rank_ic=0.049, severe=0.007),
            }
        },
        "10": {
            "models": {
                "RIDGE": summary(net=0.010, rank_ic=0.060, severe=0.006),
                "SHARED_MLP": summary(net=0.012, rank_ic=0.061, severe=0.007),
                "DOUBLE_ENSEMBLE": summary(net=0.013, rank_ic=0.058, severe=0.008),
            }
        },
    }

    aggregate, incumbent = _select_batch_incumbent(horizons)

    assert aggregate["DOUBLE_ENSEMBLE"]["aggregate_gate_status"] == "NET_EDGE"
    assert aggregate["DOUBLE_ENSEMBLE"]["mean_net_return"] == pytest.approx(
        (0.020 + 0.011 + 0.013) / 3
    )
    assert aggregate["DOUBLE_ENSEMBLE"]["delta_net_vs_ridge"] == pytest.approx(
        aggregate["DOUBLE_ENSEMBLE"]["mean_net_return"] - 0.010
    )
    assert incumbent["model"] == "DOUBLE_ENSEMBLE"
    assert incumbent["selection_scope"] == "ALL_HORIZONS_EQUAL_WEIGHT"


def test_batch_incumbent_rejects_unstable_challenger() -> None:
    ridge = {
        "status": "LEARNABLE_EDGE",
        "mean_net_return": 0.01,
        "mean_rank_ic": 0.05,
        "mean_severe_net_return": 0.004,
        "positive_fold_count": 6,
        "positive_fold_required": 4,
        "seed_mean_net_return": {"7": 0.01, "29": 0.01, "53": 0.01},
    }
    unstable = {
        **ridge,
        "mean_net_return": 0.02,
        "mean_severe_net_return": 0.01,
        "seed_mean_net_return": {"7": 0.02, "29": -0.001, "53": 0.02},
    }
    horizons = {
        "1": {"models": {"RIDGE": ridge, "SHARED_MLP": unstable}},
        "5": {"models": {"RIDGE": ridge, "SHARED_MLP": unstable}},
    }

    aggregate, incumbent = _select_batch_incumbent(horizons)

    assert aggregate["SHARED_MLP"]["aggregate_gate_status"] == "NO_NET_EDGE"
    assert incumbent["model"] == "RIDGE"


def test_cli_reuses_verified_local_trials_when_adding_shared_mlp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _materialization(tmp_path / "source")
    local_checkpoints = tmp_path / "local-checkpoints"
    assert (
        main(
            [
                *_arguments(source, tmp_path / "local-output"),
                "--checkpoint-root",
                str(local_checkpoints),
            ]
        )
        == 0
    )
    identity = {
        "package": "astraquant-stockmixer-runner",
        "version": "0.1.0",
        "torch_version": "2.7.1+test",
        "device": "cpu",
    }
    monkeypatch.setattr(
        "tools.research.run_stage_b_v2_baselines._query_shared_mlp_identity",
        lambda project, device: identity,
    )

    def fake_execute(request_path: Path, response_path: Path, project: Path) -> None:
        del project
        request = json.loads(request_path.read_text(encoding="utf-8"))
        rows = {
            int(row["row_id"]): float(row["signal"])
            for row in pq.read_table(request_path.parent / "rows.parquet").to_pylist()
        }
        body = {
            "schema_version": "astraquant.stage-b-v2-shared-mlp-response/v1",
            "request_content_digest": request["content_digest"],
            "source_materialization_digest": request["source_materialization_digest"],
            "runner_identity": identity,
            "trials": [
                {
                    "trial_id": trial["trial_id"],
                    "seed": trial["seed"],
                    "processor_digest": "sha256:" + "7" * 64,
                    "model_digest": "sha256:" + "8" * 64,
                    "inner_valid_predictions": [
                        {"row_id": row_id, "score": rows[row_id]}
                        for row_id in trial["inner_valid_row_ids"]
                    ],
                    "outer_test_predictions": [
                        {"row_id": row_id, "score": rows[row_id]}
                        for row_id in trial["outer_test_row_ids"]
                    ],
                }
                for trial in request["trials"]
            ],
        }
        response_path.write_bytes(
            canonical_json_bytes({"content_digest": _digest(canonical_json_bytes(body)), **body})
            + b"\n"
        )

    monkeypatch.setattr("tools.research.run_stage_b_v2_baselines._execute_shared_mlp", fake_execute)
    monkeypatch.setattr(
        "tools.research.run_stage_b_v2_baselines.run_cross_sectional_baselines",
        lambda *args, **kwargs: pytest.fail("verified local trials must not be retrained"),
    )
    arguments = _arguments(source, tmp_path / "combined")
    arguments.remove("--skip-shared-mlp")
    arguments.extend(
        [
            "--checkpoint-root",
            str(tmp_path / "combined-checkpoints"),
            "--reuse-local-checkpoint-root",
            str(local_checkpoints),
        ]
    )

    assert main(arguments) == 0
    report = json.loads((tmp_path / "combined" / "report.json").read_text(encoding="utf-8"))
    assert report["models"] == ["LIGHTGBM", "RIDGE", "SHARED_MLP"]
    assert report["trial_count"] == 12

    monkeypatch.setattr(
        "tools.research.run_stage_b_v2_baselines._execute_shared_mlp",
        lambda *args, **kwargs: pytest.fail("verified Shared MLP trials must be reused"),
    )
    resumed_arguments = _arguments(source, tmp_path / "resumed-combined")
    resumed_arguments.remove("--skip-shared-mlp")
    resumed_arguments.extend(
        [
            "--checkpoint-root",
            str(tmp_path / "resumed-checkpoints"),
            "--reuse-local-checkpoint-root",
            str(local_checkpoints),
            "--reuse-shared-checkpoint-root",
            str(tmp_path / "combined-checkpoints"),
        ]
    )
    assert main(resumed_arguments) == 0
    assert (tmp_path / "combined" / "report.json").read_bytes() == (
        tmp_path / "resumed-combined" / "report.json"
    ).read_bytes()

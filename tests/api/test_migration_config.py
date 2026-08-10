import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from astraquant_api.database import create_database
from astraquant_api.migration_config import resolve_migration_url

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _config(database_url: str) -> Config:
    config = Config(str(_REPOSITORY_ROOT / "packages/api/alembic.ini"))
    config.set_main_option(
        "script_location",
        str(_REPOSITORY_ROOT / "packages/api/migrations"),
    )
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _upgrade_to_0008_and_seed(
    database_path: Path,
    *,
    reverse_positions: bool = False,
) -> tuple[Config, sa.Engine]:
    database_url = f"sqlite:///{database_path}"
    config = _config(database_url)
    command.upgrade(config, "0008_experiments")
    engine = create_database(database_url)
    now = datetime(2026, 8, 10, tzinfo=UTC)
    positions = [
        {"instrument_id": "600000.SSE", "name": "浦发银行"},
        {"instrument_id": "000001.SZSE", "name": "平安银行"},
    ]
    if reverse_positions:
        positions.reverse()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO data_datasets "
                "(dataset_id, name, asset_class, frequency, created_at) "
                "VALUES (:dataset_id, :name, :asset_class, :frequency, :created_at)"
            ),
            {
                "dataset_id": "formal-real-api-bars",
                "name": "伪装正式数据",
                "asset_class": "equity",
                "frequency": "1d",
                "created_at": now,
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO data_snapshots "
                "(snapshot_id, dataset_id, status, row_count, min_event_time, "
                "max_event_time, provider_id, manifest_path, created_at) "
                "VALUES (:snapshot_id, :dataset_id, 'PUBLISHED', 1, :event_time, "
                ":event_time, 'eastmoney', :manifest_path, :created_at)"
            ),
            {
                "snapshot_id": "1" * 64,
                "dataset_id": "formal-real-api-bars",
                "event_time": now,
                "manifest_path": "formal/real-api/manifest.json",
                "created_at": now,
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO paper_accounts "
                "(account_id, name, mode, initial_cash, initial_equity, cash, "
                "created_at, updated_at) VALUES "
                "('account-legacy', '旧模拟账户', 'PAPER', '100000', '100000', "
                "'100000', :created_at, :updated_at)"
            ),
            {"created_at": now, "updated_at": now},
        )
        for position in positions:
            connection.execute(
                sa.text(
                    "INSERT INTO paper_positions "
                    "(account_id, instrument_id, name, quantity, available_quantity, "
                    "average_cost, last_price, marked_at) VALUES "
                    "('account-legacy', :instrument_id, :name, 100, 100, "
                    "'10.00', '10.10', :marked_at)"
                ),
                {**position, "marked_at": now},
            )
        connection.execute(
            sa.text(
                "INSERT INTO paper_strategy_runs "
                "(decision_id, batch_id, account_id, instrument_id, outcome, "
                "proposed_side, proposed_quantity, risk_reason, signal_json, "
                "advisory_checks_json, order_json, fill_json, decision_time) VALUES "
                "('decision-legacy', 'batch-legacy', 'account-legacy', '600000.SSE', "
                "'SKIPPED', NULL, 0, NULL, '{}', '[]', NULL, NULL, :decision_time)"
            ),
            {"decision_time": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO model_registry "
                "(model_id, strategy_id, strategy_version, feature_version, artifact_path, "
                "metrics_json, params_json, status, created_at, updated_at, approved_at) "
                "VALUES ('model-legacy', 'demo', 'v1', 'v1', "
                "'formal/eastmoney/model.txt', :metrics, '{}', 'APPROVED', "
                ":created_at, :updated_at, :approved_at)"
            ),
            {
                "metrics": json.dumps({"auc": 0.99, "net_return": 9.0}),
                "created_at": now,
                "updated_at": now,
                "approved_at": now,
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO research_experiments "
                "(experiment_id, request_json, summary_json, results_json, created_at) "
                "VALUES ('experiment-legacy', '{}', '{}', '{}', :created_at)"
            ),
            {"created_at": now},
        )
    return config, engine


def test_cli_database_url_is_used_when_ini_has_no_url() -> None:
    assert (
        resolve_migration_url(
            configured_url=None,
            cli_arguments={"database_url": "sqlite:///phase2.sqlite3"},
        )
        == "sqlite:///phase2.sqlite3"
    )


def test_missing_migration_database_url_has_an_actionable_error() -> None:
    with pytest.raises(RuntimeError, match="-x database_url"):
        resolve_migration_url(configured_url=None, cli_arguments={})


def test_0009_backfills_legacy_classes_and_seals_existing_paper(
    tmp_path: Path,
) -> None:
    config, engine = _upgrade_to_0008_and_seed(tmp_path / "legacy.sqlite3")

    command.upgrade(config, "head")

    with engine.connect() as connection:
        snapshot = connection.execute(sa.text("SELECT * FROM data_snapshots")).mappings().one()
        model = connection.execute(sa.text("SELECT * FROM model_registry")).mappings().one()
        experiment = connection.execute(
            sa.text("SELECT * FROM research_experiments")
        ).mappings().one()
        replay = connection.execute(
            sa.text("SELECT * FROM paper_strategy_runs")
        ).mappings().one()
        account = connection.execute(sa.text("SELECT * FROM paper_accounts")).mappings().one()
        seal = connection.execute(
            sa.text("SELECT * FROM paper_legacy_ledger_seals")
        ).mappings().one()
        version = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()

    for row in (snapshot, model, experiment, replay):
        assert row["semantic_class"] == "LEGACY_SEMANTICS"
        assert row["evidence_class"] == "LEGACY_UNVERIFIED"
        assert row["run_class"] == "EXPLORATORY"
        assert row["manifest_schema"] == "1"
        assert row["content_digest"] is None
    assert account["semantic_class"] == "LEGACY_SEMANTICS"
    assert account["evidence_class"] == "LEGACY_UNVERIFIED"
    assert account["run_class"] == "EXPLORATORY"
    assert seal["ledger_content_digest"].startswith("sha256:")
    assert seal["ledger_content_digest"] != "sha256:" + "0" * 64
    assert seal["seal_status"] == "SEALED_LEGACY"
    assert version == "0009_v3_legacy_evidence"


def test_0009_legacy_ledger_digest_ignores_row_insertion_order(tmp_path: Path) -> None:
    first_config, first_engine = _upgrade_to_0008_and_seed(tmp_path / "first.sqlite3")
    second_config, second_engine = _upgrade_to_0008_and_seed(
        tmp_path / "second.sqlite3",
        reverse_positions=True,
    )

    command.upgrade(first_config, "head")
    command.upgrade(second_config, "head")

    digests: list[str] = []
    for engine in (first_engine, second_engine):
        with engine.connect() as connection:
            digests.append(
                connection.execute(
                    sa.text(
                        "SELECT ledger_content_digest FROM paper_legacy_ledger_seals "
                        "WHERE account_id = 'account-legacy'"
                    )
                ).scalar_one()
            )
    assert digests[0] == digests[1]

"""Classify v2 artifacts as legacy and seal pre-v3 Paper ledgers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "0009_v3_legacy_evidence"
down_revision: str | Sequence[str] | None = "0008_experiments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLASSIFIED_TABLES = (
    "data_snapshots",
    "model_registry",
    "research_experiments",
    "paper_strategy_runs",
)
_LEDGER_TABLE_KEYS = (
    ("paper_accounts", ("account_id",)),
    ("paper_positions", ("instrument_id",)),
    ("paper_orders", ("order_id",)),
    ("paper_fills", ("fill_id",)),
    ("paper_equity_snapshots", ("snapshot_id",)),
    ("paper_strategy_runs", ("decision_id",)),
    ("paper_daily_open", ("trading_date",)),
)


def _classification_columns() -> tuple[sa.Column[str], ...]:
    return (
        sa.Column(
            "semantic_class",
            sa.String(32),
            nullable=False,
            server_default="LEGACY_SEMANTICS",
        ),
        sa.Column(
            "evidence_class",
            sa.String(32),
            nullable=False,
            server_default="LEGACY_UNVERIFIED",
        ),
        sa.Column(
            "run_class",
            sa.String(32),
            nullable=False,
            server_default="EXPLORATORY",
        ),
        sa.Column(
            "manifest_schema",
            sa.String(64),
            nullable=False,
            server_default="1",
        ),
        sa.Column("content_digest", sa.String(71)),
    )


def _normalize(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def _ledger_digest(connection: sa.Connection, account_id: str) -> str:
    metadata = sa.MetaData()
    payload: dict[str, object] = {"schema_revision": down_revision, "tables": {}}
    table_payload = payload["tables"]
    assert isinstance(table_payload, dict)
    for table_name, order_keys in _LEDGER_TABLE_KEYS:
        table = sa.Table(table_name, metadata, autoload_with=connection)
        statement = sa.select(table).where(table.c.account_id == account_id)
        statement = statement.order_by(*(table.c[key] for key in order_keys))
        rows = connection.execute(statement).mappings()
        table_payload[table_name] = [
            {key: _normalize(value) for key, value in sorted(dict(row).items())} for row in rows
        ]
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def upgrade() -> None:
    for table_name in _CLASSIFIED_TABLES:
        for column in _classification_columns():
            op.add_column(table_name, column)
    for name, default in (
        ("semantic_class", "LEGACY_SEMANTICS"),
        ("evidence_class", "LEGACY_UNVERIFIED"),
        ("run_class", "EXPLORATORY"),
    ):
        op.add_column(
            "paper_accounts",
            sa.Column(name, sa.String(32), nullable=False, server_default=default),
        )

    op.create_table(
        "paper_legacy_ledger_seals",
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.account_id"),
            primary_key=True,
        ),
        sa.Column("source_revision", sa.String(64), nullable=False),
        sa.Column("ledger_content_digest", sa.String(71), nullable=False),
        sa.Column("seal_status", sa.String(32), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_opening_imports",
        sa.Column("import_id", sa.String(36), primary_key=True),
        sa.Column(
            "source_account_id",
            sa.String(36),
            sa.ForeignKey("paper_legacy_ledger_seals.account_id"),
            nullable=False,
        ),
        sa.Column("source_ledger_seal_digest", sa.String(71), nullable=False),
        sa.Column("target_account_id", sa.String(36), nullable=False),
        sa.Column("reconciliation_digest", sa.String(71), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_account_id",
            name="uq_paper_opening_imports_source_account",
        ),
    )

    connection = op.get_bind()
    account_ids = connection.execute(
        sa.text("SELECT account_id FROM paper_accounts ORDER BY account_id")
    ).scalars()
    sealed_at = datetime.now(UTC)
    seals = [
        {
            "account_id": account_id,
            "source_revision": str(down_revision),
            "ledger_content_digest": _ledger_digest(connection, account_id),
            "seal_status": "SEALED_LEGACY",
            "sealed_at": sealed_at,
        }
        for account_id in account_ids
    ]
    if seals:
        seal_table = sa.Table(
            "paper_legacy_ledger_seals",
            sa.MetaData(),
            autoload_with=connection,
        )
        connection.execute(seal_table.insert(), seals)


def downgrade() -> None:
    op.drop_table("paper_opening_imports")
    op.drop_table("paper_legacy_ledger_seals")
    with op.batch_alter_table("paper_accounts") as batch:
        batch.drop_column("run_class")
        batch.drop_column("evidence_class")
        batch.drop_column("semantic_class")
    for table_name in reversed(_CLASSIFIED_TABLES):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column("content_digest")
            batch.drop_column("manifest_schema")
            batch.drop_column("run_class")
            batch.drop_column("evidence_class")
            batch.drop_column("semantic_class")

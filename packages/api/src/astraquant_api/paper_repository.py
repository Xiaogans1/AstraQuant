"""Transactional SQLite repository for the local Paper ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import Engine, RowMapping
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from astraquant_domain import (
    AccountMode,
    InstrumentId,
    OrderSide,
    OrderStatus,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PortfolioSnapshot,
    Position,
)
from astraquant_paper import LedgerState

metadata = sa.MetaData()

paper_accounts = sa.Table(
    "paper_accounts",
    metadata,
    sa.Column("account_id", sa.String(36), primary_key=True),
    sa.Column("name", sa.String(100), nullable=False),
    sa.Column("mode", sa.String(16), nullable=False),
    sa.Column("initial_cash", sa.String(64), nullable=False),
    sa.Column("initial_equity", sa.String(64), nullable=False),
    sa.Column("cash", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
    sa.CheckConstraint("mode IN ('PAPER', 'MIRROR')", name="ck_paper_accounts_mode"),
    sa.Index("ix_paper_accounts_created", "created_at"),
)
paper_positions = sa.Table(
    "paper_positions",
    metadata,
    sa.Column(
        "account_id",
        sa.String(36),
        sa.ForeignKey("paper_accounts.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("instrument_id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(200)),
    sa.Column("quantity", sa.Integer(), nullable=False),
    sa.Column("available_quantity", sa.Integer(), nullable=False),
    sa.Column("average_cost", sa.String(64), nullable=False),
    sa.Column("last_price", sa.String(64)),
    sa.Column("marked_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint("quantity > 0", name="ck_paper_positions_quantity"),
    sa.CheckConstraint(
        "available_quantity >= 0 AND available_quantity <= quantity",
        name="ck_paper_positions_available",
    ),
)
paper_orders = sa.Table(
    "paper_orders",
    metadata,
    sa.Column("order_id", sa.String(36), primary_key=True),
    sa.Column(
        "account_id",
        sa.String(36),
        sa.ForeignKey("paper_accounts.account_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("idempotency_key", sa.String(200), nullable=False),
    sa.Column("instrument_id", sa.String(64), nullable=False),
    sa.Column("side", sa.String(8), nullable=False),
    sa.Column("quantity", sa.Integer(), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("reject_reason", sa.String(100)),
    sa.UniqueConstraint(
        "account_id",
        "idempotency_key",
        name="uq_paper_orders_account_idempotency",
    ),
    sa.Index("ix_paper_orders_account_submitted", "account_id", "submitted_at"),
)
paper_fills = sa.Table(
    "paper_fills",
    metadata,
    sa.Column("fill_id", sa.String(36), primary_key=True),
    sa.Column(
        "order_id",
        sa.String(36),
        sa.ForeignKey("paper_orders.order_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "account_id",
        sa.String(36),
        sa.ForeignKey("paper_accounts.account_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("instrument_id", sa.String(64), nullable=False),
    sa.Column("side", sa.String(8), nullable=False),
    sa.Column("quantity", sa.Integer(), nullable=False),
    sa.Column("price", sa.String(64), nullable=False),
    sa.Column("gross_amount", sa.String(64), nullable=False),
    sa.Column("commission", sa.String(64), nullable=False),
    sa.Column("stamp_duty", sa.String(64), nullable=False),
    sa.Column("transfer_fee", sa.String(64), nullable=False),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_paper_fills_account_occurred", "account_id", "occurred_at"),
)
paper_equity_snapshots = sa.Table(
    "paper_equity_snapshots",
    metadata,
    sa.Column("snapshot_id", sa.String(36), primary_key=True),
    sa.Column(
        "account_id",
        sa.String(36),
        sa.ForeignKey("paper_accounts.account_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("cash", sa.String(64), nullable=False),
    sa.Column("market_value", sa.String(64), nullable=False),
    sa.Column("total_equity", sa.String(64), nullable=False),
    sa.Column("initial_equity", sa.String(64), nullable=False),
    sa.Column("total_pnl", sa.String(64), nullable=False),
    sa.Column("total_pnl_percent", sa.String(64)),
    sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_paper_equity_account_as_of", "account_id", "as_of"),
)
paper_strategy_runs = sa.Table(
    "paper_strategy_runs",
    metadata,
    sa.Column("decision_id", sa.String(36), primary_key=True),
    sa.Column("batch_id", sa.String(36), nullable=False),
    sa.Column(
        "account_id",
        sa.String(36),
        sa.ForeignKey("paper_accounts.account_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("instrument_id", sa.String(64), nullable=False),
    sa.Column("outcome", sa.String(16), nullable=False),
    sa.Column("proposed_side", sa.String(8)),
    sa.Column("proposed_quantity", sa.Integer(), nullable=False),
    sa.Column("risk_reason", sa.String(200)),
    sa.Column("signal_json", sa.Text(), nullable=False),
    sa.Column("advisory_checks_json", sa.Text(), nullable=False),
    sa.Column("order_json", sa.Text()),
    sa.Column("fill_json", sa.Text()),
    sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
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
    sa.Column("manifest_schema", sa.String(64), nullable=False, server_default="1"),
    sa.Column("content_digest", sa.String(71)),
    sa.Index("ix_paper_strategy_runs_account_time", "account_id", "decision_time"),
    sa.Index("ix_paper_strategy_runs_batch", "batch_id"),
)
model_registry = sa.Table(
    "model_registry",
    metadata,
    sa.Column("model_id", sa.String(64), primary_key=True),
    sa.Column("strategy_id", sa.String(64), nullable=False),
    sa.Column("strategy_version", sa.String(64), nullable=False),
    sa.Column("feature_version", sa.String(64), nullable=False),
    sa.Column("artifact_path", sa.String(400), nullable=False),
    sa.Column("metrics_json", sa.Text(), nullable=False),
    sa.Column("params_json", sa.Text(), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("approved_at", sa.DateTime(timezone=True)),
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
    sa.Column("manifest_schema", sa.String(64), nullable=False, server_default="1"),
    sa.Column("content_digest", sa.String(71)),
    sa.Index("ix_model_registry_status", "status"),
)
research_experiments = sa.Table(
    "research_experiments",
    metadata,
    sa.Column("experiment_id", sa.String(36), primary_key=True),
    sa.Column("request_json", sa.Text(), nullable=False),
    sa.Column("summary_json", sa.Text(), nullable=False),
    sa.Column("results_json", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
    sa.Column("manifest_schema", sa.String(64), nullable=False, server_default="1"),
    sa.Column("content_digest", sa.String(71)),
    sa.Index("ix_research_experiments_created", "created_at"),
)
paper_daily_open = sa.Table(
    "paper_daily_open",
    metadata,
    sa.Column("account_id", sa.String(36), nullable=False),
    sa.Column("trading_date", sa.Date(), nullable=False),
    sa.Column("cash", sa.String(64), nullable=False),
    sa.Column("positions_json", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("account_id", "trading_date"),
)

paper_legacy_ledger_seals = sa.Table(
    "paper_legacy_ledger_seals",
    metadata,
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

paper_opening_imports = sa.Table(
    "paper_opening_imports",
    metadata,
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


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    experiment_id: str
    request_json: str
    summary_json: str
    results_json: str
    created_at: datetime
    semantic_class: str = "LEGACY_SEMANTICS"
    evidence_class: str = "LEGACY_UNVERIFIED"
    run_class: str = "EXPLORATORY"
    manifest_schema: str = "1"
    content_digest: str | None = None


@dataclass(frozen=True, slots=True)
class ModelRegistryRecord:
    model_id: str
    strategy_id: str
    strategy_version: str
    feature_version: str
    artifact_path: str
    metrics_json: str
    status: str
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    params_json: str = "{}"
    semantic_class: str = "LEGACY_SEMANTICS"
    evidence_class: str = "LEGACY_UNVERIFIED"
    run_class: str = "EXPLORATORY"
    manifest_schema: str = "1"
    content_digest: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyRunRecord:
    decision_id: str
    batch_id: str
    account_id: str
    instrument_id: str
    outcome: str
    proposed_side: str | None
    proposed_quantity: int
    risk_reason: str | None
    signal_json: str
    advisory_checks: tuple[str, ...]
    order_json: str | None
    fill_json: str | None
    decision_time: datetime
    semantic_class: str = "LEGACY_SEMANTICS"
    evidence_class: str = "LEGACY_UNVERIFIED"
    run_class: str = "EXPLORATORY"
    manifest_schema: str = "1"
    content_digest: str | None = None


@dataclass(frozen=True, slots=True)
class LegacyLedgerSealRecord:
    account_id: str
    source_revision: str
    ledger_content_digest: str
    seal_status: str
    sealed_at: datetime


@dataclass(frozen=True, slots=True)
class OpeningImportRecord:
    import_id: str
    source_account_id: str
    source_ledger_seal_digest: str
    target_account_id: str
    reconciliation_digest: str
    status: str
    created_at: datetime


class LegacyLedgerSealedError(RuntimeError):
    """Raised when a pre-v3 sealed Paper ledger is mutated."""


class OpeningImportAlreadyExistsError(RuntimeError):
    """Raised when a sealed ledger already has an opening import."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _model_record(row: RowMapping) -> ModelRegistryRecord:
    return ModelRegistryRecord(
        model_id=row["model_id"],
        strategy_id=row["strategy_id"],
        strategy_version=row["strategy_version"],
        feature_version=row["feature_version"],
        artifact_path=row["artifact_path"],
        metrics_json=row["metrics_json"],
        params_json=row["params_json"],
        status=row["status"],
        created_at=_utc(row["created_at"]),
        updated_at=_utc(row["updated_at"]),
        approved_at=None if row["approved_at"] is None else _utc(row["approved_at"]),
        semantic_class=row["semantic_class"],
        evidence_class=row["evidence_class"],
        run_class=row["run_class"],
        manifest_schema=row["manifest_schema"],
        content_digest=row["content_digest"],
    )


def _experiment_record(row: RowMapping) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=row["experiment_id"],
        request_json=row["request_json"],
        summary_json=row["summary_json"],
        results_json=row["results_json"],
        created_at=_utc(row["created_at"]),
        semantic_class=row["semantic_class"],
        evidence_class=row["evidence_class"],
        run_class=row["run_class"],
        manifest_schema=row["manifest_schema"],
        content_digest=row["content_digest"],
    )


def _account_from_row(row: RowMapping) -> PaperAccount:
    return PaperAccount(
        account_id=row["account_id"],
        name=row["name"],
        mode=AccountMode(row["mode"]),
        initial_cash=_decimal(row["initial_cash"]),
        cash=_decimal(row["cash"]),
        created_at=_utc(row["created_at"]),
        updated_at=_utc(row["updated_at"]),
    )


class PaperRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_account(self, account: PaperAccount) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                paper_accounts.insert().values(
                    account_id=account.account_id,
                    name=account.name,
                    mode=account.mode.value,
                    initial_cash=str(account.initial_cash),
                    initial_equity=str(account.initial_cash),
                    cash=str(account.cash),
                    created_at=_utc(account.created_at),
                    updated_at=_utc(account.updated_at),
                    semantic_class="LEGACY_SEMANTICS",
                    evidence_class="LEGACY_UNVERIFIED",
                    run_class="EXPLORATORY",
                )
            )

    def list_accounts(self) -> list[PaperAccount]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                sa.select(paper_accounts).order_by(paper_accounts.c.created_at.desc())
            ).mappings()
            return [_account_from_row(row) for row in rows]

    def delete_account(self, account_id: str) -> None:
        with self.engine.begin() as connection:
            self._ensure_ledger_is_mutable(connection, account_id)
            result = connection.execute(
                sa.delete(paper_accounts).where(paper_accounts.c.account_id == account_id)
            )
            if result.rowcount != 1:
                raise KeyError(account_id)

    def load_state(self, account_id: str) -> LedgerState:
        with self.engine.connect() as connection:
            account_row = (
                connection.execute(
                    sa.select(paper_accounts).where(paper_accounts.c.account_id == account_id)
                )
                .mappings()
                .one_or_none()
            )
            if account_row is None:
                raise KeyError(account_id)
            position_rows = list(
                connection.execute(
                    sa.select(paper_positions)
                    .where(paper_positions.c.account_id == account_id)
                    .order_by(paper_positions.c.instrument_id)
                ).mappings()
            )
            order_rows = list(
                connection.execute(
                    sa.select(paper_orders)
                    .where(paper_orders.c.account_id == account_id)
                    .order_by(paper_orders.c.submitted_at)
                ).mappings()
            )
            fill_rows = list(
                connection.execute(
                    sa.select(paper_fills)
                    .where(paper_fills.c.account_id == account_id)
                    .order_by(paper_fills.c.occurred_at)
                ).mappings()
            )
            snapshot_rows = list(
                connection.execute(
                    sa.select(paper_equity_snapshots)
                    .where(paper_equity_snapshots.c.account_id == account_id)
                    .order_by(paper_equity_snapshots.c.as_of)
                ).mappings()
            )
        return LedgerState(
            account=_account_from_row(account_row),
            initial_equity=_decimal(account_row["initial_equity"]),
            positions=tuple(self._position(row) for row in position_rows),
            orders=tuple(self._order(row) for row in order_rows),
            fills=tuple(self._fill(row) for row in fill_rows),
            snapshots=tuple(self._snapshot(row) for row in snapshot_rows),
        )

    def save_state(self, state: LedgerState) -> None:
        assert state.initial_equity is not None
        with self.engine.begin() as connection:
            self._ensure_ledger_is_mutable(connection, state.account.account_id)
            result = connection.execute(
                paper_accounts.update()
                .where(paper_accounts.c.account_id == state.account.account_id)
                .values(
                    cash=str(state.account.cash),
                    initial_equity=str(state.initial_equity),
                    updated_at=_utc(state.account.updated_at),
                )
            )
            if result.rowcount != 1:
                raise KeyError(state.account.account_id)
            connection.execute(
                paper_positions.delete().where(
                    paper_positions.c.account_id == state.account.account_id
                )
            )
            if state.positions:
                connection.execute(
                    paper_positions.insert(),
                    [self._position_values(item) for item in state.positions],
                )
            for table, values, key in (
                (paper_orders, (self._order_values(item) for item in state.orders), "order_id"),
                (paper_fills, (self._fill_values(item) for item in state.fills), "fill_id"),
                (
                    paper_equity_snapshots,
                    (self._snapshot_values(item) for item in state.snapshots),
                    "snapshot_id",
                ),
            ):
                for item in values:
                    connection.execute(
                        sqlite_insert(table)
                        .values(**item)
                        .on_conflict_do_nothing(index_elements=[key])
                    )

    def save_strategy_runs(self, runs: tuple[StrategyRunRecord, ...]) -> None:
        if not runs:
            return
        with self.engine.begin() as connection:
            connection.execute(
                paper_strategy_runs.insert(),
                [self._strategy_run_values(item) for item in runs],
            )

    def latest_strategy_run_batch(
        self,
        account_id: str,
        *,
        limit: int = 200,
    ) -> tuple[StrategyRunRecord, ...]:
        """Return the newest persisted batch of strategy runs for an account."""
        with self.engine.connect() as connection:
            rows = list(
                connection.execute(
                    sa.select(paper_strategy_runs)
                    .where(paper_strategy_runs.c.account_id == account_id)
                    .order_by(
                        paper_strategy_runs.c.decision_time.desc(),
                        paper_strategy_runs.c.instrument_id,
                    )
                    .limit(limit)
                ).mappings()
            )
        if not rows:
            return ()
        newest_batch = rows[0]["batch_id"]
        batch_rows = [row for row in rows if row["batch_id"] == newest_batch]
        return tuple(
            self._strategy_run(row)
            for row in sorted(batch_rows, key=lambda item: str(item["instrument_id"]))
        )

    def list_models(self) -> list[ModelRegistryRecord]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                sa.select(model_registry).order_by(model_registry.c.created_at.desc())
            ).mappings()
            return [_model_record(row) for row in rows]

    def get_model(self, model_id: str) -> ModelRegistryRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(model_registry).where(model_registry.c.model_id == model_id)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _model_record(row)

    def latest_approved_model(self) -> ModelRegistryRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(model_registry)
                    .where(model_registry.c.status == "APPROVED")
                    .order_by(model_registry.c.approved_at.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _model_record(row)

    def save_model(self, record: ModelRegistryRecord) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                sqlite_insert(model_registry)
                .values(
                    model_id=record.model_id,
                    strategy_id=record.strategy_id,
                    strategy_version=record.strategy_version,
                    feature_version=record.feature_version,
                    artifact_path=record.artifact_path,
                    metrics_json=record.metrics_json,
                    params_json=record.params_json,
                    status=record.status,
                    created_at=_utc(record.created_at),
                    updated_at=_utc(record.updated_at),
                    approved_at=None if record.approved_at is None else _utc(record.approved_at),
                    semantic_class=record.semantic_class,
                    evidence_class=record.evidence_class,
                    run_class=record.run_class,
                    manifest_schema=record.manifest_schema,
                    content_digest=record.content_digest,
                )
                .on_conflict_do_update(
                    index_elements=[model_registry.c.model_id],
                    set_={
                        "strategy_id": record.strategy_id,
                        "strategy_version": record.strategy_version,
                        "feature_version": record.feature_version,
                        "artifact_path": record.artifact_path,
                        "metrics_json": record.metrics_json,
                        "params_json": record.params_json,
                        "status": record.status,
                        "updated_at": _utc(record.updated_at),
                        "approved_at": (
                            None if record.approved_at is None else _utc(record.approved_at)
                        ),
                        "semantic_class": record.semantic_class,
                        "evidence_class": record.evidence_class,
                        "run_class": record.run_class,
                        "manifest_schema": record.manifest_schema,
                        "content_digest": record.content_digest,
                    },
                )
            )

    def list_experiments(self, limit: int = 50) -> list[ExperimentRecord]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                sa.select(research_experiments)
                .order_by(research_experiments.c.created_at.desc())
                .limit(limit)
            ).mappings()
            return [_experiment_record(row) for row in rows]

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(research_experiments).where(
                        research_experiments.c.experiment_id == experiment_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _experiment_record(row)

    def save_experiment(self, record: ExperimentRecord) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                research_experiments.insert().values(
                    experiment_id=record.experiment_id,
                    request_json=record.request_json,
                    summary_json=record.summary_json,
                    results_json=record.results_json,
                    created_at=_utc(record.created_at),
                    semantic_class=record.semantic_class,
                    evidence_class=record.evidence_class,
                    run_class=record.run_class,
                    manifest_schema=record.manifest_schema,
                    content_digest=record.content_digest,
                )
            )

    def get_legacy_ledger_seal(self, account_id: str) -> LegacyLedgerSealRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(paper_legacy_ledger_seals).where(
                        paper_legacy_ledger_seals.c.account_id == account_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return LegacyLedgerSealRecord(
            account_id=row["account_id"],
            source_revision=row["source_revision"],
            ledger_content_digest=row["ledger_content_digest"],
            seal_status=row["seal_status"],
            sealed_at=_utc(row["sealed_at"]),
        )

    def get_opening_import(self, source_account_id: str) -> OpeningImportRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(paper_opening_imports).where(
                        paper_opening_imports.c.source_account_id == source_account_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return OpeningImportRecord(
            import_id=row["import_id"],
            source_account_id=row["source_account_id"],
            source_ledger_seal_digest=row["source_ledger_seal_digest"],
            target_account_id=row["target_account_id"],
            reconciliation_digest=row["reconciliation_digest"],
            status=row["status"],
            created_at=_utc(row["created_at"]),
        )

    def record_opening_import(self, record: OpeningImportRecord) -> None:
        try:
            with self.engine.begin() as connection:
                seal_digest = connection.execute(
                    sa.select(paper_legacy_ledger_seals.c.ledger_content_digest).where(
                        paper_legacy_ledger_seals.c.account_id == record.source_account_id
                    )
                ).scalar_one_or_none()
                if seal_digest is None:
                    raise KeyError(record.source_account_id)
                if seal_digest != record.source_ledger_seal_digest:
                    raise ValueError(
                        "opening import seal digest does not match sealed ledger: "
                        f"{record.source_account_id}"
                    )
                connection.execute(
                    paper_opening_imports.insert().values(
                        import_id=record.import_id,
                        source_account_id=record.source_account_id,
                        source_ledger_seal_digest=record.source_ledger_seal_digest,
                        target_account_id=record.target_account_id,
                        reconciliation_digest=record.reconciliation_digest,
                        status=record.status,
                        created_at=_utc(record.created_at),
                    )
                )
        except IntegrityError as error:
            if self.get_opening_import(record.source_account_id) is not None:
                raise OpeningImportAlreadyExistsError(record.source_account_id) from error
            raise

    def get_daily_open(
        self,
        account_id: str,
        trading_date: date,
    ) -> dict[str, object] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(paper_daily_open).where(
                        paper_daily_open.c.account_id == account_id,
                        paper_daily_open.c.trading_date == trading_date,
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return {
            "cash": row["cash"],
            "positions_json": row["positions_json"],
        }

    def save_daily_open(
        self,
        *,
        account_id: str,
        trading_date: date,
        cash: str,
        positions_json: str,
        now: datetime,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                sqlite_insert(paper_daily_open)
                .values(
                    account_id=account_id,
                    trading_date=trading_date,
                    cash=cash,
                    positions_json=positions_json,
                    created_at=_utc(now),
                )
                .on_conflict_do_nothing(index_elements=["account_id", "trading_date"])
            )

    def runs_on_date(self, account_id: str, trading_date: date) -> tuple[StrategyRunRecord, ...]:
        from datetime import timedelta as _td
        from zoneinfo import ZoneInfo as _ZI

        shanghai = _ZI("Asia/Shanghai")
        start = datetime.combine(trading_date, datetime.min.time(), tzinfo=shanghai).astimezone(UTC)
        end = start + _td(days=1)
        with self.engine.connect() as connection:
            rows = connection.execute(
                sa.select(paper_strategy_runs)
                .where(
                    paper_strategy_runs.c.account_id == account_id,
                    paper_strategy_runs.c.decision_time >= start,
                    paper_strategy_runs.c.decision_time < end,
                )
                .order_by(paper_strategy_runs.c.decision_time)
            ).mappings()
            return tuple(self._strategy_run(row) for row in rows)

    @staticmethod
    def _strategy_run_values(item: StrategyRunRecord) -> dict[str, object]:
        return {
            "decision_id": item.decision_id,
            "batch_id": item.batch_id,
            "account_id": item.account_id,
            "instrument_id": item.instrument_id,
            "outcome": item.outcome,
            "proposed_side": item.proposed_side,
            "proposed_quantity": item.proposed_quantity,
            "risk_reason": item.risk_reason,
            "signal_json": item.signal_json,
            "advisory_checks_json": json.dumps(list(item.advisory_checks)),
            "order_json": item.order_json,
            "fill_json": item.fill_json,
            "decision_time": _utc(item.decision_time),
            "semantic_class": item.semantic_class,
            "evidence_class": item.evidence_class,
            "run_class": item.run_class,
            "manifest_schema": item.manifest_schema,
            "content_digest": item.content_digest,
        }

    @staticmethod
    def _strategy_run(row: RowMapping) -> StrategyRunRecord:
        return StrategyRunRecord(
            decision_id=row["decision_id"],
            batch_id=row["batch_id"],
            account_id=row["account_id"],
            instrument_id=row["instrument_id"],
            outcome=row["outcome"],
            proposed_side=row["proposed_side"],
            proposed_quantity=row["proposed_quantity"],
            risk_reason=row["risk_reason"],
            signal_json=row["signal_json"],
            advisory_checks=tuple(json.loads(row["advisory_checks_json"])),
            order_json=row["order_json"],
            fill_json=row["fill_json"],
            decision_time=_utc(row["decision_time"]),
            semantic_class=row["semantic_class"],
            evidence_class=row["evidence_class"],
            run_class=row["run_class"],
            manifest_schema=row["manifest_schema"],
            content_digest=row["content_digest"],
        )

    @staticmethod
    def _ensure_ledger_is_mutable(connection: sa.Connection, account_id: str) -> None:
        sealed_account_id = connection.execute(
            sa.select(paper_legacy_ledger_seals.c.account_id).where(
                paper_legacy_ledger_seals.c.account_id == account_id
            )
        ).scalar_one_or_none()
        if sealed_account_id is not None:
            raise LegacyLedgerSealedError(account_id)

    @staticmethod
    def _position_values(item: Position) -> dict[str, object]:
        return {
            "account_id": item.account_id,
            "instrument_id": str(item.instrument_id),
            "name": item.name,
            "quantity": item.quantity,
            "available_quantity": item.available_quantity,
            "average_cost": str(item.average_cost),
            "last_price": None if item.last_price is None else str(item.last_price),
            "marked_at": None if item.marked_at is None else _utc(item.marked_at),
        }

    @staticmethod
    def _order_values(item: PaperOrder) -> dict[str, object]:
        return {
            "order_id": item.order_id,
            "account_id": item.account_id,
            "idempotency_key": item.idempotency_key,
            "instrument_id": str(item.instrument_id),
            "side": item.side.value,
            "quantity": item.quantity,
            "status": item.status.value,
            "submitted_at": _utc(item.submitted_at),
            "updated_at": _utc(item.updated_at),
            "reject_reason": item.reject_reason,
        }

    @staticmethod
    def _fill_values(item: PaperFill) -> dict[str, object]:
        return {
            "fill_id": item.fill_id,
            "order_id": item.order_id,
            "account_id": item.account_id,
            "instrument_id": str(item.instrument_id),
            "side": item.side.value,
            "quantity": item.quantity,
            "price": str(item.price),
            "gross_amount": str(item.gross_amount),
            "commission": str(item.commission),
            "stamp_duty": str(item.stamp_duty),
            "transfer_fee": str(item.transfer_fee),
            "occurred_at": _utc(item.occurred_at),
        }

    @staticmethod
    def _snapshot_values(item: PortfolioSnapshot) -> dict[str, object]:
        return {
            "snapshot_id": item.snapshot_id,
            "account_id": item.account_id,
            "cash": str(item.cash),
            "market_value": str(item.market_value),
            "total_equity": str(item.total_equity),
            "initial_equity": str(item.initial_equity),
            "total_pnl": str(item.total_pnl),
            "total_pnl_percent": (
                None if item.total_pnl_percent is None else str(item.total_pnl_percent)
            ),
            "as_of": _utc(item.as_of),
        }

    @staticmethod
    def _position(row: RowMapping) -> Position:
        return Position(
            account_id=row["account_id"],
            instrument_id=InstrumentId.parse(row["instrument_id"]),
            name=row["name"],
            quantity=row["quantity"],
            available_quantity=row["available_quantity"],
            average_cost=_decimal(row["average_cost"]),
            last_price=None if row["last_price"] is None else _decimal(row["last_price"]),
            marked_at=None if row["marked_at"] is None else _utc(row["marked_at"]),
        )

    @staticmethod
    def _order(row: RowMapping) -> PaperOrder:
        return PaperOrder(
            order_id=row["order_id"],
            account_id=row["account_id"],
            idempotency_key=row["idempotency_key"],
            instrument_id=InstrumentId.parse(row["instrument_id"]),
            side=OrderSide(row["side"]),
            quantity=row["quantity"],
            status=OrderStatus(row["status"]),
            submitted_at=_utc(row["submitted_at"]),
            updated_at=_utc(row["updated_at"]),
            reject_reason=row["reject_reason"],
        )

    @staticmethod
    def _fill(row: RowMapping) -> PaperFill:
        return PaperFill(
            fill_id=row["fill_id"],
            order_id=row["order_id"],
            account_id=row["account_id"],
            instrument_id=InstrumentId.parse(row["instrument_id"]),
            side=OrderSide(row["side"]),
            quantity=row["quantity"],
            price=_decimal(row["price"]),
            gross_amount=_decimal(row["gross_amount"]),
            commission=_decimal(row["commission"]),
            stamp_duty=_decimal(row["stamp_duty"]),
            transfer_fee=_decimal(row["transfer_fee"]),
            occurred_at=_utc(row["occurred_at"]),
        )

    @staticmethod
    def _snapshot(row: RowMapping) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            snapshot_id=row["snapshot_id"],
            account_id=row["account_id"],
            cash=_decimal(row["cash"]),
            market_value=_decimal(row["market_value"]),
            total_equity=_decimal(row["total_equity"]),
            initial_equity=_decimal(row["initial_equity"]),
            total_pnl=_decimal(row["total_pnl"]),
            total_pnl_percent=(
                None if row["total_pnl_percent"] is None else _decimal(row["total_pnl_percent"])
            ),
            as_of=_utc(row["as_of"]),
        )

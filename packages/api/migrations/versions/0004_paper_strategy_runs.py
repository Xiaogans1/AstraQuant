"""Persist auditable strategy runs so the workspace survives refresh."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_paper_strategy_runs"
down_revision: str | Sequence[str] | None = "0003_paper_portfolio"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_strategy_runs",
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
    )
    op.create_index(
        "ix_paper_strategy_runs_account_time",
        "paper_strategy_runs",
        ["account_id", "decision_time"],
    )
    op.create_index(
        "ix_paper_strategy_runs_batch",
        "paper_strategy_runs",
        ["batch_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_paper_strategy_runs_batch", table_name="paper_strategy_runs")
    op.drop_index("ix_paper_strategy_runs_account_time", table_name="paper_strategy_runs")
    op.drop_table("paper_strategy_runs")

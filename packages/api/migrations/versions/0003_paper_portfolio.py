"""Create the local Paper portfolio ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_paper_portfolio"
down_revision: str | Sequence[str] | None = "0002_data_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_accounts",
        sa.Column("account_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("initial_cash", sa.String(64), nullable=False),
        sa.Column("initial_equity", sa.String(64), nullable=False),
        sa.Column("cash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('PAPER', 'MIRROR')", name="ck_paper_accounts_mode"),
    )
    op.create_index("ix_paper_accounts_created", "paper_accounts", ["created_at"])
    op.create_table(
        "paper_positions",
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.account_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("available_quantity", sa.Integer(), nullable=False),
        sa.Column("average_cost", sa.String(64), nullable=False),
        sa.Column("last_price", sa.String(64)),
        sa.Column("marked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("account_id", "instrument_id"),
        sa.CheckConstraint("quantity > 0", name="ck_paper_positions_quantity"),
        sa.CheckConstraint(
            "available_quantity >= 0 AND available_quantity <= quantity",
            name="ck_paper_positions_available",
        ),
    )
    op.create_table(
        "paper_orders",
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
    )
    op.create_index(
        "ix_paper_orders_account_submitted",
        "paper_orders",
        ["account_id", "submitted_at"],
    )
    op.create_table(
        "paper_fills",
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
    )
    op.create_index(
        "ix_paper_fills_account_occurred",
        "paper_fills",
        ["account_id", "occurred_at"],
    )
    op.create_table(
        "paper_equity_snapshots",
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
    )
    op.create_index(
        "ix_paper_equity_account_as_of",
        "paper_equity_snapshots",
        ["account_id", "as_of"],
    )


def downgrade() -> None:
    op.drop_index("ix_paper_equity_account_as_of", table_name="paper_equity_snapshots")
    op.drop_table("paper_equity_snapshots")
    op.drop_index("ix_paper_fills_account_occurred", table_name="paper_fills")
    op.drop_table("paper_fills")
    op.drop_index("ix_paper_orders_account_submitted", table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_table("paper_positions")
    op.drop_index("ix_paper_accounts_created", table_name="paper_accounts")
    op.drop_table("paper_accounts")


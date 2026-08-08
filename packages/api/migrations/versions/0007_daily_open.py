"""Store the daily opening account state for same-baseline replay."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_daily_open"
down_revision: str | Sequence[str] | None = "0006_model_params"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_daily_open",
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("cash", sa.String(64), nullable=False),
        sa.Column("positions_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("account_id", "trading_date"),
    )


def downgrade() -> None:
    op.drop_table("paper_daily_open")

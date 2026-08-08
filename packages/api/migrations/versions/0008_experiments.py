"""Persist replay experiments for later review and reporting."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_experiments"
down_revision: str | Sequence[str] | None = "0007_daily_open"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_experiments",
        sa.Column("experiment_id", sa.String(36), primary_key=True),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("results_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_research_experiments_created",
        "research_experiments",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_research_experiments_created", table_name="research_experiments")
    op.drop_table("research_experiments")

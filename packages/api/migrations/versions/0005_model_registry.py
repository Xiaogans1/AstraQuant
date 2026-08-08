"""Model registry for approved research artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_model_registry"
down_revision: str | Sequence[str] | None = "0004_paper_strategy_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("model_id", sa.String(64), primary_key=True),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("artifact_path", sa.String(400), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_model_registry_status", "model_registry", ["status"])


def downgrade() -> None:
    op.drop_index("ix_model_registry_status", table_name="model_registry")
    op.drop_table("model_registry")

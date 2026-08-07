"""Add inference parameters to the model registry."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_model_params"
down_revision: str | Sequence[str] | None = "0005_model_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_registry",
        sa.Column(
            "params_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("model_registry", "params_json")

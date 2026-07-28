"""Create the local market-data catalog."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_data_catalog"
down_revision: str | Sequence[str] | None = "0001_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_datasets",
        sa.Column("dataset_id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("asset_class", sa.String(32), nullable=False),
        sa.Column("frequency", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "data_snapshots",
        sa.Column("snapshot_id", sa.String(64), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(100),
            sa.ForeignKey("data_datasets.dataset_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("min_event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_id", sa.String(100), nullable=False),
        sa.Column("manifest_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('STAGED', 'PUBLISHED', 'REJECTED')",
            name="ck_data_snapshots_status",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "snapshot_id",
            name="uq_data_snapshots_dataset_snapshot",
        ),
    )
    op.create_index(
        "ix_data_snapshots_dataset_created",
        "data_snapshots",
        ["dataset_id", "created_at"],
    )
    op.create_table(
        "data_quality_issues",
        sa.Column(
            "snapshot_id",
            sa.String(64),
            sa.ForeignKey("data_snapshots.snapshot_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("samples_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id", "code"),
    )


def downgrade() -> None:
    op.drop_table("data_quality_issues")
    op.drop_index(
        "ix_data_snapshots_dataset_created",
        table_name="data_snapshots",
    )
    op.drop_table("data_snapshots")
    op.drop_table("data_datasets")

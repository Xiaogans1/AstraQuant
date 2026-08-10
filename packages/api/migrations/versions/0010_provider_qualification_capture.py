"""Add append-only provider qualification and capture index tables."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_provider_qualification_capture"
down_revision: str | Sequence[str] | None = "0009_v3_legacy_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_identities",
        sa.Column("identity_digest", sa.String(71), primary_key=True),
        sa.Column("identity_json", sa.Text(), nullable=False),
        sa.Column("vendor", sa.String(64), nullable=False),
        sa.Column("endpoint", sa.String(200), nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_provider_identities_vendor_capability",
        "provider_identities",
        ["vendor", "capability"],
    )
    op.create_table(
        "provider_qualification_reports",
        sa.Column("report_digest", sa.String(71), primary_key=True),
        sa.Column(
            "identity_digest",
            sa.String(71),
            sa.ForeignKey(
                "provider_identities.identity_digest",
                name="fk_provider_reports_identity",
            ),
            nullable=False,
        ),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("approvable", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "approvable IN (0, 1)",
            name="ck_provider_reports_approvable",
        ),
    )
    op.create_index(
        "ix_provider_reports_identity",
        "provider_qualification_reports",
        ["identity_digest", "observed_at"],
    )
    op.create_table(
        "provider_approvals",
        sa.Column("approval_id", sa.String(71), primary_key=True),
        sa.Column(
            "identity_digest",
            sa.String(71),
            sa.ForeignKey(
                "provider_identities.identity_digest",
                name="fk_provider_approvals_identity",
            ),
            nullable=False,
        ),
        sa.Column(
            "report_digest",
            sa.String(71),
            sa.ForeignKey(
                "provider_qualification_reports.report_digest",
                name="fk_provider_approvals_report",
            ),
            nullable=False,
        ),
        sa.Column("approval_json", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("policy_version", sa.String(200), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_provider_approvals_identity_effective",
        "provider_approvals",
        ["identity_digest", "effective_at"],
    )
    op.create_table(
        "provider_revocations",
        sa.Column("revocation_id", sa.String(71), primary_key=True),
        sa.Column(
            "approval_id",
            sa.String(71),
            sa.ForeignKey(
                "provider_approvals.approval_id",
                name="fk_provider_revocations_approval",
            ),
            nullable=False,
        ),
        sa.Column("revocation_json", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("reason_digest", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_provider_revocations_approval_effective",
        "provider_revocations",
        ["approval_id", "effective_at"],
    )
    op.create_table(
        "capture_index",
        sa.Column("capture_id", sa.String(71), primary_key=True),
        sa.Column(
            "identity_digest",
            sa.String(71),
            sa.ForeignKey(
                "provider_identities.identity_digest",
                name="fk_capture_index_identity",
            ),
            nullable=False,
        ),
        sa.Column(
            "report_digest",
            sa.String(71),
            sa.ForeignKey(
                "provider_qualification_reports.report_digest",
                name="fk_capture_index_report",
            ),
            nullable=False,
        ),
        sa.Column(
            "approval_id",
            sa.String(71),
            sa.ForeignKey(
                "provider_approvals.approval_id",
                name="fk_capture_index_approval",
            ),
            nullable=False,
        ),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("response_digest", sa.String(71), nullable=False),
        sa.Column("object_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("object_path", name="uq_capture_index_object_path"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'SEALED', 'QUARANTINED')",
            name="ck_capture_index_status",
        ),
    )
    op.create_index(
        "ix_capture_index_identity_captured",
        "capture_index",
        ["identity_digest", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_capture_index_identity_captured", table_name="capture_index")
    op.drop_table("capture_index")
    op.drop_index(
        "ix_provider_revocations_approval_effective",
        table_name="provider_revocations",
    )
    op.drop_table("provider_revocations")
    op.drop_index(
        "ix_provider_approvals_identity_effective",
        table_name="provider_approvals",
    )
    op.drop_table("provider_approvals")
    op.drop_index(
        "ix_provider_reports_identity",
        table_name="provider_qualification_reports",
    )
    op.drop_table("provider_qualification_reports")
    op.drop_index(
        "ix_provider_identities_vendor_capability",
        table_name="provider_identities",
    )
    op.drop_table("provider_identities")

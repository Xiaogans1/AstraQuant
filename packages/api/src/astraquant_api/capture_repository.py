"""Append-only provider qualification and capture index repository."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy import Engine, RowMapping

from astraquant_data.provider_identity import (
    ProviderCapability,
    ProviderIdentity,
    ProviderTransport,
)
from astraquant_data.provider_qualification import (
    CapabilityResult,
    CheckStatus,
    ProbeEvidence,
    ProviderApproval,
    ProviderQualificationTimeline,
    ProviderRevocation,
    QualificationCheck,
    QualificationCoverage,
    QualificationReport,
    RevocationKind,
)

metadata = sa.MetaData()

provider_identities = sa.Table(
    "provider_identities",
    metadata,
    sa.Column("identity_digest", sa.String(71), primary_key=True),
    sa.Column("identity_json", sa.Text(), nullable=False),
    sa.Column("vendor", sa.String(64), nullable=False),
    sa.Column("endpoint", sa.String(200), nullable=False),
    sa.Column("capability", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_provider_identities_vendor_capability", "vendor", "capability"),
)

provider_qualification_reports = sa.Table(
    "provider_qualification_reports",
    metadata,
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
    sa.Index("ix_provider_reports_identity", "identity_digest", "observed_at"),
)

provider_approvals = sa.Table(
    "provider_approvals",
    metadata,
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
    sa.Index("ix_provider_approvals_identity_effective", "identity_digest", "effective_at"),
)

provider_revocations = sa.Table(
    "provider_revocations",
    metadata,
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
    sa.Index("ix_provider_revocations_approval_effective", "approval_id", "effective_at"),
)

capture_index = sa.Table(
    "capture_index",
    metadata,
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
    sa.Index("ix_capture_index_identity_captured", "identity_digest", "captured_at"),
)


class QualificationConflictError(RuntimeError):
    """An immutable record already exists with different canonical content."""


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _identity_from_dict(value: dict[str, object]) -> ProviderIdentity:
    return ProviderIdentity(
        vendor=str(value["vendor"]),
        product=str(value["product"]),
        endpoint=str(value["endpoint"]),
        capability=ProviderCapability(str(value["capability"])),
        interface=str(value["interface"]),
        interface_build=str(value["interface_build"]),
        transport=ProviderTransport(str(value["transport"])),
        permission_tier=str(value["permission_tier"]),
        schema_fingerprint=str(value["schema_fingerprint"]),
    )


def _report_from_json(payload: str) -> QualificationReport:
    value = json.loads(payload)
    identity = _identity_from_dict(value["identity"])
    coverage = value["coverage"]
    return QualificationReport(
        identity=identity,
        probes=tuple(
            ProbeEvidence(
                request_digest=item["request_digest"],
                raw_response_digest=item["raw_response_digest"],
                observed_at=datetime.fromisoformat(item["observed_at"]),
            )
            for item in value["probes"]
        ),
        coverage=QualificationCoverage(
            start=date.fromisoformat(coverage["start"]),
            end=date.fromisoformat(coverage["end"]),
            instruments=tuple(coverage["instruments"]),
            delisted_instruments=tuple(coverage["delisted_instruments"]),
        ),
        results=tuple(
            CapabilityResult(
                check=QualificationCheck(item["check"]),
                status=CheckStatus(item["status"]),
                evidence_digest=item["evidence_digest"],
            )
            for item in value["results"]
        ),
        adjust_modes=tuple(value["adjust_modes"]),
        units=tuple(value["units"]),
        observed_at=datetime.fromisoformat(value["observed_at"]),
        schema_version=value["schema_version"],
    )


def _approval_from_row(row: RowMapping) -> ProviderApproval:
    return ProviderApproval(
        identity_digest=row["identity_digest"],
        report_digest=row["report_digest"],
        reviewer=row["reviewer"],
        policy_version=row["policy_version"],
        effective_at=_utc(row["effective_at"]),
    )


def _revocation_from_row(row: RowMapping) -> ProviderRevocation:
    return ProviderRevocation(
        kind=RevocationKind(row["kind"]),
        effective_at=_utc(row["effective_at"]),
        reviewer=row["reviewer"],
        reason_digest=row["reason_digest"],
    )


class QualificationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _compare_or_insert(
        connection: sa.Connection,
        *,
        table: sa.Table,
        key_column: sa.Column[str],
        key: str,
        body_column: sa.Column[str],
        body: str,
        values: dict[str, object],
        label: str,
    ) -> None:
        existing = connection.execute(
            sa.select(body_column).where(key_column == key)
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(table.insert().values(**values))
            return
        if existing != body:
            raise QualificationConflictError(f"{label} immutable content conflicts")

    def append_report(self, report: QualificationReport) -> str:
        identity_body = _json(report.identity.to_dict())
        report_body = _json(report.to_dict())
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._compare_or_insert(
                connection,
                table=provider_identities,
                key_column=provider_identities.c.identity_digest,
                key=report.identity.identity_digest,
                body_column=provider_identities.c.identity_json,
                body=identity_body,
                values={
                    "identity_digest": report.identity.identity_digest,
                    "identity_json": identity_body,
                    "vendor": report.identity.vendor,
                    "endpoint": report.identity.endpoint,
                    "capability": report.identity.capability.value,
                    "created_at": now,
                },
                label="identity",
            )
            self._compare_or_insert(
                connection,
                table=provider_qualification_reports,
                key_column=provider_qualification_reports.c.report_digest,
                key=report.report_digest,
                body_column=provider_qualification_reports.c.report_json,
                body=report_body,
                values={
                    "report_digest": report.report_digest,
                    "identity_digest": report.identity.identity_digest,
                    "report_json": report_body,
                    "approvable": report.approvable,
                    "observed_at": report.observed_at,
                    "created_at": now,
                },
                label="report",
            )
        return report.report_digest

    def append_approval(self, approval: ProviderApproval) -> str:
        body = _json(approval.to_dict())
        with self._engine.begin() as connection:
            report_identity = connection.execute(
                sa.select(provider_qualification_reports.c.identity_digest).where(
                    provider_qualification_reports.c.report_digest == approval.report_digest
                )
            ).scalar_one_or_none()
            if report_identity != approval.identity_digest:
                raise QualificationConflictError("approval identity/report binding conflicts")
            self._compare_or_insert(
                connection,
                table=provider_approvals,
                key_column=provider_approvals.c.approval_id,
                key=approval.approval_id,
                body_column=provider_approvals.c.approval_json,
                body=body,
                values={
                    "approval_id": approval.approval_id,
                    "identity_digest": approval.identity_digest,
                    "report_digest": approval.report_digest,
                    "approval_json": body,
                    "reviewer": approval.reviewer,
                    "policy_version": approval.policy_version,
                    "effective_at": approval.effective_at,
                    "created_at": datetime.now(UTC),
                },
                label="approval",
            )
        return approval.approval_id

    def append_revocation(
        self,
        approval_id: str,
        revocation: ProviderRevocation,
    ) -> str:
        body = _json({"approval_id": approval_id, **revocation.to_dict()})
        with self._engine.begin() as connection:
            approval_exists = connection.scalar(
                sa.select(sa.func.count())
                .select_from(provider_approvals)
                .where(provider_approvals.c.approval_id == approval_id)
            )
            if approval_exists != 1:
                raise QualificationConflictError("revocation approval does not exist")
            self._compare_or_insert(
                connection,
                table=provider_revocations,
                key_column=provider_revocations.c.revocation_id,
                key=revocation.revocation_id,
                body_column=provider_revocations.c.revocation_json,
                body=body,
                values={
                    "revocation_id": revocation.revocation_id,
                    "approval_id": approval_id,
                    "revocation_json": body,
                    "kind": revocation.kind.value,
                    "effective_at": revocation.effective_at,
                    "reviewer": revocation.reviewer,
                    "reason_digest": revocation.reason_digest,
                    "created_at": datetime.now(UTC),
                },
                label="revocation",
            )
        return revocation.revocation_id

    def is_approved_for_capture(
        self,
        identity: ProviderIdentity,
        *,
        captured_at: datetime,
    ) -> bool:
        with self._engine.connect() as connection:
            approvals = connection.execute(
                sa.select(provider_approvals).where(
                    provider_approvals.c.identity_digest == identity.identity_digest
                )
            ).mappings()
            for approval_row in approvals:
                report_payload = connection.scalar(
                    sa.select(provider_qualification_reports.c.report_json).where(
                        provider_qualification_reports.c.report_digest
                        == approval_row["report_digest"]
                    )
                )
                if not isinstance(report_payload, str):
                    continue
                report = _report_from_json(report_payload)
                approval = _approval_from_row(approval_row)
                revocation_rows = connection.execute(
                    sa.select(provider_revocations).where(
                        provider_revocations.c.approval_id == approval.approval_id
                    )
                ).mappings()
                timeline = ProviderQualificationTimeline(
                    identity=report.identity,
                    report=report,
                    approval=approval,
                    revocations=tuple(_revocation_from_row(row) for row in revocation_rows),
                )
                if timeline.is_approved_for(identity, captured_at=captured_at):
                    return True
        return False

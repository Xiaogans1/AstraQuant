"""Single-writer service for provider qualification state transitions."""

from __future__ import annotations

from astraquant_api.capture_repository import (
    QualificationRepository,
    qualification_report_from_dict,
)
from astraquant_api.provider_qualification_schemas import (
    ProviderApprovalCommand,
    ProviderRevocationCommand,
    QualificationCommandResponse,
    QualificationReportCommand,
)
from astraquant_data.provider_qualification import (
    ProviderQualificationTimeline,
    ProviderRevocation,
)


class QualificationNotFoundError(LookupError):
    pass


class ProviderQualificationService:
    def __init__(self, repository: QualificationRepository) -> None:
        self._repository = repository

    def submit_report(
        self,
        command: QualificationReportCommand,
    ) -> QualificationCommandResponse:
        report = qualification_report_from_dict(command.report)
        report_digest = self._repository.append_report(report)
        return QualificationCommandResponse(
            artifact_id=report_digest,
            state="UNQUALIFIED",
            identity_digest=report.identity.identity_digest,
            report_digest=report_digest,
        )

    def approve(
        self,
        command: ProviderApprovalCommand,
    ) -> QualificationCommandResponse:
        report = self._repository.get_report(command.report_digest)
        if report is None:
            raise QualificationNotFoundError("qualification report not found")
        if report.identity.identity_digest != command.identity_digest:
            raise QualificationNotFoundError("provider identity not found for report")
        timeline = ProviderQualificationTimeline(
            identity=report.identity,
            report=report,
        ).approve(
            reviewer=command.reviewer,
            policy_version=command.policy_version,
            effective_at=command.effective_at,
        )
        assert timeline.approval is not None
        approval_id = self._repository.append_approval(timeline.approval)
        return QualificationCommandResponse(
            artifact_id=approval_id,
            state=timeline.state.value,
            identity_digest=command.identity_digest,
            report_digest=command.report_digest,
        )

    def revoke(
        self,
        command: ProviderRevocationCommand,
    ) -> QualificationCommandResponse:
        timeline = self._repository.get_timeline_for_approval(command.approval_id)
        if timeline is None:
            raise QualificationNotFoundError("provider approval not found")
        candidate = ProviderRevocation(
            kind=command.kind,
            effective_at=command.effective_at,
            reviewer=command.reviewer,
            reason_digest=command.reason_digest,
        )
        if any(
            existing.revocation_id == candidate.revocation_id for existing in timeline.revocations
        ):
            return QualificationCommandResponse(
                artifact_id=candidate.revocation_id,
                state=timeline.state.value,
                identity_digest=timeline.identity.identity_digest,
                report_digest=timeline.report.report_digest,
            )
        revoked = timeline.revoke(
            kind=command.kind,
            effective_at=command.effective_at,
            reviewer=command.reviewer,
            reason_digest=command.reason_digest,
        )
        revocation = revoked.revocations[-1]
        revocation_id = self._repository.append_revocation(
            command.approval_id,
            revocation,
        )
        return QualificationCommandResponse(
            artifact_id=revocation_id,
            state=revoked.state.value,
            identity_digest=timeline.identity.identity_digest,
            report_digest=timeline.report.report_digest,
        )

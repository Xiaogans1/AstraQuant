from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from astraquant_api.capture_repository import (
    QualificationConflictError,
    QualificationRepository,
    provider_approvals,
    provider_identities,
    provider_qualification_reports,
    provider_revocations,
)
from astraquant_api.database import create_database, migrate_database
from astraquant_data.provider_identity import (
    ProviderCapability,
    ProviderIdentity,
    ProviderTransport,
)
from astraquant_data.provider_qualification import (
    CapabilityResult,
    CheckStatus,
    ProbeEvidence,
    ProviderQualificationTimeline,
    QualificationCheck,
    QualificationCoverage,
    QualificationReport,
    RevocationKind,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _identity() -> ProviderIdentity:
    return ProviderIdentity(
        vendor="eastmoney",
        product="eastmoney-terminal",
        endpoint="market.daily-bars",
        capability=ProviderCapability.DAILY_BARS,
        interface="gm_python_sdk",
        interface_build="3.0.176",
        transport=ProviderTransport.NDJSON_BRIDGE,
        permission_tier="level1-history",
        schema_fingerprint=_digest("1"),
    )


def _report() -> QualificationReport:
    return QualificationReport(
        identity=_identity(),
        probes=(
            ProbeEvidence(
                request_digest=_digest("2"),
                raw_response_digest=_digest("3"),
                observed_at=NOW,
            ),
        ),
        coverage=QualificationCoverage(
            start=date(2020, 1, 1),
            end=date(2026, 8, 8),
            instruments=("600000.SSE",),
            delisted_instruments=("600001.SSE",),
        ),
        results=tuple(
            CapabilityResult(
                check=check,
                status=CheckStatus.PASS,
                evidence_digest=_digest(format(index + 4, "x")),
            )
            for index, check in enumerate(QualificationCheck)
        ),
        adjust_modes=("NONE",),
        units=("price=CNY", "volume=share"),
        observed_at=NOW,
    )


def _repository(tmp_path: Path) -> tuple[QualificationRepository, sa.Engine]:
    database_url = f"sqlite:///{tmp_path / 'qualification.sqlite3'}"
    migrate_database(database_url)
    engine = create_database(database_url)
    return QualificationRepository(engine), engine


def test_report_append_is_idempotent_and_never_auto_approves(tmp_path: Path) -> None:
    repository, engine = _repository(tmp_path)
    report = _report()

    assert repository.append_report(report) == report.report_digest
    assert repository.append_report(report) == report.report_digest
    assert repository.is_approved_for_capture(report.identity, captured_at=NOW) is False

    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(provider_identities)) == 1
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(provider_qualification_reports)
            )
            == 1
        )
        assert connection.scalar(sa.select(sa.func.count()).select_from(provider_approvals)) == 0


def test_same_digest_with_different_body_is_rejected(tmp_path: Path) -> None:
    repository, engine = _repository(tmp_path)
    report = _report()
    repository.append_report(report)
    with engine.begin() as connection:
        connection.execute(
            provider_qualification_reports.update()
            .where(provider_qualification_reports.c.report_digest == report.report_digest)
            .values(report_json='{"tampered":true}')
        )

    with pytest.raises(QualificationConflictError, match="report"):
        repository.append_report(report)


def test_approval_and_revocation_use_capture_time_semantics(tmp_path: Path) -> None:
    repository, engine = _repository(tmp_path)
    report = _report()
    repository.append_report(report)
    approved_timeline = ProviderQualificationTimeline(
        identity=report.identity,
        report=report,
    ).approve(
        reviewer="reviewer-1",
        policy_version="provider-policy/v1",
        effective_at=NOW,
    )
    assert approved_timeline.approval is not None
    repository.append_approval(approved_timeline.approval)

    assert repository.is_approved_for_capture(report.identity, captured_at=NOW)
    revoked_at = NOW + timedelta(days=2)
    revoked_timeline = approved_timeline.revoke(
        kind=RevocationKind.REVOKED,
        effective_at=revoked_at,
        reviewer="reviewer-2",
        reason_digest=_digest("f"),
    )
    repository.append_revocation(
        approved_timeline.approval.approval_id,
        revoked_timeline.revocations[-1],
    )

    assert repository.is_approved_for_capture(
        report.identity,
        captured_at=NOW + timedelta(days=1),
    )
    assert not repository.is_approved_for_capture(
        report.identity,
        captured_at=revoked_at,
    )
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(provider_approvals)) == 1
        assert connection.scalar(sa.select(sa.func.count()).select_from(provider_revocations)) == 1


def test_retroactive_compromise_invalidates_pre_effective_capture(tmp_path: Path) -> None:
    repository, _engine = _repository(tmp_path)
    report = _report()
    repository.append_report(report)
    timeline = ProviderQualificationTimeline(identity=report.identity, report=report).approve(
        reviewer="reviewer-1",
        policy_version="provider-policy/v1",
        effective_at=NOW,
    )
    assert timeline.approval is not None
    repository.append_approval(timeline.approval)
    compromised = timeline.revoke(
        kind=RevocationKind.RETROACTIVE_COMPROMISE,
        effective_at=NOW + timedelta(days=10),
        reviewer="security-reviewer",
        reason_digest=_digest("f"),
    )
    repository.append_revocation(
        timeline.approval.approval_id,
        compromised.revocations[-1],
    )

    assert not repository.is_approved_for_capture(
        report.identity,
        captured_at=NOW + timedelta(days=1),
    )

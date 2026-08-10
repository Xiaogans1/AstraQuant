from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from astraquant_api.capture_repository import QualificationRepository
from astraquant_api.database import create_database, migrate_database
from astraquant_api.provider_qualification_routes import (
    build_provider_qualification_router,
)
from astraquant_api.provider_qualification_service import (
    ProviderQualificationService,
)
from astraquant_data.provider_identity import (
    ProviderCapability,
    ProviderIdentity,
    ProviderTransport,
)
from astraquant_data.provider_qualification import (
    CapabilityResult,
    CheckStatus,
    ProbeEvidence,
    QualificationCheck,
    QualificationCoverage,
    QualificationReport,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)
TOKEN = "local-session-token"


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _report(status: CheckStatus = CheckStatus.PASS) -> QualificationReport:
    identity = ProviderIdentity(
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
    return QualificationReport(
        identity=identity,
        probes=(ProbeEvidence(_digest("2"), _digest("3"), NOW),),
        coverage=QualificationCoverage(
            start=date(2020, 1, 1),
            end=date(2026, 8, 8),
            instruments=("600000.SSE",),
            delisted_instruments=("600001.SSE",),
        ),
        results=tuple(
            CapabilityResult(check, status, _digest(format(index + 4, "x")))
            for index, check in enumerate(QualificationCheck)
        ),
        adjust_modes=("NONE",),
        units=("price=CNY", "volume=share"),
        observed_at=NOW,
    )


def _client(tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'routes.sqlite3'}"
    migrate_database(database_url)
    repository = QualificationRepository(create_database(database_url))
    service = ProviderQualificationService(repository)
    app = FastAPI()

    def require_auth(authorization: str | None = Header(None)) -> None:
        if authorization != f"Bearer {TOKEN}":
            raise HTTPException(status_code=401, detail="unauthorized")

    app.include_router(build_provider_qualification_router(service, Depends(require_auth)))
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_report_submission_is_authenticated_and_remains_unqualified(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    report = _report()

    assert (
        client.post(
            "/v1/provider-qualifications/reports",
            json={"report": report.to_dict()},
        ).status_code
        == 401
    )
    response = client.post(
        "/v1/provider-qualifications/reports",
        headers=_headers(),
        json={"report": report.to_dict()},
    )

    assert response.status_code == 200
    assert response.json() == {
        "artifact_id": report.report_digest,
        "state": "UNQUALIFIED",
        "identity_digest": report.identity.identity_digest,
        "report_digest": report.report_digest,
    }


def test_authenticated_approval_and_revocation_are_idempotent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    report = _report()
    client.post(
        "/v1/provider-qualifications/reports",
        headers=_headers(),
        json={"report": report.to_dict()},
    )
    approval_command = {
        "identity_digest": report.identity.identity_digest,
        "report_digest": report.report_digest,
        "reviewer": "reviewer-1",
        "policy_version": "provider-policy/v1",
        "effective_at": NOW.isoformat(),
    }

    first = client.post(
        "/v1/provider-qualifications/approvals",
        headers=_headers(),
        json=approval_command,
    )
    second = client.post(
        "/v1/provider-qualifications/approvals",
        headers=_headers(),
        json=approval_command,
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()

    revoke_command = {
        "approval_id": first.json()["artifact_id"],
        "kind": "REVOKED",
        "reviewer": "reviewer-2",
        "reason_digest": _digest("f"),
        "effective_at": (NOW + timedelta(days=1)).isoformat(),
    }
    revoked = client.post(
        "/v1/provider-qualifications/revocations",
        headers=_headers(),
        json=revoke_command,
    )
    repeated = client.post(
        "/v1/provider-qualifications/revocations",
        headers=_headers(),
        json=revoke_command,
    )
    assert revoked.status_code == repeated.status_code == 200
    assert revoked.json() == repeated.json()
    assert revoked.json()["state"] == "REVOKED"


def test_non_approvable_report_is_rejected_at_approval_not_submission(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    report = _report(CheckStatus.FAIL)
    submitted = client.post(
        "/v1/provider-qualifications/reports",
        headers=_headers(),
        json={"report": report.to_dict()},
    )
    assert submitted.status_code == 200

    approved = client.post(
        "/v1/provider-qualifications/approvals",
        headers=_headers(),
        json={
            "identity_digest": report.identity.identity_digest,
            "report_digest": report.report_digest,
            "reviewer": "reviewer-1",
            "policy_version": "provider-policy/v1",
            "effective_at": NOW.isoformat(),
        },
    )
    assert approved.status_code == 422
    assert "not approvable" in approved.json()["detail"]

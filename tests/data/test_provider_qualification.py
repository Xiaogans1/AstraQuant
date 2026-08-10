from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

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
    QualificationError,
    QualificationReport,
    QualificationState,
    RevocationKind,
)

NOW = datetime(2026, 8, 10, 1, 2, 3, tzinfo=UTC)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _identity(**changes: object) -> ProviderIdentity:
    values: dict[str, object] = {
        "vendor": "eastmoney",
        "product": "eastmoney-terminal",
        "endpoint": "market.daily-bars",
        "capability": ProviderCapability.DAILY_BARS,
        "interface": "gm_python_sdk",
        "interface_build": "3.0.176",
        "transport": ProviderTransport.NDJSON_BRIDGE,
        "permission_tier": "level1-history",
        "schema_fingerprint": _digest("1"),
    }
    values.update(changes)
    return ProviderIdentity(**values)  # type: ignore[arg-type]


def test_eastmoney_provider_identity_separates_vendor_interface_and_transport() -> None:
    identity = _identity()

    assert identity.vendor == "eastmoney"
    assert identity.interface == "gm_python_sdk"
    assert identity.transport is ProviderTransport.NDJSON_BRIDGE
    assert identity.endpoint == "market.daily-bars"
    assert identity.capability is ProviderCapability.DAILY_BARS
    assert identity.identity_digest.startswith("sha256:")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("vendor", "Eastmoney/GM"),
        ("vendor", " eastmoney"),
        ("interface", "GM Python SDK"),
        ("permission_tier", ""),
        ("product", " eastmoney-terminal"),
        ("endpoint", ""),
        ("interface_build", "3.0.176 "),
        ("schema_fingerprint", "sha256:not-a-digest"),
        ("schema_fingerprint", f"sha256:{'0' * 64}"),
    ],
)
def test_provider_identity_rejects_noncanonical_or_incomplete_fields(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        _identity(**{field: value})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda identity: replace(identity, endpoint="market.minute-bars"),
        lambda identity: replace(
            identity,
            capability=ProviderCapability.MINUTE_BARS,
        ),
        lambda identity: replace(identity, interface_build="3.0.177"),
        lambda identity: replace(identity, permission_tier="level2-history"),
        lambda identity: replace(identity, schema_fingerprint=_digest("2")),
    ],
)
def test_provider_identity_digest_changes_for_every_qualification_boundary(
    mutate: Callable[[ProviderIdentity], ProviderIdentity],
) -> None:
    identity = _identity()

    changed = mutate(identity)

    assert changed.identity_digest != identity.identity_digest


def test_same_vendor_capabilities_have_distinct_identities() -> None:
    identities = [
        _identity(
            endpoint=f"endpoint.{capability.value.casefold()}",
            capability=capability,
        )
        for capability in ProviderCapability
    ]

    assert {identity.capability for identity in identities} == {
        ProviderCapability.DAILY_BARS,
        ProviderCapability.MINUTE_BARS,
        ProviderCapability.CORPORATE_ACTIONS,
        ProviderCapability.INSTRUMENT_STATUS,
        ProviderCapability.L2_QUOTES,
    }
    assert len({identity.identity_digest for identity in identities}) == len(identities)


def _probe(seed: str = "2") -> ProbeEvidence:
    return ProbeEvidence(
        request_digest=_digest(seed),
        raw_response_digest=_digest("3"),
        observed_at=NOW,
    )


def _coverage() -> QualificationCoverage:
    return QualificationCoverage(
        start=date(2020, 1, 1),
        end=date(2026, 8, 8),
        instruments=("600000.SSE", "000001.SZSE"),
        delisted_instruments=("600001.SSE",),
    )


def _results(status: CheckStatus = CheckStatus.PASS) -> tuple[CapabilityResult, ...]:
    return tuple(
        CapabilityResult(
            check=check,
            status=status,
            evidence_digest=_digest(format(index + 4, "x")),
        )
        for index, check in enumerate(QualificationCheck)
    )


def _report(
    *,
    probes: tuple[ProbeEvidence, ...] | None = None,
    coverage: QualificationCoverage | None = None,
    results: tuple[CapabilityResult, ...] | None = None,
    adjust_modes: tuple[str, ...] = ("NONE", "FORWARD"),
    units: tuple[str, ...] = ("price=CNY", "volume=share"),
) -> QualificationReport:
    return QualificationReport(
        identity=_identity(),
        probes=(_probe(),) if probes is None else probes,
        coverage=_coverage() if coverage is None else coverage,
        results=_results() if results is None else results,
        adjust_modes=adjust_modes,
        units=units,
        observed_at=NOW,
    )


def test_qualification_report_requires_complete_passed_evidence_matrix() -> None:
    report = _report()

    assert set(QualificationCheck) == {
        QualificationCheck.COVERAGE,
        QualificationCheck.DELISTED_INSTRUMENT,
        QualificationCheck.ADJUST_AND_UNITS,
        QualificationCheck.PAGINATION_AND_TRUNCATION,
        QualificationCheck.REVISION_BEHAVIOR,
        QualificationCheck.RATE_LIMIT,
        QualificationCheck.SCHEMA_EVOLUTION,
    }
    assert report.approvable is True
    assert report.schema_version == "astraquant.provider-qualification-report/v1"
    assert report.report_digest.startswith("sha256:")


@pytest.mark.parametrize(
    "report",
    [
        _report(probes=()),
        _report(
            coverage=QualificationCoverage(
                start=date(2020, 1, 1),
                end=date(2026, 8, 8),
                instruments=(),
                delisted_instruments=("600001.SSE",),
            )
        ),
        _report(
            coverage=QualificationCoverage(
                start=date(2020, 1, 1),
                end=date(2026, 8, 8),
                instruments=("600000.SSE",),
                delisted_instruments=(),
            )
        ),
        _report(results=_results()[:-1]),
        _report(results=_results(CheckStatus.FAIL)),
        _report(results=_results(CheckStatus.NOT_TESTED)),
        _report(adjust_modes=()),
        _report(units=()),
    ],
)
def test_incomplete_qualification_report_is_not_approvable(
    report: QualificationReport,
) -> None:
    assert report.approvable is False


def test_qualification_report_rejects_duplicate_checks() -> None:
    result = _results()[0]

    with pytest.raises(ValueError, match="duplicate qualification check"):
        _report(results=(result, result))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ProbeEvidence(
            request_digest="invalid",
            raw_response_digest=_digest("3"),
            observed_at=NOW,
        ),
        lambda: ProbeEvidence(
            request_digest=_digest("2"),
            raw_response_digest="invalid",
            observed_at=NOW,
        ),
        lambda: ProbeEvidence(
            request_digest=_digest("2"),
            raw_response_digest=_digest("3"),
            observed_at=datetime(2026, 8, 10),
        ),
        lambda: CapabilityResult(
            check=QualificationCheck.COVERAGE,
            status=CheckStatus.PASS,
            evidence_digest="invalid",
        ),
    ],
)
def test_qualification_evidence_rejects_invalid_digest_or_naive_time(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(ValueError):
        factory()


def test_qualification_report_digest_is_order_independent() -> None:
    report = _report()
    reordered = QualificationReport(
        identity=report.identity,
        probes=tuple(reversed(report.probes)),
        coverage=QualificationCoverage(
            start=report.coverage.start,
            end=report.coverage.end,
            instruments=tuple(reversed(report.coverage.instruments)),
            delisted_instruments=report.coverage.delisted_instruments,
        ),
        results=tuple(reversed(report.results)),
        adjust_modes=tuple(reversed(report.adjust_modes)),
        units=tuple(reversed(report.units)),
        observed_at=report.observed_at,
    )

    assert reordered.report_digest == report.report_digest


def test_qualification_report_digest_covers_material_evidence() -> None:
    report = _report()
    changed = _report(probes=(_probe("9"),))

    assert changed.report_digest != report.report_digest


def _timeline(report: QualificationReport | None = None) -> ProviderQualificationTimeline:
    qualified_report = _report() if report is None else report
    return ProviderQualificationTimeline(
        identity=qualified_report.identity,
        report=qualified_report,
    )


def test_full_pass_report_remains_unqualified_until_human_approval() -> None:
    timeline = _timeline()

    assert timeline.report.approvable is True
    assert timeline.state is QualificationState.UNQUALIFIED
    assert timeline.is_approved_for(timeline.identity, captured_at=NOW) is False

    approved = timeline.approve(
        reviewer="reviewer-1",
        policy_version="provider-policy/v1",
        effective_at=NOW,
    )

    assert timeline.state is QualificationState.UNQUALIFIED
    assert approved.state is QualificationState.APPROVED
    assert approved.is_approved_for(approved.identity, captured_at=NOW) is True
    assert approved.approval is not None
    assert approved.approval.identity_digest == approved.identity.identity_digest
    assert approved.approval.report_digest == approved.report.report_digest
    assert approved.approval.approval_id.startswith("sha256:")


@pytest.mark.parametrize("status", [CheckStatus.FAIL, CheckStatus.NOT_TESTED])
def test_non_approvable_report_cannot_be_manually_approved(status: CheckStatus) -> None:
    timeline = _timeline(_report(results=_results(status)))

    with pytest.raises(QualificationError, match="report is not approvable"):
        timeline.approve(
            reviewer="reviewer-1",
            policy_version="provider-policy/v1",
            effective_at=NOW,
        )


@pytest.mark.parametrize(
    "changed_identity",
    [
        replace(_identity(), interface_build="3.0.177"),
        replace(_identity(), permission_tier="level2-history"),
        replace(_identity(), schema_fingerprint=_digest("e")),
    ],
)
def test_approval_is_bound_to_exact_provider_identity(
    changed_identity: ProviderIdentity,
) -> None:
    approved = _timeline().approve(
        reviewer="reviewer-1",
        policy_version="provider-policy/v1",
        effective_at=NOW,
    )

    assert approved.is_approved_for(changed_identity, captured_at=NOW) is False


@pytest.mark.parametrize(
    "kind",
    [RevocationKind.REVOKED, RevocationKind.SUPERSEDED],
)
def test_ordinary_revocation_preserves_pre_effective_capture_history(
    kind: RevocationKind,
) -> None:
    approved = _timeline().approve(
        reviewer="reviewer-1",
        policy_version="provider-policy/v1",
        effective_at=NOW,
    )
    revoked_at = datetime(2026, 8, 11, tzinfo=UTC)
    revoked = approved.revoke(
        kind=kind,
        effective_at=revoked_at,
        reviewer="reviewer-2",
        reason_digest=_digest("f"),
    )

    assert revoked.state is QualificationState.REVOKED
    assert revoked.is_approved_for(
        revoked.identity,
        captured_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
    )
    assert revoked.is_approved_for(revoked.identity, captured_at=revoked_at) is False

    with pytest.raises(QualificationError, match="duplicate revocation"):
        revoked.revoke(
            kind=kind,
            effective_at=revoked_at,
            reviewer="reviewer-2",
            reason_digest=_digest("f"),
        )


def test_revocation_cannot_predate_approval() -> None:
    approved = _timeline().approve(
        reviewer="reviewer-1",
        policy_version="provider-policy/v1",
        effective_at=NOW,
    )

    with pytest.raises(QualificationError, match="before approval"):
        approved.revoke(
            kind=RevocationKind.REVOKED,
            effective_at=datetime(2026, 8, 9, tzinfo=UTC),
            reviewer="reviewer-2",
            reason_digest=_digest("f"),
        )


def test_retroactive_compromise_invalidates_all_capture_history() -> None:
    approved = _timeline().approve(
        reviewer="reviewer-1",
        policy_version="provider-policy/v1",
        effective_at=NOW,
    )
    compromised = approved.revoke(
        kind=RevocationKind.RETROACTIVE_COMPROMISE,
        effective_at=datetime(2026, 8, 12, tzinfo=UTC),
        reviewer="security-reviewer",
        reason_digest=_digest("f"),
    )

    assert compromised.state is QualificationState.COMPROMISED
    assert (
        compromised.is_approved_for(
            compromised.identity,
            captured_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
        )
        is False
    )
    with pytest.raises(QualificationError, match="compromised"):
        compromised.approve(
            reviewer="reviewer-3",
            policy_version="provider-policy/v2",
            effective_at=datetime(2026, 8, 13, tzinfo=UTC),
        )

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import UTC, date, datetime
from queue import Queue
from threading import Event

import pytest
from pydantic import ValidationError

from astraquant_api.formal_data_schemas import FormalCaptureRequest
from astraquant_api.formal_data_service import (
    FormalCaptureAdmissionError,
    FormalCaptureAdmissionService,
    TrustedCoverage,
)
from astraquant_api.formal_data_worker import (
    FormalCaptureResult,
    run_formal_data_worker,
)
from astraquant_api.worker import WorkerMessage, WorkerMessageKind
from astraquant_data.adapters.eastmoney_batch import CaptureCanceled
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
from astraquant_domain import Adjustment, BarFrequency

NOW = datetime(2026, 8, 11, 1, 2, 3, tzinfo=UTC)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _timeline() -> ProviderQualificationTimeline:
    identity = ProviderIdentity(
        vendor="eastmoney",
        product="eastmoney-terminal",
        endpoint="market.history",
        capability=ProviderCapability.DAILY_BARS,
        interface="gm_python_sdk",
        interface_build="test-sdk-1.0",
        transport=ProviderTransport.NDJSON_BRIDGE,
        permission_tier="level1-history",
        schema_fingerprint=_digest("1"),
    )
    report = QualificationReport(
        identity=identity,
        probes=(ProbeEvidence(_digest("2"), _digest("3"), NOW),),
        coverage=QualificationCoverage(
            start=date(2020, 1, 1),
            end=date(2026, 8, 11),
            instruments=("600000.SSE",),
            delisted_instruments=("600001.SSE",),
        ),
        results=tuple(
            CapabilityResult(check, CheckStatus.PASS, _digest(format(index + 4, "x")))
            for index, check in enumerate(QualificationCheck)
        ),
        adjust_modes=("NONE",),
        units=("price=CNY", "volume=share"),
        observed_at=NOW,
    )
    return ProviderQualificationTimeline(identity=identity, report=report).approve(
        reviewer="reviewer@example.com",
        policy_version="provider-policy/v1",
        effective_at=NOW,
    )


class FakeQualificationLookup:
    def __init__(self, timeline: ProviderQualificationTimeline | None) -> None:
        self.timeline = timeline
        self.approval_ids: list[str] = []

    def get_timeline_for_approval(
        self,
        approval_id: str,
    ) -> ProviderQualificationTimeline | None:
        self.approval_ids.append(approval_id)
        return self.timeline


class FakeCoverageResolver:
    def __init__(self) -> None:
        self.resolution = TrustedCoverage(
            sessions=(date(2026, 8, 10), date(2026, 8, 11)),
            rows_per_session=1,
            coverage_membership_digest=_digest("a"),
            policy_digest=_digest("b"),
        )
        self.requests: list[tuple[str, str, date, date]] = []

    def resolve(
        self,
        *,
        instrument_id: str,
        frequency: str,
        start: date,
        end: date,
    ) -> TrustedCoverage:
        self.requests.append((instrument_id, frequency, start, end))
        return self.resolution


def _request(approval_id: str) -> FormalCaptureRequest:
    return FormalCaptureRequest(
        approval_id=approval_id,
        instrument_id="600000.SSE",
        frequency=BarFrequency.DAY,
        start=date(2026, 8, 10),
        end=date(2026, 8, 11),
        adjustment=Adjustment.NONE,
    )


def test_admission_freezes_exact_approval_identity_and_trusted_coverage() -> None:
    timeline = _timeline()
    assert timeline.approval is not None
    lookup = FakeQualificationLookup(timeline)
    coverage = FakeCoverageResolver()
    service = FormalCaptureAdmissionService(lookup=lookup, coverage=coverage)

    command = service.resolve(_request(timeline.approval.approval_id), created_at=NOW)

    assert command.approval_id == timeline.approval.approval_id
    assert command.report_digest == timeline.report.report_digest
    assert command.identity == timeline.identity.to_dict()
    assert command.sessions == (date(2026, 8, 10), date(2026, 8, 11))
    assert command.coverage_membership_digest == _digest("a")
    assert command.policy_digest == _digest("b")
    assert command.command_digest.startswith("sha256:")
    assert lookup.approval_ids == [timeline.approval.approval_id]
    assert coverage.requests == [("600000.SSE", "1d", date(2026, 8, 10), date(2026, 8, 11))]


def test_request_cannot_select_legacy_or_alternate_provider() -> None:
    timeline = _timeline()
    assert timeline.approval is not None

    with pytest.raises(ValidationError, match="provider"):
        FormalCaptureRequest.model_validate(
            {
                **_request(timeline.approval.approval_id).model_dump(mode="json"),
                "provider": "fixture",
            }
        )


def test_admission_rejects_revoked_approval_at_command_time() -> None:
    timeline = _timeline()
    assert timeline.approval is not None
    revoked = timeline.revoke(
        kind=RevocationKind.REVOKED,
        effective_at=NOW,
        reviewer="reviewer@example.com",
        reason_digest=_digest("c"),
    )
    service = FormalCaptureAdmissionService(
        lookup=FakeQualificationLookup(revoked),
        coverage=FakeCoverageResolver(),
    )

    with pytest.raises(FormalCaptureAdmissionError, match="not approved"):
        service.resolve(_request(timeline.approval.approval_id), created_at=NOW)


def test_admission_rejects_empty_or_untrusted_coverage() -> None:
    timeline = _timeline()
    assert timeline.approval is not None
    coverage = FakeCoverageResolver()
    object.__setattr__(
        coverage,
        "resolution",
        TrustedCoverage(
            sessions=(),
            rows_per_session=1,
            coverage_membership_digest=_digest("a"),
            policy_digest=_digest("b"),
        ),
    )
    service = FormalCaptureAdmissionService(
        lookup=FakeQualificationLookup(timeline),
        coverage=coverage,
    )

    with pytest.raises(FormalCaptureAdmissionError, match="coverage"):
        service.resolve(_request(timeline.approval.approval_id), created_at=NOW)


def _command_values() -> dict[str, object]:
    timeline = _timeline()
    assert timeline.approval is not None
    command = FormalCaptureAdmissionService(
        lookup=FakeQualificationLookup(timeline),
        coverage=FakeCoverageResolver(),
    ).resolve(_request(timeline.approval.approval_id), created_at=NOW)
    return command.model_dump(mode="json")


def _run_worker(
    executor: Callable[..., FormalCaptureResult],
    *,
    cancel: Event | None = None,
) -> WorkerMessage:
    messages: Queue[WorkerMessage] = Queue()
    run_formal_data_worker(
        "formal-task",
        messages,
        cancel or Event(),
        _command_values(),
        "D:/formal/capture",
        "D:/sdk/python.exe",
        "D:/repo/tools/eastmoney_bridge.py",
        "private-eastmoney-token",
        executor=executor,
    )
    emitted: list[WorkerMessage] = []
    while not messages.empty():
        emitted.append(messages.get_nowait())
    return emitted[-1]


def test_worker_returns_only_sealed_capture_audit_fields() -> None:
    def execute(**_: object) -> FormalCaptureResult:
        return FormalCaptureResult(
            command_digest=_digest("d"),
            capture_id=_digest("e"),
            seal_digest=_digest("f"),
            chunk_count=2,
            row_count=2,
        )

    terminal = _run_worker(execute)

    assert terminal.kind is WorkerMessageKind.SUCCEEDED
    assert terminal.progress == 100
    assert terminal.payload == {
        "command_digest": _digest("d"),
        "capture_id": _digest("e"),
        "seal_digest": _digest("f"),
        "chunk_count": 2,
        "row_count": 2,
    }
    serialized = repr(terminal)
    assert "private-eastmoney-token" not in serialized
    assert "D:/formal" not in serialized


def test_worker_cancellation_never_reports_success_or_fake_seal() -> None:
    def execute(**_: object) -> FormalCaptureResult:
        raise CaptureCanceled("stop after persisted page")

    terminal = _run_worker(execute)

    assert terminal.kind is WorkerMessageKind.CANCELED
    assert terminal.payload is None
    assert terminal.current_step == "canceled"


def test_worker_source_has_no_database_or_legacy_provider_capability() -> None:
    source = inspect.getsource(run_formal_data_worker).casefold()

    assert "sqlalchemy" not in source
    assert "qualificationrepository" not in source
    assert "from astraquant_api.data_worker import" not in source
    assert "import astraquant_api.data_worker" not in source
    assert "akshare" not in source
    assert "csv" not in source

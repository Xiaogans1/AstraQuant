from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from astraquant_data.adapters.eastmoney_batch import (
    BatchCaptureRequest,
    EastmoneyBatchAdapter,
    ProviderEvidenceDriftError,
    plan_session_coverage,
)
from astraquant_data.capture import CapturePlan, CapturePurpose, CaptureStatus
from astraquant_data.capture_store import CaptureStore, IncompleteCaptureError
from astraquant_data.eastmoney_client import (
    BridgeCallEvidence,
    BridgeResponse,
    BridgeResponseRepresentation,
    HistoryCall,
    HistoryRangeCapture,
)
from astraquant_data.eastmoney_protocol import (
    HistoryBatch,
    HistoryPage,
    HistoryPageEvidence,
    HistoryPageSpec,
)
from astraquant_data.provider_identity import (
    ProviderCapability,
    ProviderIdentity,
    ProviderTransport,
)
from astraquant_domain.run_manifest import canonical_json_bytes

NOW = datetime(2026, 8, 11, 1, 2, 3, tzinfo=UTC)


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _identity(schema: dict[str, object]) -> ProviderIdentity:
    return ProviderIdentity(
        vendor="eastmoney",
        product="eastmoney-terminal",
        endpoint="market.history",
        capability=ProviderCapability.DAILY_BARS,
        interface="gm_python_sdk",
        interface_build="test-sdk-1.0",
        transport=ProviderTransport.NDJSON_BRIDGE,
        permission_tier="level1-history",
        schema_fingerprint=_digest(schema),
    )


def _spec(index: int, count: int) -> HistoryPageSpec:
    return HistoryPageSpec(
        index=index,
        page_count=count,
        cursor=f"day-{index}",
        start_at=datetime(2026, 8, 1 + index, tzinfo=UTC),
        end_at=datetime(2026, 8, 2 + index, tzinfo=UTC),
    )


def _captured_range(
    *,
    count: int = 2,
    adjust: int = 0,
    provider_declares_total: bool = True,
) -> HistoryRangeCapture:
    schema: dict[str, object] = {
        "kind": "object",
        "fields": ["page", "rows"],
        "field_types": {"page": ["dict"], "rows": ["list"]},
    }
    calls: list[HistoryCall] = []
    pages: list[HistoryPage] = []
    rows: list[dict[str, object]] = []
    for index in range(count):
        spec = _spec(index, count)
        row: dict[str, object] = {
            "symbol": "SHSE.600000",
            "bob": spec.start_at.isoformat(),
            "close": str(10 + index),
        }
        result = {
            "rows": [row],
            "page": {
                "index": index,
                "page_count": count,
                "cursor": spec.cursor,
                "start_at": spec.start_at.isoformat(),
                "end_at": spec.end_at.isoformat(),
                "frequency": "1d",
                "adjust": adjust,
                "units": ["price=CNY", "volume=share"],
                "returned_count": 1,
                "declared_total": count if provider_declares_total else None,
            },
        }
        request: dict[str, object] = {
            "contract_version": "astraquant.eastmoney-bridge/v1",
            "id": str(index + 1),
            "method": "history_range",
            "params": {"page": index, "adjust": adjust},
            "requested_at": (NOW.replace(microsecond=index)).isoformat(),
        }
        evidence = BridgeCallEvidence(
            request_digest=_digest(request),
            response_digest=_digest(result),
            canonical_request=request,
            attempt=1,
            retry_of_request_digest=None,
            representation=BridgeResponseRepresentation.SDK_OBJECT_CANONICAL,
            serialization_version="astraquant.sdk-object-json/v1",
            interface="gm_python_sdk",
            interface_build="test-sdk-1.0",
            permission_tier="level1-history",
            requested_at=NOW.replace(microsecond=index),
            received_at=NOW.replace(microsecond=index + 10),
            observed_schema=schema,
        )
        page = HistoryPage(
            rows=(row,),
            evidence=HistoryPageEvidence(
                spec=spec,
                returned_count=1,
                declared_total=count if provider_declares_total else None,
                frequency="1d",
                adjust=adjust,
                units=("price=CNY", "volume=share"),
                schema_digest=_digest({"row": "schema"}),
                request_digest=evidence.request_digest,
                response_digest=evidence.response_digest,
            ),
        )
        pages.append(page)
        rows.append(row)
        calls.append(
            HistoryCall(
                page=page,
                response=BridgeResponse(result=result, evidence=evidence),
            )
        )
    return HistoryRangeCapture(
        batch=HistoryBatch(rows=tuple(rows), pages=tuple(pages), declared_total=count),
        calls=tuple(calls),
    )


class FakeBatchClient:
    def __init__(self, captured: HistoryRangeCapture) -> None:
        self.captured = captured
        self.requests: list[dict[str, object]] = []
        self.error: Exception | None = None

    def history_range_with_evidence(self, **request: object) -> HistoryRangeCapture:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.captured


def _request(count: int = 2, *, adjust: int = 0) -> BatchCaptureRequest:
    return BatchCaptureRequest(
        symbol="SHSE.600000",
        frequency="1d",
        pages=tuple(_spec(index, count) for index in range(count)),
        adjust=adjust,
        units=("price=CNY", "volume=share"),
        expected_total=count,
        coverage_membership_digest=_digest({"pages": count}),
    )


def test_batch_adapter_seals_exact_real_call_bytes_without_adjustment_drift(
    tmp_path: Path,
) -> None:
    captured = _captured_range(adjust=0)
    client = FakeBatchClient(captured)
    schema = captured.calls[0].response.evidence.observed_schema
    identity = _identity(schema)
    request = _request()
    plan = CapturePlan(
        identity_digest=identity.identity_digest,
        report_digest=None,
        approval_id=None,
        endpoint=identity.endpoint,
        expected_chunk_count=2,
        expected_row_count=2,
        coverage_proof_digest=request.coverage_proof_digest,
        purpose=CapturePurpose.QUALIFICATION_PROBE,
    )
    store = CaptureStore(tmp_path)
    adapter = EastmoneyBatchAdapter(client=client, store=store, identity=identity)

    envelope = adapter.capture(request, plan=plan, recorded_at=NOW)

    assert envelope.status is CaptureStatus.SEALED
    assert client.requests[0]["adjust"] == 0
    first = store.read_chunk(plan.capture_id, envelope.chunk_ids[0])
    assert first.adjust == "NONE"
    assert first.canonical_response == canonical_json_bytes(captured.calls[0].response.result)
    assert first.request_digest == captured.calls[0].response.evidence.request_digest
    assert first.response_digest == captured.calls[0].response.evidence.response_digest


def test_batch_adapter_maps_adjust_one_to_forward_not_none(tmp_path: Path) -> None:
    captured = _captured_range(count=1, adjust=1)
    identity = _identity(captured.calls[0].response.evidence.observed_schema)
    request = _request(count=1, adjust=1)
    plan = CapturePlan(
        identity_digest=identity.identity_digest,
        report_digest=None,
        approval_id=None,
        endpoint=identity.endpoint,
        expected_chunk_count=1,
        expected_row_count=1,
        coverage_proof_digest=request.coverage_proof_digest,
        purpose=CapturePurpose.QUALIFICATION_PROBE,
    )
    store = CaptureStore(tmp_path)
    adapter = EastmoneyBatchAdapter(
        client=FakeBatchClient(captured),
        store=store,
        identity=identity,
    )

    envelope = adapter.capture(request, plan=plan, recorded_at=NOW)

    chunk = store.read_chunk(plan.capture_id, envelope.chunk_ids[0])
    assert chunk.adjust == "FORWARD"


def test_batch_adapter_uses_pinned_coverage_proof_when_provider_has_no_total(
    tmp_path: Path,
) -> None:
    captured = _captured_range(count=1, provider_declares_total=False)
    identity = _identity(captured.calls[0].response.evidence.observed_schema)
    request = _request(count=1)
    plan = CapturePlan(
        identity_digest=identity.identity_digest,
        report_digest=None,
        approval_id=None,
        endpoint=identity.endpoint,
        expected_chunk_count=1,
        expected_row_count=1,
        coverage_proof_digest=request.coverage_proof_digest,
        purpose=CapturePurpose.QUALIFICATION_PROBE,
    )
    store = CaptureStore(tmp_path)
    adapter = EastmoneyBatchAdapter(
        client=FakeBatchClient(captured),
        store=store,
        identity=identity,
    )

    envelope = adapter.capture(request, plan=plan, recorded_at=NOW)

    assert envelope.status is CaptureStatus.SEALED


def test_batch_adapter_rejects_identity_or_runtime_schema_drift(tmp_path: Path) -> None:
    captured = _captured_range(count=1)
    identity = _identity({"different": "schema"})
    request = _request(count=1)
    plan = CapturePlan(
        identity_digest=identity.identity_digest,
        report_digest=None,
        approval_id=None,
        endpoint=identity.endpoint,
        expected_chunk_count=1,
        expected_row_count=1,
        coverage_proof_digest=request.coverage_proof_digest,
        purpose=CapturePurpose.QUALIFICATION_PROBE,
    )
    adapter = EastmoneyBatchAdapter(
        client=FakeBatchClient(captured),
        store=CaptureStore(tmp_path),
        identity=identity,
    )

    with pytest.raises(ProviderEvidenceDriftError, match="schema"):
        adapter.capture(request, plan=plan, recorded_at=NOW)


def test_batch_adapter_never_seals_when_client_cannot_prove_completeness(
    tmp_path: Path,
) -> None:
    captured = _captured_range(count=1)
    client = FakeBatchClient(captured)
    client.error = IncompleteCaptureError("upstream incomplete")
    identity = _identity(captured.calls[0].response.evidence.observed_schema)
    request = _request(count=1)
    plan = CapturePlan(
        identity_digest=identity.identity_digest,
        report_digest=None,
        approval_id=None,
        endpoint=identity.endpoint,
        expected_chunk_count=1,
        expected_row_count=1,
        coverage_proof_digest=request.coverage_proof_digest,
        purpose=CapturePurpose.QUALIFICATION_PROBE,
    )
    store = CaptureStore(tmp_path)
    adapter = EastmoneyBatchAdapter(client=client, store=store, identity=identity)

    with pytest.raises(IncompleteCaptureError):
        adapter.capture(request, plan=plan, recorded_at=NOW)

    with pytest.raises(IncompleteCaptureError, match="not sealed"):
        store.read(plan.capture_id)


def test_minute_request_cannot_assume_one_5000_row_page_covers_51_sessions() -> None:
    with pytest.raises(ValueError, match="chunk capacity"):
        BatchCaptureRequest(
            symbol="SHSE.600000",
            frequency="60s",
            pages=(_spec(0, 1),),
            adjust=0,
            units=("price=CNY", "volume=share"),
            expected_total=12_240,
            coverage_membership_digest=_digest({"sessions": 51}),
        )


def test_batch_request_rejects_overlapping_page_ranges() -> None:
    first = _spec(0, 2)
    overlapping = HistoryPageSpec(
        index=1,
        page_count=2,
        cursor="overlap",
        start_at=first.end_at.replace(hour=0) - (first.end_at - first.start_at) / 2,
        end_at=first.end_at.replace(day=first.end_at.day + 1),
    )

    with pytest.raises(ValueError, match="overlap"):
        BatchCaptureRequest(
            symbol="SHSE.600000",
            frequency="60s",
            pages=(first, overlapping),
            adjust=0,
            units=("price=CNY", "volume=share"),
            expected_total=2,
            coverage_membership_digest=_digest({"sessions": 2}),
        )


def test_minute_coverage_planner_splits_51_sessions_below_5000_row_limit() -> None:
    sessions = tuple(date(2026, 5, 1) + timedelta(days=index) for index in range(51))

    request = plan_session_coverage(
        symbol="SHSE.600000",
        frequency="60s",
        sessions=sessions,
        rows_per_session=240,
        adjust=0,
    )

    assert request.expected_total == 12_240
    assert len(request.pages) == 3
    assert request.max_rows_per_chunk == 5_000
    assert all(page.page_count == 3 for page in request.pages)


def test_daily_coverage_planner_binds_exact_lifecycle_sessions_and_symbol() -> None:
    sessions = (date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6))
    first = plan_session_coverage(
        symbol="SHSE.600000",
        frequency="1d",
        sessions=sessions,
        rows_per_session=1,
        adjust=0,
    )
    second = plan_session_coverage(
        symbol="SHSE.600001",
        frequency="1d",
        sessions=sessions,
        rows_per_session=1,
        adjust=0,
    )
    different_middle_session = plan_session_coverage(
        symbol="SHSE.600000",
        frequency="1d",
        sessions=(sessions[0], date(2020, 1, 4), sessions[-1]),
        rows_per_session=1,
        adjust=0,
    )

    assert first.expected_total == len(sessions)
    assert first.pages[0].cursor == "2020-01-02/2020-01-06"
    assert first.coverage_proof_digest != second.coverage_proof_digest
    assert first.coverage_proof_digest != different_middle_session.coverage_proof_digest

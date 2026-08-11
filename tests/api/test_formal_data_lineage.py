from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from astraquant_api.formal_data_lineage import FormalCaptureLineageService
from astraquant_api.formal_data_schemas import (
    FormalCaptureRequest,
    FormalIncrementRequest,
    ResolvedFormalCaptureCommand,
)
from astraquant_api.formal_data_service import FormalCaptureAdmissionError
from astraquant_data.capture import CaptureChunk, CaptureEnvelope, CapturePlan
from astraquant_data.eastmoney_client import BridgeResponseRepresentation

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _chunk() -> CaptureChunk:
    request = {
        "method": "history_range",
        "params": {
            "symbol": "SHSE.600000",
            "frequency": "1d",
            "adjust": 0,
            "page": {"cursor": "2026-08-10/2026-08-11"},
        },
    }
    return CaptureChunk(
        sequence=0,
        canonical_request=json.dumps(request).encode(),
        canonical_response=b"[]",
        response_representation=BridgeResponseRepresentation.SDK_OBJECT_CANONICAL,
        requested_at=NOW,
        received_at=NOW,
        recorded_at=NOW,
        serialization_version="astraquant.sdk-object-json/v1",
        dtype="list[bar]",
        schema={"kind": "list"},
        units=("price=CNY",),
        adjust="NONE",
        page_cursor="2026-08-10/2026-08-11",
        page_count=1,
        returned_count=0,
        declared_total=0,
        attempt=1,
        retry_of_request_digest=None,
    )


class _Store:
    def __init__(self) -> None:
        self.chunk = _chunk()
        plan = CapturePlan(
            identity_digest=_digest("1"),
            report_digest=_digest("2"),
            approval_id=_digest("3"),
            endpoint="market.history",
            expected_chunk_count=1,
            expected_row_count=0,
            coverage_proof_digest=_digest("4"),
            started_at=NOW,
        )
        self.capture_id = plan.capture_id
        self.envelope = CaptureEnvelope(plan=plan, chunk_ids=(self.chunk.chunk_id,), sealed_at=NOW)

    def read(self, capture_id: str) -> CaptureEnvelope:
        assert capture_id == self.capture_id
        return self.envelope

    def read_chunk(self, capture_id: str, chunk_id: str) -> CaptureChunk:
        assert capture_id == self.capture_id
        assert chunk_id == self.chunk.chunk_id
        return self.chunk


class _Admission:
    def __init__(self, store: _Store, *, drift: bool = False) -> None:
        self.store = store
        self.drift = drift
        self.request: FormalCaptureRequest | None = None

    def resolve(
        self, request: FormalCaptureRequest, *, created_at: datetime
    ) -> ResolvedFormalCaptureCommand:
        self.request = request
        plan = self.store.envelope.plan
        return ResolvedFormalCaptureCommand(
            identity={"vendor": "eastmoney"},
            identity_digest=_digest("9") if self.drift else plan.identity_digest,
            report_digest=plan.report_digest or _digest("2"),
            approval_id=plan.approval_id or _digest("3"),
            instrument_id=request.instrument_id,
            frequency=request.frequency,
            start=request.start,
            end=request.end,
            adjustment=request.adjustment,
            sessions=(request.start,),
            rows_per_session=1,
            coverage_membership_digest=_digest("5"),
            policy_digest=_digest("6"),
            created_at=created_at,
        )


def test_increment_is_derived_from_exact_sealed_predecessor_and_binds_lineage() -> None:
    store = _Store()
    admission = _Admission(store)
    service = FormalCaptureLineageService(store=store, admission=admission)

    command = service.resolve_increment(
        FormalIncrementRequest(
            predecessor_capture_id=store.capture_id,
            end=date(2026, 8, 14),
        ),
        created_at=NOW,
    )

    assert admission.request is not None
    assert admission.request.model_dump(mode="json") == {
        "approval_id": _digest("3"),
        "instrument_id": "600000.SSE",
        "frequency": "1d",
        "start": "2026-08-12",
        "end": "2026-08-14",
        "adjustment": "none",
    }
    assert command.predecessor_capture_id == store.capture_id


def test_increment_rejects_approval_identity_drift() -> None:
    store = _Store()
    service = FormalCaptureLineageService(store=store, admission=_Admission(store, drift=True))

    with pytest.raises(FormalCaptureAdmissionError, match="lineage drift"):
        service.resolve_increment(
            FormalIncrementRequest(
                predecessor_capture_id=store.capture_id,
                end=date(2026, 8, 14),
            ),
            created_at=NOW,
        )

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from astraquant_data.capture import (
    CaptureChunk,
    CapturePlan,
    CapturePurpose,
    CaptureStatus,
    SecretMaterialError,
)
from astraquant_data.capture_store import (
    CaptureConflictError,
    CaptureIntegrityError,
    CaptureStore,
    IncompleteCaptureError,
    SealedCaptureError,
)
from astraquant_data.eastmoney_client import BridgeResponseRepresentation

NOW = datetime(2026, 8, 11, 1, 2, 3, tzinfo=UTC)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _plan(*, expected_chunk_count: int = 2) -> CapturePlan:
    return CapturePlan(
        identity_digest=_digest("1"),
        report_digest=_digest("2"),
        approval_id=_digest("3"),
        endpoint="market.history",
        expected_chunk_count=expected_chunk_count,
        expected_row_count=expected_chunk_count,
        coverage_proof_digest=_digest("5"),
        started_at=NOW,
        purpose=CapturePurpose.FORMAL_DATA,
    )


def _chunk(
    sequence: int = 0,
    *,
    close: str = "10.00",
    page_count: int = 2,
    page_cursor: str | None = None,
    declared_total: int | None = 2,
    adjust: str = "NONE",
    units: tuple[str, ...] = ("price=CNY", "volume=share"),
) -> CaptureChunk:
    request = {
        "symbol": "SHSE.600000",
        "frequency": "1d",
        "page": sequence,
        "adjust": 0,
    }
    response = [{"symbol": "SHSE.600000", "close": close}]
    return CaptureChunk(
        sequence=sequence,
        canonical_request=json.dumps(request, sort_keys=True).encode(),
        canonical_response=json.dumps(response, sort_keys=True).encode(),
        response_representation=BridgeResponseRepresentation.SDK_OBJECT_CANONICAL,
        requested_at=NOW + timedelta(seconds=sequence * 3),
        received_at=NOW + timedelta(seconds=sequence * 3 + 1),
        recorded_at=NOW + timedelta(seconds=sequence * 3 + 2),
        serialization_version="astraquant.sdk-object-json/v1",
        dtype="list[bar]",
        schema={"fields": ["close", "symbol"], "version": "v1"},
        units=units,
        adjust=adjust,
        page_cursor=page_cursor or f"page-{sequence}",
        page_count=page_count,
        returned_count=1,
        declared_total=declared_total,
        attempt=1,
        retry_of_request_digest=None,
    )


def test_store_appends_chunks_idempotently_and_seals_complete_parent(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    plan = _plan()
    first = _chunk(0)
    second = _chunk(1)

    assert store.begin(plan) == plan.capture_id
    assert store.begin(plan) == plan.capture_id
    assert store.append_chunk(plan.capture_id, first) == first.chunk_id
    assert store.append_chunk(plan.capture_id, first) == first.chunk_id
    store.append_chunk(plan.capture_id, second)

    envelope = store.seal(plan.capture_id)

    assert envelope.status is CaptureStatus.SEALED
    assert envelope.plan == plan
    assert envelope.chunk_ids == (first.chunk_id, second.chunk_id)
    assert store.read(plan.capture_id) == envelope


def test_seal_fails_closed_when_parent_is_missing_a_planned_chunk(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    plan = _plan()
    store.begin(plan)
    store.append_chunk(plan.capture_id, _chunk(0))

    with pytest.raises(IncompleteCaptureError, match="expected 2 chunks"):
        store.seal(plan.capture_id)


def test_same_sequence_with_different_payload_conflicts(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    plan = _plan(expected_chunk_count=1)
    store.begin(plan)
    store.append_chunk(plan.capture_id, _chunk(0, page_count=1, declared_total=1))

    with pytest.raises(CaptureConflictError, match="sequence 0"):
        store.append_chunk(
            plan.capture_id,
            _chunk(0, close="10.01", page_count=1, declared_total=1),
        )


def test_sealed_capture_rejects_late_chunks(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    plan = _plan(expected_chunk_count=1)
    store.begin(plan)
    store.append_chunk(plan.capture_id, _chunk(0, page_count=1, declared_total=1))
    store.seal(plan.capture_id)

    with pytest.raises(SealedCaptureError):
        store.append_chunk(plan.capture_id, _chunk(0, page_count=1, declared_total=1))


def test_read_recomputes_chunk_digest_and_detects_one_byte_tamper(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    plan = _plan(expected_chunk_count=1)
    chunk = _chunk(0, page_count=1, declared_total=1)
    store.begin(plan)
    store.append_chunk(plan.capture_id, chunk)
    store.seal(plan.capture_id)
    chunk_path = store.chunk_path(plan.capture_id, chunk.chunk_id)
    body = json.loads(chunk_path.read_text(encoding="utf-8"))
    body["canonical_response_b64"] = "W10="  # []
    chunk_path.write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(CaptureIntegrityError, match="chunk digest"):
        store.read(plan.capture_id)


@pytest.mark.parametrize("secret_key", ["token", "cookie", "Authorization", "password"])
def test_chunk_rejects_secret_like_request_fields(secret_key: str) -> None:
    request = json.dumps({secret_key: "must-not-be-recorded"}).encode()

    with pytest.raises(SecretMaterialError, match="secret-like"):
        CaptureChunk(
            sequence=0,
            canonical_request=request,
            canonical_response=b"[]",
            response_representation=BridgeResponseRepresentation.SDK_OBJECT_CANONICAL,
            requested_at=NOW,
            received_at=NOW,
            recorded_at=NOW,
            serialization_version="astraquant.sdk-object-json/v1",
            dtype="list[bar]",
            schema={"fields": []},
            units=("price=CNY",),
            adjust="NONE",
            page_cursor="page-0",
            page_count=1,
            returned_count=0,
            declared_total=0,
            attempt=1,
            retry_of_request_digest=None,
        )


def test_capture_identity_changes_with_exact_approval_or_endpoint() -> None:
    baseline = _plan()

    assert _plan(expected_chunk_count=1).capture_id != baseline.capture_id
    assert (
        CapturePlan(
            identity_digest=baseline.identity_digest,
            report_digest=baseline.report_digest,
            approval_id=_digest("4"),
            endpoint=baseline.endpoint,
            expected_chunk_count=baseline.expected_chunk_count,
            expected_row_count=baseline.expected_row_count,
            coverage_proof_digest=baseline.coverage_proof_digest,
            started_at=baseline.started_at,
        ).capture_id
        != baseline.capture_id
    )
    assert (
        CapturePlan(
            identity_digest=baseline.identity_digest,
            report_digest=baseline.report_digest,
            approval_id=baseline.approval_id,
            endpoint=baseline.endpoint,
            expected_chunk_count=baseline.expected_chunk_count,
            expected_row_count=baseline.expected_row_count,
            coverage_proof_digest=baseline.coverage_proof_digest,
            started_at=baseline.started_at + timedelta(seconds=1),
        ).capture_id
        != baseline.capture_id
    )


def test_formal_capture_plan_binds_command_and_optional_predecessor() -> None:
    baseline = _plan(expected_chunk_count=1)
    linked = CapturePlan(
        identity_digest=baseline.identity_digest,
        report_digest=baseline.report_digest,
        approval_id=baseline.approval_id,
        endpoint=baseline.endpoint,
        expected_chunk_count=baseline.expected_chunk_count,
        expected_row_count=baseline.expected_row_count,
        coverage_proof_digest=baseline.coverage_proof_digest,
        started_at=baseline.started_at,
        purpose=baseline.purpose,
        command_digest=_digest("8"),
        predecessor_capture_id=_digest("9"),
    )

    assert linked.capture_id != baseline.capture_id
    assert CapturePlan.from_dict(linked.to_dict()) == linked


def test_legacy_capture_plan_without_lineage_fields_remains_stable() -> None:
    plan = _plan(expected_chunk_count=1)
    legacy = plan.to_dict()

    assert "command_digest" not in legacy
    assert "predecessor_capture_id" not in legacy
    assert CapturePlan.from_dict(legacy).capture_id == plan.capture_id


def test_append_rejects_page_count_that_disagrees_with_parent_plan(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    plan = _plan(expected_chunk_count=2)
    store.begin(plan)

    with pytest.raises(CaptureConflictError, match="page_count"):
        store.append_chunk(plan.capture_id, _chunk(0, page_count=3))


def test_append_rejects_duplicate_page_cursor_across_sequences(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    plan = _plan()
    store.begin(plan)
    store.append_chunk(plan.capture_id, _chunk(0, page_cursor="same-page"))

    with pytest.raises(CaptureConflictError, match="page cursor"):
        store.append_chunk(plan.capture_id, _chunk(1, page_cursor="same-page"))


def test_seal_rejects_disagreeing_declared_totals(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    plan = _plan()
    store.begin(plan)
    store.append_chunk(plan.capture_id, _chunk(0, declared_total=2))
    store.append_chunk(plan.capture_id, _chunk(1, declared_total=3))

    with pytest.raises(IncompleteCaptureError, match="declared total"):
        store.seal(plan.capture_id)


def test_seal_rejects_adjustment_or_unit_drift_across_chunks(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    plan = _plan()
    store.begin(plan)
    store.append_chunk(plan.capture_id, _chunk(0))
    store.append_chunk(plan.capture_id, _chunk(1, adjust="FORWARD"))

    with pytest.raises(IncompleteCaptureError, match="adjustment/units/schema"):
        store.seal(plan.capture_id)


def test_chunk_rejects_secret_like_response_fields() -> None:
    with pytest.raises(SecretMaterialError, match="secret-like"):
        CaptureChunk(
            sequence=0,
            canonical_request=b"{}",
            canonical_response=b'{"cookie":"must-not-be-recorded"}',
            response_representation=BridgeResponseRepresentation.SDK_OBJECT_CANONICAL,
            requested_at=NOW,
            received_at=NOW,
            recorded_at=NOW,
            serialization_version="astraquant.sdk-object-json/v1",
            dtype="list[bar]",
            schema={"fields": []},
            units=("price=CNY",),
            adjust="NONE",
            page_cursor="page-0",
            page_count=1,
            returned_count=0,
            declared_total=0,
            attempt=1,
            retry_of_request_digest=None,
        )


def test_qualification_probe_can_be_captured_before_report_or_approval() -> None:
    plan = CapturePlan(
        identity_digest=_digest("1"),
        report_digest=None,
        approval_id=None,
        endpoint="market.history",
        expected_chunk_count=1,
        expected_row_count=1,
        coverage_proof_digest=_digest("5"),
        started_at=NOW,
        purpose=CapturePurpose.QUALIFICATION_PROBE,
    )

    assert plan.report_digest is None
    assert plan.approval_id is None
    assert plan.capture_id.startswith("sha256:")


@pytest.mark.parametrize(("report", "approval"), [(None, _digest("3")), (_digest("2"), None)])
def test_formal_capture_requires_exact_report_and_approval(
    report: str | None,
    approval: str | None,
) -> None:
    with pytest.raises(ValueError, match="formal capture"):
        CapturePlan(
            identity_digest=_digest("1"),
            report_digest=report,
            approval_id=approval,
            endpoint="market.history",
            expected_chunk_count=1,
            expected_row_count=1,
            coverage_proof_digest=_digest("5"),
            started_at=NOW,
            purpose=CapturePurpose.FORMAL_DATA,
        )

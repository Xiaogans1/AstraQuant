from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from astraquant_data.capture import CaptureChunk, CapturePlan
from astraquant_data.capture_reconciliation import (
    CaptureReconciliationStatus,
    reconcile_captures,
)
from astraquant_data.capture_store import CaptureIntegrityError, CaptureStore
from astraquant_data.eastmoney_client import BridgeResponseRepresentation

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _capture(
    store: CaptureStore,
    *,
    started_at: datetime,
    response: bytes = b'{"rows":[{"close":"10.00"}]}',
    symbol: str = "SHSE.600000",
    schema: dict[str, object] | None = None,
) -> str:
    plan = CapturePlan(
        identity_digest=_digest("1"),
        report_digest=_digest("2"),
        approval_id=_digest("3"),
        endpoint="market.history",
        expected_chunk_count=1,
        expected_row_count=1,
        coverage_proof_digest=_digest("4"),
        started_at=started_at,
        command_digest=_digest("5"),
    )
    request = {
        "method": "history_range",
        "params": {
            "symbol": symbol,
            "frequency": "1d",
            "adjust": 0,
            "units": ["price=CNY", "volume=share"],
            "page": {
                "index": 0,
                "page_count": 1,
                "cursor": "2026-08-11/2026-08-11",
                "start_at": "2026-08-10T16:00:00+00:00",
                "end_at": "2026-08-11T15:59:59.999999+00:00",
            },
        },
    }
    chunk = CaptureChunk(
        sequence=0,
        canonical_request=json.dumps(request, sort_keys=True).encode(),
        canonical_response=response,
        response_representation=BridgeResponseRepresentation.SDK_OBJECT_CANONICAL,
        requested_at=started_at,
        received_at=started_at,
        recorded_at=started_at,
        serialization_version="astraquant.sdk-object-json/v1",
        dtype="list[bar]",
        schema=schema or {"kind": "list", "fields": ["close"]},
        units=("price=CNY", "volume=share"),
        adjust="NONE",
        page_cursor="2026-08-11/2026-08-11",
        page_count=1,
        returned_count=1,
        declared_total=1,
        attempt=1,
        retry_of_request_digest=None,
    )
    store.begin(plan)
    store.append_chunk(plan.capture_id, chunk)
    store.seal(plan.capture_id, sealed_at=started_at)
    return plan.capture_id


def test_same_scope_and_content_produce_stable_match_report(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    left = _capture(store, started_at=NOW)
    right = _capture(store, started_at=NOW + timedelta(hours=1))

    first = reconcile_captures(store, left, right)
    second = reconcile_captures(store, left, right)

    assert first.status is CaptureReconciliationStatus.MATCH
    assert first.differences == ()
    assert first.report_digest == second.report_digest
    assert store.read_reconciliation(first.report_digest) == first


def test_response_change_is_content_mismatch_not_scope_mismatch(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    left = _capture(store, started_at=NOW)
    right = _capture(
        store,
        started_at=NOW + timedelta(hours=1),
        response=b'{"rows":[{"close":"10.01"}]}',
    )

    report = reconcile_captures(store, left, right)

    assert report.status is CaptureReconciliationStatus.CONTENT_MISMATCH
    assert report.differences == ("CONTENT",)
    assert report.left_scope_digest == report.right_scope_digest
    assert report.left_content_digest != report.right_content_digest


def test_symbol_or_schema_change_is_explicit_scope_mismatch(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    left = _capture(store, started_at=NOW)
    right = _capture(
        store,
        started_at=NOW + timedelta(hours=1),
        symbol="SZSE.000001",
        schema={"kind": "list", "fields": ["close", "volume"]},
    )

    report = reconcile_captures(store, left, right)

    assert report.status is CaptureReconciliationStatus.SCOPE_MISMATCH
    assert report.differences == ("REQUEST_SCOPE", "SCHEMA")


def test_reconciliation_report_tamper_is_detected_on_read(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path)
    left = _capture(store, started_at=NOW)
    right = _capture(store, started_at=NOW + timedelta(hours=1))
    report = reconcile_captures(store, left, right)
    name = report.report_digest.removeprefix("sha256:")
    path = tmp_path / "reconciliations" / name[:2] / f"{name}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["left_content_digest"] = _digest("f")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(CaptureIntegrityError, match="digest"):
        store.read_reconciliation(report.report_digest)

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from astraquant_data.eastmoney_client import (
    BridgeResponseRepresentation,
    EastmoneyBridgeClient,
    EastmoneyBridgeExited,
    EastmoneyBridgeProtocolError,
    EastmoneyBridgeTimeout,
)
from astraquant_data.eastmoney_protocol import HistoryCompletenessError, HistoryPageSpec

FAKE_BRIDGE = Path("tests/fixtures/eastmoney/fake_bridge.py")


def make_client(*, timeout_seconds: float = 1) -> EastmoneyBridgeClient:
    return EastmoneyBridgeClient(
        python_executable=Path(sys.executable),
        bridge_script=FAKE_BRIDGE,
        timeout_seconds=timeout_seconds,
    )


def test_bridge_client_never_places_token_on_the_command_line() -> None:
    client = make_client()
    client.start()
    try:
        client.configure(token="secret-token")
        quotes = client.current(["SHSE.000001"])
        assert quotes[0]["symbol"] == "SHSE.000001"
        assert "secret-token" not in " ".join(str(part) for part in client.command)
        assert client.command[1:3] == ("-I", "-u")
    finally:
        client.stop()


def test_bridge_client_correlates_monotonic_request_ids() -> None:
    client = make_client()
    with client:
        client.configure("valid-token")
        client.current(["SHSE.000001"])
        assert client.last_request_id == 2


def test_bridge_client_forwards_explicit_price_adjustment() -> None:
    client = make_client()
    with client:
        rows = client.history_n(
            symbol="SZSE.159516",
            frequency="1d",
            count=300,
            adjust=1,
        )

    assert rows == [
        {
            "symbol": "SZSE.159516",
            "frequency": "1d",
            "count": 300,
            "adjust": 1,
        }
    ]


@pytest.mark.parametrize(
    ("symbol", "error_type"),
    [
        ("TEST.TIMEOUT", EastmoneyBridgeTimeout),
        ("TEST.MALFORMED", EastmoneyBridgeProtocolError),
        ("TEST.WRONG_ID", EastmoneyBridgeProtocolError),
        ("TEST.EXIT", EastmoneyBridgeExited),
    ],
)
def test_bridge_client_fails_closed_on_bad_child_behavior(
    symbol: str,
    error_type: type[Exception],
) -> None:
    client = make_client(timeout_seconds=0.1)
    with client, pytest.raises(error_type):
        client.current([symbol])


def test_bridge_client_requires_start_and_rejects_blank_tokens() -> None:
    client = make_client()
    with pytest.raises(RuntimeError, match="not running"):
        client.current(["SHSE.000001"])
    client.start()
    try:
        with pytest.raises(ValueError, match="token"):
            client.configure("  ")
    finally:
        client.stop()


def test_bridge_client_returns_versioned_sdk_object_evidence() -> None:
    client = make_client()
    with client:
        client.configure("private-token", permission_tier="level1-history")
        response = client.current_with_evidence(["SHSE.000001"])

    assert response.result == [{"symbol": "SHSE.000001", "price": 1}]
    evidence = response.evidence
    assert evidence.representation is BridgeResponseRepresentation.SDK_OBJECT_CANONICAL
    assert evidence.serialization_version == "astraquant.sdk-object-json/v1"
    assert evidence.interface == "gm_python_sdk"
    assert evidence.interface_build == "test-sdk-1.0"
    assert evidence.permission_tier == "level1-history"
    assert evidence.request_digest.startswith("sha256:")
    assert evidence.response_digest.startswith("sha256:")
    assert evidence.attempt == 1
    assert evidence.retry_of_request_digest is None
    assert evidence.canonical_request["contract_version"] == ("astraquant.eastmoney-bridge/v1")
    assert evidence.requested_at <= evidence.received_at
    assert evidence.observed_schema["kind"] == "list"
    assert evidence.observed_schema["field_types"] == {
        "price": ["int"],
        "symbol": ["str"],
    }
    serialized = str(evidence.to_dict())
    assert "private-token" not in serialized


@pytest.mark.parametrize(
    "symbol",
    ["TEST.WRONG_VERSION", "TEST.UNKNOWN_REPRESENTATION", "TEST.BAD_DIGEST"],
)
def test_bridge_client_rejects_unverifiable_evidence_envelopes(symbol: str) -> None:
    client = make_client()
    with client, pytest.raises(EastmoneyBridgeProtocolError):
        client.current_with_evidence([symbol])


def test_bridge_client_fetches_explicit_history_ranges_with_coverage_proof() -> None:
    spec = HistoryPageSpec(
        index=0,
        page_count=1,
        cursor="2026-08-01/2026-08-02",
        start_at=datetime(2026, 8, 1, tzinfo=UTC),
        end_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    client = make_client()

    with client:
        batch = client.history_range(
            symbol="SHSE.600000",
            frequency="1d",
            pages=(spec,),
            adjust=0,
            expected_total=1,
        )

    assert batch.complete is True
    assert batch.rows == (
        {
            "symbol": "SHSE.600000",
            "bob": "2026-08-01T00:00:00+00:00",
        },
    )
    assert batch.pages[0].evidence.spec == spec


def test_bridge_client_preserves_each_history_call_for_immutable_capture() -> None:
    spec = HistoryPageSpec(
        index=0,
        page_count=1,
        cursor="2026-08-01/2026-08-02",
        start_at=datetime(2026, 8, 1, tzinfo=UTC),
        end_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    client = make_client()

    with client:
        captured = client.history_range_with_evidence(
            symbol="SHSE.600000",
            frequency="1d",
            pages=(spec,),
            adjust=0,
            expected_total=1,
        )

    assert captured.batch.rows == (
        {
            "symbol": "SHSE.600000",
            "bob": "2026-08-01T00:00:00+00:00",
        },
    )
    assert len(captured.calls) == 1
    call = captured.calls[0]
    assert call.response.evidence.request_digest == call.page.evidence.request_digest
    assert call.response.evidence.response_digest == call.page.evidence.response_digest
    assert call.response.result == {
        "rows": list(captured.batch.rows),
        "page": {
            "index": 0,
            "page_count": 1,
            "cursor": "2026-08-01/2026-08-02",
            "start_at": "2026-08-01T00:00:00+00:00",
            "end_at": "2026-08-02T00:00:00+00:00",
            "frequency": "1d",
            "adjust": 0,
            "units": ["price=CNY", "volume=share"],
            "returned_count": 1,
            "declared_total": None,
        },
    }


def test_bridge_client_can_fetch_one_exact_history_page_for_resumable_capture() -> None:
    spec = HistoryPageSpec(
        index=0,
        page_count=1,
        cursor="2026-08-01/2026-08-02",
        start_at=datetime(2026, 8, 1, tzinfo=UTC),
        end_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    client = make_client()

    with client:
        call = client.history_page_with_evidence(
            symbol="SHSE.600000",
            frequency="1d",
            page=spec,
            adjust=0,
            units=("price=CNY", "volume=share"),
        )

    assert call.page.evidence.spec == spec
    assert call.page.rows[0]["symbol"] == "SHSE.600000"


def test_bridge_client_rejects_history_without_total_or_external_proof() -> None:
    spec = HistoryPageSpec(
        index=0,
        page_count=1,
        cursor="unproven",
        start_at=datetime(2026, 8, 1, tzinfo=UTC),
        end_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    client = make_client()

    with (
        client,
        pytest.raises(
            HistoryCompletenessError,
            match="UNPROVEN_COMPLETENESS",
        ),
    ):
        client.history_range(
            symbol="SHSE.600000",
            frequency="1d",
            pages=(spec,),
            adjust=0,
        )

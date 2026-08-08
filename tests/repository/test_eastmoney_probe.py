from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_domain import InstrumentId, LiveQuote
from tools.eastmoney_probe import ProbeResult, run_probe


class FakeProvider:
    def __init__(self, quotes: list[LiveQuote] | None = None, failure: Exception | None = None):
        self.quotes = quotes or []
        self.failure = failure
        self.connected_token: str | None = None
        self.disconnected = False

    def connect(self, token: str) -> None:
        self.connected_token = token

    def poll(self, instruments: Sequence[InstrumentId]) -> list[LiveQuote]:
        assert len(instruments) == 6
        if self.failure is not None:
            raise self.failure
        return self.quotes

    def disconnect(self) -> None:
        self.disconnected = True


def quote(symbol: str, seconds_old: int = 1) -> LiveQuote:
    now = datetime.now(UTC)
    return LiveQuote.minimum(
        InstrumentId.parse(symbol),
        event_time=now - timedelta(seconds=seconds_old),
        received_time=now,
        last_price=Decimal("1"),
        previous_close=Decimal("1"),
        source_id="eastmoney",
    )


def test_probe_result_is_aggregate_only() -> None:
    provider = FakeProvider([quote("000001.SSE"), quote("399001.SZSE", 2)])

    result = run_probe(provider, token="private-token", seconds=15, poll_interval=0)
    payload = result.as_dict()

    assert result.result == "PASSED"
    assert result.requested_instrument_count == 6
    assert result.received_instrument_count == 2
    assert result.successful_poll_count == 1
    assert provider.connected_token == "private-token"
    assert provider.disconnected is True
    serialized = str(payload)
    assert "private-token" not in serialized
    assert "000001.SSE" not in serialized
    assert "last_price" not in serialized


def test_probe_reports_no_data_without_inventing_events() -> None:
    result = run_probe(FakeProvider(), token="private-token", seconds=15, poll_interval=0)

    assert result.result == "NO_DATA"
    assert result.received_instrument_count == 0
    assert result.first_event_at is None
    assert result.median_age_ms is None


def test_probe_reports_provider_failure_safely() -> None:
    result = run_probe(
        FakeProvider(failure=RuntimeError("secret server detail")),
        token="private-token",
        seconds=15,
        poll_interval=0,
    )

    assert result.result == "PROVIDER_ERROR"
    assert result.error_code == "provider_failure"
    assert "secret server detail" not in str(result.as_dict())


def test_probe_result_schema_contains_no_raw_market_fields() -> None:
    fields = set(ProbeResult.__dataclass_fields__)

    assert fields.isdisjoint({"symbols", "quotes", "prices", "token", "account_id"})

from datetime import UTC, datetime
from uuid import UUID

import pytest

from astraquant_domain.clocks import FixedClock
from astraquant_domain.events import EventEnvelope

EVENT_ID = UUID("00000000-0000-0000-0000-000000000010")
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000020")
NOW = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)


def test_create_deterministic_event() -> None:
    event = EventEnvelope.create(
        event_type="order.submitted",
        payload={"client_order_id": "order-1"},
        clock=FixedClock(NOW),
        event_id=EVENT_ID,
        correlation_id=CORRELATION_ID,
    )

    assert event.event_id == EVENT_ID
    assert event.correlation_id == CORRELATION_ID
    assert event.occurred_at == NOW
    assert event.schema_version == 1


def test_reject_naive_event_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EventEnvelope(
            event_id=EVENT_ID,
            correlation_id=CORRELATION_ID,
            occurred_at=datetime(2026, 7, 27, 8, 0),
            event_type="order.submitted",
            schema_version=1,
            payload={},
        )


@pytest.mark.parametrize("event_type", ["", " ", ".invalid", "invalid."])
def test_reject_invalid_event_type(event_type: str) -> None:
    with pytest.raises(ValueError, match="event_type"):
        EventEnvelope(
            event_id=EVENT_ID,
            correlation_id=CORRELATION_ID,
            occurred_at=NOW,
            event_type=event_type,
            schema_version=1,
            payload={},
        )

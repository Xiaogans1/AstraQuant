from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_domain import (
    DecisionRecord,
    InstrumentId,
    SignalAction,
    SignalFrame,
    SignalState,
)


def _signal(**changes: object) -> SignalFrame:
    decision_time = datetime(2026, 8, 6, 2, 31, tzinfo=UTC)
    values: dict[str, object] = {
        "signal_id": "sig-123",
        "instrument_id": InstrumentId.parse("159516.SZSE"),
        "event_time": decision_time - timedelta(minutes=1),
        "decision_time": decision_time,
        "expires_at": decision_time + timedelta(minutes=1),
        "action": SignalAction.BUY,
        "state": SignalState.ACTIVE,
        "reference_price": Decimal("0.703"),
        "confidence": Decimal("0.72"),
        "strategy_id": "intraday-momentum-volume",
        "strategy_version": "baseline-v1",
        "feature_version": "intraday-v1",
        "reason_codes": ("MOMENTUM_POSITIVE",),
    }
    values.update(changes)
    return SignalFrame(**values)  # type: ignore[arg-type]


def test_signal_requires_aware_ordered_times() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _signal(decision_time=datetime(2026, 8, 6, 2, 31))
    with pytest.raises(ValueError, match="expires_at"):
        _signal(expires_at=datetime(2026, 8, 6, 2, 31, tzinfo=UTC))


def test_suppressed_or_warming_signal_cannot_claim_a_trade_action() -> None:
    with pytest.raises(ValueError, match="HOLD"):
        _signal(state=SignalState.SUPPRESSED, action=SignalAction.BUY)
    with pytest.raises(ValueError, match="HOLD"):
        _signal(state=SignalState.WARMING_UP, action=SignalAction.SELL)


def test_signal_validates_confidence_and_reference_price() -> None:
    with pytest.raises(ValueError, match="confidence"):
        _signal(confidence=Decimal("1.1"))
    with pytest.raises(ValueError, match="reference_price"):
        _signal(reference_price=Decimal("0"))


def test_non_active_signal_may_have_no_reference_price_when_no_bar_exists() -> None:
    signal = _signal(
        state=SignalState.WARMING_UP,
        action=SignalAction.HOLD,
        reference_price=None,
    )

    assert signal.reference_price is None


def test_decision_record_requires_complete_trace_references() -> None:
    signal = _signal()
    with pytest.raises(ValueError, match="feature_snapshot_id"):
        DecisionRecord(
            decision_id="decision-1",
            feature_snapshot_id="",
            signal_id=signal.signal_id,
            strategy_id=signal.strategy_id,
            strategy_version=signal.strategy_version,
            market_event_time=signal.event_time,
            decision_time=signal.decision_time,
            advisory_checks=("MARKET_LIVE",),
        )


def test_valid_signal_and_decision_record_are_immutable() -> None:
    signal = _signal()
    record = DecisionRecord(
        decision_id="decision-1",
        feature_snapshot_id="feature-1",
        signal_id=signal.signal_id,
        strategy_id=signal.strategy_id,
        strategy_version=signal.strategy_version,
        market_event_time=signal.event_time,
        decision_time=signal.decision_time,
        advisory_checks=("MARKET_LIVE", "DATA_FRESH"),
    )

    assert signal.action is SignalAction.BUY
    assert record.advisory_checks == ("MARKET_LIVE", "DATA_FRESH")
    with pytest.raises(AttributeError):
        signal.signal_id = "changed"  # type: ignore[misc]

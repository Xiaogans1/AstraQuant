"""Auditable advisory signals that can never represent real broker orders."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from astraquant_domain.identifiers import InstrumentId


class SignalAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class SignalState(StrEnum):
    ACTIVE = "ACTIVE"
    SUPPRESSED = "SUPPRESSED"
    WARMING_UP = "WARMING_UP"


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_text(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class SignalFrame:
    signal_id: str
    instrument_id: InstrumentId
    event_time: datetime
    decision_time: datetime
    expires_at: datetime
    action: SignalAction
    state: SignalState
    reference_price: Decimal | None
    confidence: Decimal
    strategy_id: str
    strategy_version: str
    feature_version: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("event_time", self.event_time),
            ("decision_time", self.decision_time),
            ("expires_at", self.expires_at),
        ):
            _require_aware(name, value)
        if self.event_time > self.decision_time:
            raise ValueError("event_time must not exceed decision_time")
        if self.expires_at <= self.decision_time:
            raise ValueError("expires_at must follow decision_time")
        if self.state is not SignalState.ACTIVE and self.action is not SignalAction.HOLD:
            raise ValueError("suppressed and warming signals must use HOLD")
        if self.state is SignalState.ACTIVE and self.reference_price is None:
            raise ValueError("active signal requires reference_price")
        if self.reference_price is not None and self.reference_price <= 0:
            raise ValueError("reference_price must be positive")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be between zero and one")
        for text_name, text_value in (
            ("signal_id", self.signal_id),
            ("strategy_id", self.strategy_id),
            ("strategy_version", self.strategy_version),
            ("feature_version", self.feature_version),
        ):
            _require_text(text_name, text_value)
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must not be empty")


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_id: str
    feature_snapshot_id: str
    signal_id: str
    strategy_id: str
    strategy_version: str
    market_event_time: datetime
    decision_time: datetime
    advisory_checks: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_aware("market_event_time", self.market_event_time)
        _require_aware("decision_time", self.decision_time)
        if self.market_event_time > self.decision_time:
            raise ValueError("market_event_time must not exceed decision_time")
        for name, value in (
            ("decision_id", self.decision_id),
            ("feature_snapshot_id", self.feature_snapshot_id),
            ("signal_id", self.signal_id),
            ("strategy_id", self.strategy_id),
            ("strategy_version", self.strategy_version),
        ):
            _require_text(name, value)
        if not self.advisory_checks or any(not item.strip() for item in self.advisory_checks):
            raise ValueError("advisory_checks must not be empty")

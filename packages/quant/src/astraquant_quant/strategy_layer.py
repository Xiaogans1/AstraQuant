"""LEAN-style strategy layers: alpha -> target position -> risk -> execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from astraquant_domain import (
    DecisionRecord,
    InstrumentId,
    OrderSide,
    SignalAction,
    SignalFrame,
    SignalState,
)
from astraquant_quant.engine import QuantDecision
from astraquant_quant.features import RealtimeFeatureSnapshot, RealtimeFeatureStatus

MODEL_FEATURE_COLUMNS: Final = [
    "return_1",
    "return_3",
    "return_5",
    "return_10",
    "volatility_5",
    "vwap_deviation",
    "volume_ratio",
    "day_high_position",
    "ma5_gap",
    "ma20_gap",
]

_MODEL_SIGNAL_TTL: Final = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class PortfolioConstructor:
    max_position_percent: Decimal


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    max_position_percent: Decimal


def build_target_position(
    constructor: PortfolioConstructor,
    risk: RiskPolicy,
    *,
    signal_strength: Decimal,
    equity: Decimal,
    price: Decimal,
) -> int:
    """Convert signal strength into a share target, capped by risk and rounded to 100-share lots."""
    budget = equity * min(constructor.max_position_percent, risk.max_position_percent)
    budget = budget * signal_strength / Decimal("100")
    if budget <= 0 or price <= 0:
        return 0
    return int(budget / price / 100) * 100


def side_of(action: SignalAction) -> OrderSide | None:
    if action is SignalAction.BUY:
        return OrderSide.BUY
    if action is SignalAction.SELL:
        return OrderSide.SELL
    return None


def build_model_signal(
    *,
    instrument_id: InstrumentId,
    action: SignalAction,
    price: Decimal,
    decision_time: datetime,
    strategy_id: str,
    strategy_version: str,
    feature_version: str,
    reason: str,
    confidence: Decimal,
) -> QuantDecision:
    """Assemble the auditable decision for an approved-model signal.

    The model signal has no online feature frame, so the feature snapshot is
    a placeholder with zero completed bars.
    """
    signal = SignalFrame(
        signal_id=_stable_id(
            "model-signal",
            {
                "instrument_id": str(instrument_id),
                "price": str(price),
                "action": action.value,
                "decision_time": decision_time.isoformat(),
            },
        ),
        instrument_id=instrument_id,
        event_time=decision_time,
        decision_time=decision_time,
        expires_at=decision_time + _MODEL_SIGNAL_TTL,
        action=action,
        state=SignalState.ACTIVE,
        reference_price=price,
        confidence=confidence,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        feature_version=feature_version,
        reason_codes=(reason,),
    )
    decision_record = DecisionRecord(
        decision_id=_stable_id(
            "model-decision",
            {
                "instrument_id": str(instrument_id),
                "signal_id": signal.signal_id,
            },
        ),
        feature_snapshot_id=f"model-{signal.signal_id}",
        signal_id=signal.signal_id,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        market_event_time=decision_time,
        decision_time=decision_time,
        advisory_checks=("MARKET_LIVE", "MODEL_APPROVED"),
    )
    features = RealtimeFeatureSnapshot(
        feature_snapshot_id=f"model-{signal.signal_id}",
        status=RealtimeFeatureStatus.READY,
        completed_bar_count=0,
        latest_bar=None,
        frame=None,
        reason_codes=("MODEL_SIGNAL",),
    )
    return QuantDecision(features=features, signal=signal, decision_record=decision_record)


def _stable_id(prefix: str, payload: object) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"{prefix}-{digest[:24]}"

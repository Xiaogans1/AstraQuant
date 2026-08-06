"""Deterministic advisory engine for completed one-minute market bars."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from astraquant_data.market_bars import MarketBar
from astraquant_domain import (
    DecisionRecord,
    InstrumentId,
    SignalAction,
    SignalFrame,
    SignalState,
)
from astraquant_quant.features import (
    FEATURE_VERSION,
    RealtimeFeatureSnapshot,
    RealtimeFeatureStatus,
    build_intraday_features,
)

STRATEGY_ID: Final = "intraday-momentum-volume"
STRATEGY_VERSION: Final = "baseline-v1"
_SIGNAL_TTL: Final = timedelta(minutes=1)
_STALE_AFTER: Final = timedelta(seconds=120)


@dataclass(frozen=True, slots=True)
class QuantDecision:
    features: RealtimeFeatureSnapshot
    signal: SignalFrame
    decision_record: DecisionRecord


def evaluate_intraday_signal(
    instrument_id: InstrumentId,
    bars: list[MarketBar],
    decision_time: datetime,
    *,
    market_live: bool,
) -> QuantDecision:
    features = build_intraday_features(instrument_id, bars, decision_time)
    latest = features.latest_bar
    reference_price = None if latest is None else latest.close
    event_time = decision_time if latest is None else latest.timestamp
    checks: list[str] = []
    reasons: tuple[str, ...]

    if not market_live:
        state = SignalState.SUPPRESSED
        action = SignalAction.HOLD
        confidence = Decimal("0")
        reasons = ("MARKET_NOT_LIVE",)
        checks.append("MARKET_NOT_LIVE")
    elif features.status is RealtimeFeatureStatus.WARMING_UP:
        state = SignalState.WARMING_UP
        action = SignalAction.HOLD
        confidence = Decimal("0")
        reasons = features.reason_codes
        checks.extend(("MARKET_LIVE", "FEATURES_WARMING_UP"))
    elif (
        latest is not None
        and decision_time - (latest.timestamp + timedelta(minutes=1)) > _STALE_AFTER
    ):
        state = SignalState.SUPPRESSED
        action = SignalAction.HOLD
        confidence = Decimal("0")
        reasons = ("MARKET_DATA_STALE",)
        checks.extend(("MARKET_LIVE", "MARKET_DATA_STALE"))
    else:
        state = SignalState.ACTIVE
        action, confidence, reasons = _baseline_action(features)
        checks.extend(("MARKET_LIVE", "DATA_FRESH", "FEATURES_READY", "BASELINE_VALID"))

    signal_payload = {
        "feature_snapshot_id": features.feature_snapshot_id,
        "instrument_id": str(instrument_id),
        "decision_time": decision_time.isoformat(),
        "action": action.value,
        "state": state.value,
        "reasons": reasons,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
    }
    signal_id = _stable_id("signal", signal_payload)
    signal = SignalFrame(
        signal_id=signal_id,
        instrument_id=instrument_id,
        event_time=event_time,
        decision_time=decision_time,
        expires_at=decision_time + _SIGNAL_TTL,
        action=action,
        state=state,
        reference_price=reference_price,
        confidence=confidence,
        strategy_id=STRATEGY_ID,
        strategy_version=STRATEGY_VERSION,
        feature_version=FEATURE_VERSION,
        reason_codes=reasons,
    )
    decision_record = DecisionRecord(
        decision_id=_stable_id(
            "decision",
            {
                "feature_snapshot_id": features.feature_snapshot_id,
                "signal_id": signal_id,
                "checks": checks,
            },
        ),
        feature_snapshot_id=features.feature_snapshot_id,
        signal_id=signal_id,
        strategy_id=STRATEGY_ID,
        strategy_version=STRATEGY_VERSION,
        market_event_time=event_time,
        decision_time=decision_time,
        advisory_checks=tuple(checks),
    )
    return QuantDecision(
        features=features,
        signal=signal,
        decision_record=decision_record,
    )


def _baseline_action(
    features: RealtimeFeatureSnapshot,
) -> tuple[SignalAction, Decimal, tuple[str, ...]]:
    assert features.frame is not None
    values = features.frame.rows[0].values
    return_5m = _decimal(values["return_5m"])
    ma_5_gap = _decimal(values["ma_5_gap"])
    ma_20_gap = _decimal(values["ma_20_gap"])
    volume_ratio = _decimal(values["volume_ratio_20"])
    if (
        return_5m >= Decimal("0.003")
        and ma_5_gap > 0
        and ma_20_gap > 0
        and volume_ratio >= Decimal("1.5")
    ):
        return SignalAction.BUY, Decimal("0.65"), ("MOMENTUM_VOLUME_BREAKOUT",)
    if return_5m <= Decimal("-0.003") and ma_5_gap < 0:
        return SignalAction.SELL, Decimal("0.65"), ("DOWNTREND_EXIT",)
    return SignalAction.HOLD, Decimal("0.50"), ("NO_CONFIRMED_EDGE",)


def _decimal(value: float | None) -> Decimal:
    return Decimal("0") if value is None else Decimal(str(value))


def _stable_id(prefix: str, payload: object) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"{prefix}-{digest[:24]}"

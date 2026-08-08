from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_domain import InstrumentId, OrderSide, SignalAction, SignalState
from astraquant_quant import QuantDecision
from astraquant_quant.features import RealtimeFeatureStatus
from astraquant_quant.strategy_layer import (
    MODEL_FEATURE_COLUMNS,
    PortfolioConstructor,
    RiskPolicy,
    build_model_signal,
    build_target_position,
    side_of,
)


def test_target_position_is_capped_by_risk_budget() -> None:
    target = build_target_position(
        PortfolioConstructor(max_position_percent=Decimal("20")),
        RiskPolicy(max_position_percent=Decimal("10")),
        signal_strength=Decimal("1"),
        equity=Decimal("100000"),
        price=Decimal("10"),
    )
    assert target == 1000


def test_target_position_scales_with_signal_strength() -> None:
    target = build_target_position(
        PortfolioConstructor(max_position_percent=Decimal("20")),
        RiskPolicy(max_position_percent=Decimal("20")),
        signal_strength=Decimal("0.5"),
        equity=Decimal("100000"),
        price=Decimal("10"),
    )
    assert target == 1000


def test_target_position_returns_zero_without_budget() -> None:
    target = build_target_position(
        PortfolioConstructor(max_position_percent=Decimal("20")),
        RiskPolicy(max_position_percent=Decimal("20")),
        signal_strength=Decimal("0.01"),
        equity=Decimal("100000"),
        price=Decimal("10"),
    )
    assert target == 0


def test_side_of_maps_signal_actions() -> None:
    assert side_of(SignalAction.BUY) is OrderSide.BUY
    assert side_of(SignalAction.SELL) is OrderSide.SELL
    assert side_of(SignalAction.HOLD) is None


def _bars(count: int = 35) -> list[MarketBar]:
    start = datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    return [
        MarketBar(
            timestamp=start + timedelta(minutes=index),
            open=Decimal("10"),
            high=Decimal("10"),
            low=Decimal("10"),
            close=Decimal("10"),
            volume=Decimal("100"),
            turnover=Decimal("1000"),
            previous_close=Decimal("10"),
        )
        for index in range(count)
    ]


def test_model_feature_columns_are_supported_by_research_rows() -> None:
    from astraquant_quant.research_features import build_feature_rows

    row = build_feature_rows(_bars())[-1]
    assert set(MODEL_FEATURE_COLUMNS) <= set(row)


def test_build_model_signal_assembles_an_auditable_decision() -> None:
    decision = build_model_signal(
        instrument_id=InstrumentId.parse("159516.SZSE"),
        action=SignalAction.BUY,
        price=Decimal("9.70"),
        decision_time=datetime(2026, 8, 7, 2, 31, tzinfo=UTC),
        strategy_id="microstructure-lgbm",
        strategy_version="lgbm-v1",
        feature_version="minute-v1",
        reason="model lgbm-v1 up-probability 0.72",
        confidence=Decimal("0.72"),
    )
    signal = decision.signal
    assert signal.action is SignalAction.BUY
    assert signal.state is SignalState.ACTIVE
    assert signal.reference_price == Decimal("9.70")
    assert signal.strategy_id == "microstructure-lgbm"
    assert signal.strategy_version == "lgbm-v1"
    assert signal.feature_version == "minute-v1"
    assert signal.confidence == Decimal("0.72")
    assert signal.reason_codes == ("model lgbm-v1 up-probability 0.72",)
    assert signal.expires_at == signal.decision_time + timedelta(minutes=1)
    assert decision.decision_record.strategy_id == "microstructure-lgbm"
    assert decision.decision_record.advisory_checks == ("MARKET_LIVE", "MODEL_APPROVED")
    assert decision.decision_record.feature_snapshot_id == decision.features.feature_snapshot_id
    assert decision.features.status is RealtimeFeatureStatus.READY
    assert decision.features.frame is None


def test_build_model_signal_hold_has_zero_confidence() -> None:
    decision = build_model_signal(
        instrument_id=InstrumentId.parse("159516.SZSE"),
        action=SignalAction.HOLD,
        price=Decimal("9.70"),
        decision_time=datetime(2026, 8, 7, 2, 31, tzinfo=UTC),
        strategy_id="microstructure-lgbm",
        strategy_version="lgbm-v1",
        feature_version="minute-v1",
        reason="model lgbm-v1 up-probability 0.50",
        confidence=Decimal("0"),
    )
    assert decision.signal.action is SignalAction.HOLD
    assert decision.signal.confidence == Decimal("0")
    assert side_of(decision.signal.action) is None


def test_build_model_signal_is_deterministic() -> None:
    def build() -> QuantDecision:
        return build_model_signal(
            instrument_id=InstrumentId.parse("159516.SZSE"),
            action=SignalAction.BUY,
            price=Decimal("9.70"),
            decision_time=datetime(2026, 8, 7, 2, 31, tzinfo=UTC),
            strategy_id="microstructure-lgbm",
            strategy_version="lgbm-v1",
            feature_version="minute-v1",
            reason="model lgbm-v1 up-probability 0.72",
            confidence=Decimal("0.72"),
        )

    first = build()
    second = build()
    assert first.signal.signal_id == second.signal.signal_id
    assert first.decision_record.decision_id == second.decision_record.decision_id

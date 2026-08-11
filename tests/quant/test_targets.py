from __future__ import annotations

from decimal import Decimal

from astraquant_quant.targets import (
    ForecastEvidenceStatus,
    ForecastInput,
    ForecastTargetPolicy,
    TargetReason,
    build_base_target,
)


def _policy() -> ForecastTargetPolicy:
    return ForecastTargetPolicy(
        enter_probability=Decimal("0.55"),
        exit_probability=Decimal("0.45"),
        max_position_percent=Decimal("20"),
        round_trip_cost_rate=Decimal("0.0005"),
        lot_size=100,
    )


def _forecast(
    *,
    probability: str,
    expected_return: str,
    evidence: ForecastEvidenceStatus = ForecastEvidenceStatus.VALIDATED,
) -> ForecastInput:
    return ForecastInput(
        forecast_id="forecast-1",
        probability_up=Decimal(probability),
        expected_return=Decimal(expected_return),
        evidence_status=evidence,
    )


def test_validated_forecast_scales_target_by_probability_and_risk_budget() -> None:
    target = build_base_target(
        _forecast(probability="0.75", expected_return="0.01"),
        _policy(),
        current_target_quantity=0,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )

    assert target.target_quantity == 1000
    assert target.signal_strength == Decimal("0.5")
    assert target.reason is TargetReason.FORECAST_TARGET


def test_insufficient_evidence_keeps_current_base_target() -> None:
    target = build_base_target(
        _forecast(
            probability="0.90",
            expected_return="0.02",
            evidence=ForecastEvidenceStatus.INSUFFICIENT_EVIDENCE,
        ),
        _policy(),
        current_target_quantity=1200,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )

    assert target.target_quantity == 1200
    assert target.reason is TargetReason.INSUFFICIENT_EVIDENCE


def test_forecast_without_net_edge_keeps_current_base_target() -> None:
    target = build_base_target(
        _forecast(probability="0.80", expected_return="0.0004"),
        _policy(),
        current_target_quantity=800,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )

    assert target.target_quantity == 800
    assert target.reason is TargetReason.NO_NET_EDGE


def test_probability_inside_no_trade_band_keeps_current_base_target() -> None:
    target = build_base_target(
        _forecast(probability="0.52", expected_return="0.01"),
        _policy(),
        current_target_quantity=600,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )

    assert target.target_quantity == 600
    assert target.reason is TargetReason.NO_TRADE_BAND


def test_validated_bearish_forecast_targets_zero() -> None:
    target = build_base_target(
        _forecast(probability="0.40", expected_return="-0.01"),
        _policy(),
        current_target_quantity=1000,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )

    assert target.target_quantity == 0
    assert target.reason is TargetReason.FORECAST_TARGET

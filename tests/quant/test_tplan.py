from __future__ import annotations

from decimal import Decimal

from astraquant_domain import OrderSide
from astraquant_quant.targets import ForecastEvidenceStatus
from astraquant_quant.tplan import (
    TPlanReason,
    TPlanRequest,
    TPlanStatus,
    TPlanType,
    build_tplan,
)


def _request(
    plan_type: TPlanType,
    **changes: object,
) -> TPlanRequest:
    values: dict[str, object] = {
        "plan_id": "tplan-1",
        "plan_type": plan_type,
        "base_target_quantity": 2000,
        "actual_quantity": 2000,
        "opening_sellable_quantity": 1000,
        "reserved_opening_quantity": 200,
        "requested_quantity": 1000,
        "cash_available": Decimal("0"),
        "price": Decimal("10"),
        "expected_incremental_return": Decimal("0.002"),
        "round_trip_cost_rate": Decimal("0.0005"),
        "evidence_status": ForecastEvidenceStatus.VALIDATED,
        "lot_size": 100,
    }
    values.update(changes)
    return TPlanRequest(**values)  # type: ignore[arg-type]


def test_sell_then_buyback_uses_only_unreserved_opening_base() -> None:
    draft = build_tplan(_request(TPlanType.SELL_THEN_BUYBACK))

    assert draft.status is TPlanStatus.READY
    assert draft.planned_quantity == 800
    assert draft.opening_quantity_to_reserve == 800
    assert draft.first_side is OrderSide.SELL
    assert draft.second_side is OrderSide.BUY
    assert draft.base_target_quantity == 2000


def test_buy_then_sell_base_is_limited_by_cash_and_reserves_opening_lots() -> None:
    draft = build_tplan(
        _request(
            TPlanType.BUY_THEN_SELL_BASE,
            reserved_opening_quantity=0,
            cash_available=Decimal("5500"),
        )
    )

    assert draft.status is TPlanStatus.READY
    assert draft.planned_quantity == 500
    assert draft.opening_quantity_to_reserve == 500
    assert draft.first_side is OrderSide.BUY
    assert draft.second_side is OrderSide.SELL
    assert TPlanReason.CASH_LIMIT in draft.reasons


def test_tplan_holds_when_forecast_evidence_is_insufficient() -> None:
    draft = build_tplan(
        _request(
            TPlanType.SELL_THEN_BUYBACK,
            evidence_status=ForecastEvidenceStatus.INSUFFICIENT_EVIDENCE,
        )
    )

    assert draft.status is TPlanStatus.HOLD
    assert draft.planned_quantity == 0
    assert draft.reasons == (TPlanReason.INSUFFICIENT_EVIDENCE,)


def test_tplan_holds_when_incremental_edge_does_not_cover_cost() -> None:
    draft = build_tplan(
        _request(
            TPlanType.SELL_THEN_BUYBACK,
            expected_incremental_return=Decimal("0.0005"),
        )
    )

    assert draft.status is TPlanStatus.HOLD
    assert draft.reasons == (TPlanReason.NO_NET_EDGE,)


def test_tplan_holds_without_an_unreserved_opening_lot() -> None:
    draft = build_tplan(
        _request(
            TPlanType.SELL_THEN_BUYBACK,
            opening_sellable_quantity=200,
            reserved_opening_quantity=200,
        )
    )

    assert draft.status is TPlanStatus.HOLD
    assert draft.reasons == (TPlanReason.NO_OPENING_SELLABLE,)

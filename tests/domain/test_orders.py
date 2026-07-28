from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from astraquant_domain.identifiers import InstrumentId
from astraquant_domain.orders import (
    Environment,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    transition_order,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
INSTRUMENT = InstrumentId.parse("RB2610.SHFE")


def test_virtual_order_environments_never_include_live_trading() -> None:
    assert {environment.value for environment in Environment} == {"BACKTEST", "PAPER"}
    assert "LIVE" not in Path(
        "packages/domain/src/astraquant_domain/orders.py"
    ).read_text(encoding="utf-8")


def test_create_limit_order() -> None:
    request = OrderRequest(
        client_order_id=ORDER_ID,
        instrument_id=INSTRUMENT,
        environment=Environment.PAPER,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        time_in_force=TimeInForce.DAY,
        limit_price=Decimal("3500.5"),
    )

    assert request.quantity == Decimal("2")
    assert request.limit_price == Decimal("3500.5")


def test_limit_order_requires_price() -> None:
    with pytest.raises(ValueError, match="limit_price is required"):
        OrderRequest(
            client_order_id=ORDER_ID,
            instrument_id=INSTRUMENT,
            environment=Environment.PAPER,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            time_in_force=TimeInForce.DAY,
        )


def test_market_order_rejects_limit_price() -> None:
    with pytest.raises(ValueError, match="limit_price must be omitted"):
        OrderRequest(
            client_order_id=ORDER_ID,
            instrument_id=INSTRUMENT,
            environment=Environment.PAPER,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            time_in_force=TimeInForce.IOC,
            limit_price=Decimal("3500"),
        )


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1")])
def test_order_quantity_must_be_positive(quantity: Decimal) -> None:
    with pytest.raises(ValueError, match="quantity must be positive"):
        OrderRequest(
            client_order_id=ORDER_ID,
            instrument_id=INSTRUMENT,
            environment=Environment.PAPER,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
            time_in_force=TimeInForce.IOC,
        )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderStatus.PENDING_SUBMIT, OrderStatus.SUBMITTED),
        (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED),
        (OrderStatus.SUBMITTED, OrderStatus.CANCEL_PENDING),
        (OrderStatus.CANCEL_PENDING, OrderStatus.CANCELED),
    ],
)
def test_allow_valid_order_transition(current: OrderStatus, target: OrderStatus) -> None:
    assert transition_order(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderStatus.FILLED, OrderStatus.CANCELED),
        (OrderStatus.CANCELED, OrderStatus.SUBMITTED),
        (OrderStatus.REJECTED, OrderStatus.SUBMITTED),
        (OrderStatus.PENDING_SUBMIT, OrderStatus.FILLED),
    ],
)
def test_reject_invalid_order_transition(current: OrderStatus, target: OrderStatus) -> None:
    with pytest.raises(ValueError, match="Invalid order transition"):
        transition_order(current, target)

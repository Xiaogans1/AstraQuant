from decimal import Decimal

from astraquant_domain import OrderSide
from astraquant_paper.fees import FeeSchedule


def test_buy_fee_applies_minimum_commission_without_stamp_duty() -> None:
    fees = FeeSchedule().calculate(
        side=OrderSide.BUY,
        gross_amount=Decimal("1000"),
        stamp_duty_exempt=False,
    )

    assert fees.commission == Decimal("5.00")
    assert fees.stamp_duty == Decimal("0.00")
    assert fees.transfer_fee == Decimal("0.01")
    assert fees.total == Decimal("5.01")


def test_stock_sell_fee_includes_stamp_duty() -> None:
    fees = FeeSchedule().calculate(
        side=OrderSide.SELL,
        gross_amount=Decimal("10000"),
        stamp_duty_exempt=False,
    )

    assert fees.commission == Decimal("5.00")
    assert fees.stamp_duty == Decimal("5.00")
    assert fees.transfer_fee == Decimal("0.10")


def test_etf_sell_can_be_marked_stamp_duty_exempt() -> None:
    fees = FeeSchedule().calculate(
        side=OrderSide.SELL,
        gross_amount=Decimal("10000"),
        stamp_duty_exempt=True,
    )

    assert fees.stamp_duty == Decimal("0.00")

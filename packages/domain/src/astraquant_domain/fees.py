"""Configurable fee rules shared by backtest, Paper, and Live runtimes.

The fee schedule is a user-configurable trading-cost model: commission rate,
per-order minimum commission, sell-side stamp duty and transfer fee. Runtimes
never hard-code a schedule; they consume whatever the user has configured
(``GET/PUT /v1/paper/fee-config`` persists it in the Paper service).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from astraquant_domain.orders import OrderSide

_CENT = Decimal("0.01")


def _money(value: Decimal, *, minimum_if_positive: bool = False) -> Decimal:
    rounded = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    if minimum_if_positive and value > 0 and rounded == 0:
        return _CENT
    return rounded


@dataclass(frozen=True, slots=True)
class FeeBreakdown:
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.stamp_duty + self.transfer_fee


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    commission_rate: Decimal = Decimal("0.00025")
    minimum_commission: Decimal = Decimal("0")
    stamp_duty_rate: Decimal = Decimal("0.0005")
    transfer_fee_rate: Decimal = Decimal("0.00001")

    def calculate(
        self,
        *,
        side: OrderSide,
        gross_amount: Decimal,
        stamp_duty_exempt: bool,
    ) -> FeeBreakdown:
        if gross_amount <= 0:
            raise ValueError("gross_amount must be positive")
        commission = max(
            _money(gross_amount * self.commission_rate),
            self.minimum_commission,
        ).quantize(_CENT)
        stamp_duty = (
            Decimal("0")
            if side is OrderSide.BUY or stamp_duty_exempt
            else gross_amount * self.stamp_duty_rate
        )
        transfer_fee = gross_amount * self.transfer_fee_rate
        return FeeBreakdown(
            commission=commission,
            stamp_duty=_money(stamp_duty),
            transfer_fee=_money(transfer_fee, minimum_if_positive=True),
        )

"""Immutable portfolio and virtual-trading contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from astraquant_domain.identifiers import InstrumentId
from astraquant_domain.orders import OrderSide, OrderStatus

_PERCENT_QUANTUM = Decimal("0.0001")


def _require_text(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class AccountMode(StrEnum):
    PAPER = "PAPER"
    MIRROR = "MIRROR"


@dataclass(frozen=True, slots=True)
class PaperAccount:
    account_id: str
    name: str
    mode: AccountMode
    initial_cash: Decimal
    cash: Decimal
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", _require_text("account_id", self.account_id))
        object.__setattr__(self, "name", _require_text("name", self.name))
        if self.initial_cash < 0:
            raise ValueError("initial_cash must be non-negative")
        if self.cash < 0:
            raise ValueError("cash must be non-negative")
        _require_aware("created_at", self.created_at)
        _require_aware("updated_at", self.updated_at)


@dataclass(frozen=True, slots=True)
class Position:
    account_id: str
    instrument_id: InstrumentId
    name: str | None
    quantity: int
    available_quantity: int
    average_cost: Decimal
    last_price: Decimal | None = None
    marked_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", _require_text("account_id", self.account_id))
        if self.name is not None:
            normalized_name = self.name.strip()
            object.__setattr__(self, "name", normalized_name or None)
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.available_quantity < 0:
            raise ValueError("available_quantity must be non-negative")
        if self.available_quantity > self.quantity:
            raise ValueError("available_quantity must not exceed quantity")
        if self.average_cost < 0:
            raise ValueError("average_cost must be non-negative")
        if self.last_price is not None and self.last_price <= 0:
            raise ValueError("last_price must be positive")
        if self.marked_at is not None:
            _require_aware("marked_at", self.marked_at)

    @property
    def mark_price(self) -> Decimal:
        return self.last_price if self.last_price is not None else self.average_cost

    @property
    def market_value(self) -> Decimal:
        return self.mark_price * self.quantity

    @property
    def cost_basis(self) -> Decimal:
        return self.average_cost * self.quantity

    @property
    def unrealized_pnl(self) -> Decimal:
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_percent(self) -> Decimal | None:
        if self.cost_basis == 0:
            return None
        return (self.unrealized_pnl / self.cost_basis * 100).quantize(_PERCENT_QUANTUM)


@dataclass(frozen=True, slots=True)
class PaperOrder:
    order_id: str
    account_id: str
    idempotency_key: str
    instrument_id: InstrumentId
    side: OrderSide
    quantity: int
    status: OrderStatus
    submitted_at: datetime
    updated_at: datetime
    reject_reason: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("order_id", "account_id", "idempotency_key"):
            object.__setattr__(
                self, field_name, _require_text(field_name, getattr(self, field_name))
            )
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        _require_aware("submitted_at", self.submitted_at)
        _require_aware("updated_at", self.updated_at)


@dataclass(frozen=True, slots=True)
class PaperFill:
    fill_id: str
    order_id: str
    account_id: str
    instrument_id: InstrumentId
    side: OrderSide
    quantity: int
    price: Decimal
    gross_amount: Decimal
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    occurred_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("fill_id", "order_id", "account_id"):
            object.__setattr__(
                self, field_name, _require_text(field_name, getattr(self, field_name))
            )
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.price <= 0 or self.gross_amount <= 0:
            raise ValueError("fill price and gross_amount must be positive")
        if any(value < 0 for value in (self.commission, self.stamp_duty, self.transfer_fee)):
            raise ValueError("fill fees must be non-negative")
        _require_aware("occurred_at", self.occurred_at)

    @property
    def total_fee(self) -> Decimal:
        return self.commission + self.stamp_duty + self.transfer_fee

    @property
    def net_cash_flow(self) -> Decimal:
        if self.side is OrderSide.BUY:
            return -(self.gross_amount + self.total_fee)
        return self.gross_amount - self.total_fee


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    snapshot_id: str
    account_id: str
    cash: Decimal
    market_value: Decimal
    total_equity: Decimal
    initial_equity: Decimal
    total_pnl: Decimal
    total_pnl_percent: Decimal | None
    as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _require_text("snapshot_id", self.snapshot_id))
        object.__setattr__(self, "account_id", _require_text("account_id", self.account_id))
        if self.cash < 0 or self.market_value < 0 or self.total_equity < 0:
            raise ValueError("snapshot balances must be non-negative")
        if self.total_equity != self.cash + self.market_value:
            raise ValueError("total_equity must equal cash plus market_value")
        _require_aware("as_of", self.as_of)

    @classmethod
    def create(
        cls,
        *,
        snapshot_id: str,
        account_id: str,
        cash: Decimal,
        initial_equity: Decimal,
        positions: tuple[Position, ...],
        as_of: datetime,
    ) -> Self:
        market_value = sum((position.market_value for position in positions), Decimal("0"))
        total_equity = cash + market_value
        total_pnl = total_equity - initial_equity
        total_pnl_percent = (
            None
            if initial_equity == 0
            else (total_pnl / initial_equity * 100).quantize(_PERCENT_QUANTUM)
        )
        return cls(
            snapshot_id=snapshot_id,
            account_id=account_id,
            cash=cash,
            market_value=market_value,
            total_equity=total_equity,
            initial_equity=initial_equity,
            total_pnl=total_pnl,
            total_pnl_percent=total_pnl_percent,
            as_of=as_of,
        )

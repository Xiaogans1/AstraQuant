"""Public API schemas for local Paper accounts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from astraquant_domain import (
    AccountMode,
    OrderSide,
    OrderStatus,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PortfolioSnapshot,
    Position,
)
from astraquant_paper import LedgerState


class AccountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    mode: AccountMode = AccountMode.PAPER
    initial_cash: Decimal = Field(ge=0)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized


class OpeningPositionRequest(BaseModel):
    instrument_id: str
    name: str | None = Field(default=None, max_length=200)
    quantity: int = Field(gt=0)
    available_quantity: int = Field(ge=0)
    average_cost: Decimal = Field(ge=0)


class MarketOrderRequest(BaseModel):
    instrument_id: str
    side: OrderSide
    quantity: int = Field(gt=0)
    name: str | None = Field(default=None, max_length=200)
    stamp_duty_exempt: bool = False


class AccountView(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    name: str
    mode: AccountMode
    initial_cash: Decimal
    cash: Decimal
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, item: PaperAccount) -> AccountView:
        return cls(**{field: getattr(item, field) for field in cls.model_fields})


class PositionView(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_id: str
    name: str | None
    quantity: int
    available_quantity: int
    average_cost: Decimal
    last_price: Decimal | None
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_percent: Decimal | None
    marked_at: datetime | None

    @classmethod
    def from_domain(cls, item: Position) -> PositionView:
        return cls(
            instrument_id=str(item.instrument_id),
            name=item.name,
            quantity=item.quantity,
            available_quantity=item.available_quantity,
            average_cost=item.average_cost,
            last_price=item.last_price,
            market_value=item.market_value,
            unrealized_pnl=item.unrealized_pnl,
            unrealized_pnl_percent=item.unrealized_pnl_percent,
            marked_at=item.marked_at,
        )


class OrderView(BaseModel):
    order_id: str
    account_id: str
    idempotency_key: str
    instrument_id: str
    side: OrderSide
    quantity: int
    status: OrderStatus
    submitted_at: datetime
    updated_at: datetime
    reject_reason: str | None

    @classmethod
    def from_domain(cls, item: PaperOrder) -> OrderView:
        return cls(
            order_id=item.order_id,
            account_id=item.account_id,
            idempotency_key=item.idempotency_key,
            instrument_id=str(item.instrument_id),
            side=item.side,
            quantity=item.quantity,
            status=item.status,
            submitted_at=item.submitted_at,
            updated_at=item.updated_at,
            reject_reason=item.reject_reason,
        )


class FillView(BaseModel):
    fill_id: str
    order_id: str
    instrument_id: str
    side: OrderSide
    quantity: int
    price: Decimal
    gross_amount: Decimal
    total_fee: Decimal
    net_cash_flow: Decimal
    occurred_at: datetime

    @classmethod
    def from_domain(cls, item: PaperFill) -> FillView:
        return cls(
            fill_id=item.fill_id,
            order_id=item.order_id,
            instrument_id=str(item.instrument_id),
            side=item.side,
            quantity=item.quantity,
            price=item.price,
            gross_amount=item.gross_amount,
            total_fee=item.total_fee,
            net_cash_flow=item.net_cash_flow,
            occurred_at=item.occurred_at,
        )


class EquityView(BaseModel):
    snapshot_id: str
    cash: Decimal
    market_value: Decimal
    total_equity: Decimal
    initial_equity: Decimal
    total_pnl: Decimal
    total_pnl_percent: Decimal | None
    as_of: datetime

    @classmethod
    def from_domain(cls, item: PortfolioSnapshot) -> EquityView:
        return cls(**{field: getattr(item, field) for field in cls.model_fields})


class AccountSummaryView(AccountView):
    initial_equity: Decimal
    total_equity: Decimal
    total_pnl: Decimal


class AccountDetailView(BaseModel):
    account: AccountView
    positions: list[PositionView]
    latest_equity: EquityView | None

    @classmethod
    def from_state(cls, state: LedgerState) -> AccountDetailView:
        return cls(
            account=AccountView.from_domain(state.account),
            positions=[PositionView.from_domain(item) for item in state.positions],
            latest_equity=(
                None if not state.snapshots else EquityView.from_domain(state.snapshots[-1])
            ),
        )


class OrderExecutionView(BaseModel):
    order: OrderView
    fill: FillView | None
    portfolio: AccountDetailView


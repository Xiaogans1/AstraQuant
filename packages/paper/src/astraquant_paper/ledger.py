"""Pure deterministic state transitions for local virtual trading."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from astraquant_domain import (
    InstrumentId,
    LiveQuote,
    OrderSide,
    OrderStatus,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PortfolioSnapshot,
    Position,
)
from astraquant_paper.fees import FeeBreakdown, FeeSchedule


class RejectionCode(StrEnum):
    INSUFFICIENT_CASH = "insufficient_cash"
    INSUFFICIENT_AVAILABLE_QUANTITY = "insufficient_available_quantity"


@dataclass(frozen=True, slots=True)
class LedgerState:
    account: PaperAccount
    initial_equity: Decimal | None = None
    positions: tuple[Position, ...] = ()
    orders: tuple[PaperOrder, ...] = ()
    fills: tuple[PaperFill, ...] = ()
    snapshots: tuple[PortfolioSnapshot, ...] = ()

    def __post_init__(self) -> None:
        if self.initial_equity is None:
            object.__setattr__(self, "initial_equity", self.account.initial_cash)
        elif self.initial_equity < 0:
            raise ValueError("initial_equity must be non-negative")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    state: LedgerState
    order: PaperOrder
    fill: PaperFill | None


class PaperLedger:
    def __init__(self, fee_schedule: FeeSchedule | None = None) -> None:
        self._fee_schedule = fee_schedule or FeeSchedule()

    def add_opening_position(
        self,
        state: LedgerState,
        *,
        instrument_id: InstrumentId,
        name: str | None,
        quantity: int,
        available_quantity: int,
        average_cost: Decimal,
    ) -> LedgerState:
        if self._find_position(state, instrument_id) is not None:
            raise ValueError("opening position already exists")
        position = Position(
            account_id=state.account.account_id,
            instrument_id=instrument_id,
            name=name,
            quantity=quantity,
            available_quantity=available_quantity,
            average_cost=average_cost,
        )
        assert state.initial_equity is not None
        return replace(
            state,
            initial_equity=state.initial_equity + position.cost_basis,
            positions=(*state.positions, position),
        )

    def mark_to_market(
        self,
        state: LedgerState,
        quotes: tuple[LiveQuote, ...],
        *,
        now: datetime,
    ) -> LedgerState:
        quote_by_instrument = {str(item.instrument_id): item for item in quotes}
        marked_positions = tuple(
            self._mark_position(position, quote_by_instrument.get(str(position.instrument_id)))
            for position in state.positions
        )
        snapshot = self._snapshot(state.account, state.initial_equity, marked_positions, now)
        return replace(
            state,
            positions=marked_positions,
            snapshots=(*state.snapshots, snapshot),
        )

    def execute_market_order(
        self,
        state: LedgerState,
        *,
        quote: LiveQuote,
        side: OrderSide,
        quantity: int,
        idempotency_key: str,
        now: datetime,
        name: str | None = None,
        stamp_duty_exempt: bool = False,
    ) -> ExecutionResult:
        duplicate = next(
            (item for item in state.orders if item.idempotency_key == idempotency_key),
            None,
        )
        if duplicate is not None:
            fill = next((item for item in state.fills if item.order_id == duplicate.order_id), None)
            return ExecutionResult(state=state, order=duplicate, fill=fill)
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        price = self._execution_price(quote, side)
        gross_amount = price * quantity
        fees = self._fee_schedule.calculate(
            side=side,
            gross_amount=gross_amount,
            stamp_duty_exempt=stamp_duty_exempt,
        )
        rejection = self._rejection(state, quote.instrument_id, side, quantity, gross_amount, fees)
        order_id = str(uuid4())
        order = PaperOrder(
            order_id=order_id,
            account_id=state.account.account_id,
            idempotency_key=idempotency_key,
            instrument_id=quote.instrument_id,
            side=side,
            quantity=quantity,
            status=OrderStatus.REJECTED if rejection is not None else OrderStatus.FILLED,
            submitted_at=now,
            updated_at=now,
            reject_reason=None if rejection is None else rejection.value,
        )
        if rejection is not None:
            rejected_state = replace(state, orders=(*state.orders, order))
            return ExecutionResult(state=rejected_state, order=order, fill=None)

        fill = PaperFill(
            fill_id=str(uuid4()),
            order_id=order.order_id,
            account_id=state.account.account_id,
            instrument_id=quote.instrument_id,
            side=side,
            quantity=quantity,
            price=price,
            gross_amount=gross_amount,
            commission=fees.commission,
            stamp_duty=fees.stamp_duty,
            transfer_fee=fees.transfer_fee,
            occurred_at=now,
        )
        next_account = replace(
            state.account,
            cash=state.account.cash + fill.net_cash_flow,
            updated_at=now,
        )
        positions = self._apply_position_fill(
            state,
            fill,
            name=name,
            quote=quote,
        )
        snapshot = self._snapshot(next_account, state.initial_equity, positions, now)
        next_state = replace(
            state,
            account=next_account,
            positions=positions,
            orders=(*state.orders, order),
            fills=(*state.fills, fill),
            snapshots=(*state.snapshots, snapshot),
        )
        return ExecutionResult(state=next_state, order=order, fill=fill)

    @staticmethod
    def _execution_price(quote: LiveQuote, side: OrderSide) -> Decimal:
        if side is OrderSide.BUY and quote.ask:
            return quote.ask[0].price
        if side is OrderSide.SELL and quote.bid:
            return quote.bid[0].price
        return quote.last_price

    @staticmethod
    def _find_position(state: LedgerState, instrument_id: InstrumentId) -> Position | None:
        return next(
            (item for item in state.positions if item.instrument_id == instrument_id),
            None,
        )

    def _rejection(
        self,
        state: LedgerState,
        instrument_id: InstrumentId,
        side: OrderSide,
        quantity: int,
        gross_amount: Decimal,
        fees: FeeBreakdown,
    ) -> RejectionCode | None:
        if side is OrderSide.BUY:
            required_cash = gross_amount + fees.total
            return RejectionCode.INSUFFICIENT_CASH if state.account.cash < required_cash else None
        position = self._find_position(state, instrument_id)
        if position is None or position.available_quantity < quantity:
            return RejectionCode.INSUFFICIENT_AVAILABLE_QUANTITY
        return None

    @staticmethod
    def _mark_position(position: Position, quote: LiveQuote | None) -> Position:
        if quote is None:
            return position
        return replace(position, last_price=quote.last_price, marked_at=quote.event_time)

    def _apply_position_fill(
        self,
        state: LedgerState,
        fill: PaperFill,
        *,
        name: str | None,
        quote: LiveQuote,
    ) -> tuple[Position, ...]:
        current = self._find_position(state, fill.instrument_id)
        others = tuple(item for item in state.positions if item.instrument_id != fill.instrument_id)
        if fill.side is OrderSide.BUY:
            old_quantity = 0 if current is None else current.quantity
            old_cost = Decimal("0") if current is None else current.average_cost * old_quantity
            new_quantity = old_quantity + fill.quantity
            average_cost = (old_cost + fill.gross_amount + fill.total_fee) / new_quantity
            position = Position(
                account_id=state.account.account_id,
                instrument_id=fill.instrument_id,
                name=name if current is None else current.name,
                quantity=new_quantity,
                available_quantity=0 if current is None else current.available_quantity,
                average_cost=average_cost,
                last_price=quote.last_price,
                marked_at=quote.event_time,
            )
            return (*others, position)
        assert current is not None
        remaining = current.quantity - fill.quantity
        if remaining == 0:
            return others
        position = replace(
            current,
            quantity=remaining,
            available_quantity=current.available_quantity - fill.quantity,
            last_price=quote.last_price,
            marked_at=quote.event_time,
        )
        return (*others, position)

    @staticmethod
    def _snapshot(
        account: PaperAccount,
        initial_equity: Decimal | None,
        positions: tuple[Position, ...],
        now: datetime,
    ) -> PortfolioSnapshot:
        assert initial_equity is not None
        return PortfolioSnapshot.create(
            snapshot_id=str(uuid4()),
            account_id=account.account_id,
            cash=account.cash,
            initial_equity=initial_equity,
            positions=positions,
            as_of=now,
        )

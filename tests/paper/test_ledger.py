from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from astraquant_domain import (
    AccountMode,
    InstrumentId,
    LiveQuote,
    OrderSide,
    OrderStatus,
    PaperAccount,
    QuoteLevel,
)
from astraquant_paper import LedgerState, PaperLedger, RejectionCode

NOW = datetime(2026, 8, 6, 6, 30, tzinfo=UTC)
INSTRUMENT = InstrumentId.parse("159516.SZSE")


def account(cash: str = "100000") -> PaperAccount:
    return PaperAccount(
        account_id="account-1",
        name="主模拟账户",
        mode=AccountMode.PAPER,
        initial_cash=Decimal(cash),
        cash=Decimal(cash),
        created_at=NOW,
        updated_at=NOW,
    )


def quote(
    *, last: str = "0.714", bid: str | None = "0.713", ask: str | None = "0.715"
) -> LiveQuote:
    return LiveQuote.minimum(
        INSTRUMENT,
        event_time=NOW,
        last_price=Decimal(last),
        previous_close=Decimal("0.701"),
        bid=() if bid is None else (QuoteLevel(Decimal(bid), Decimal("10000")),),
        ask=() if ask is None else (QuoteLevel(Decimal(ask), Decimal("10000")),),
    )


def test_buy_uses_best_ask_and_freezes_new_quantity_for_t_plus_one() -> None:
    result = PaperLedger().execute_market_order(
        LedgerState(account=account()),
        quote=quote(),
        side=OrderSide.BUY,
        quantity=1_000,
        idempotency_key="paper-order-0001",
        now=NOW,
        name="半导体设备ETF",
        stamp_duty_exempt=True,
    )

    assert result.order.status is OrderStatus.FILLED
    assert result.fill is not None
    assert result.fill.price == Decimal("0.715")
    assert result.state.account.cash == Decimal("99279.99")
    assert result.state.positions[0].quantity == 1_000
    assert result.state.positions[0].available_quantity == 0
    assert result.state.snapshots[-1].initial_equity == Decimal("100000")
    assert result.state.snapshots[-1].total_pnl == Decimal("-6.01")


def test_set_cash_balance_treats_the_difference_as_external_capital() -> None:
    ledger = PaperLedger()
    opening = ledger.add_opening_position(
        LedgerState(account=account()),
        instrument_id=INSTRUMENT,
        name="半导体设备ETF",
        quantity=1_000,
        available_quantity=1_000,
        average_cost=Decimal("0.68"),
    )
    marked = ledger.mark_to_market(opening, (quote(),), now=NOW)

    adjusted = ledger.set_cash_balance(
        marked,
        cash=Decimal("50000"),
        now=NOW + timedelta(seconds=1),
    )

    assert adjusted.account.cash == Decimal("50000")
    assert adjusted.initial_equity == Decimal("50680")
    assert adjusted.snapshots[-1].cash == Decimal("50000")
    assert adjusted.snapshots[-1].total_equity == Decimal("50714")
    assert adjusted.snapshots[-1].total_pnl == marked.snapshots[-1].total_pnl


def test_next_market_day_releases_frozen_quantity_before_sell() -> None:
    ledger = PaperLedger()
    bought = ledger.execute_market_order(
        LedgerState(account=account()),
        quote=quote(),
        side=OrderSide.BUY,
        quantity=1_000,
        idempotency_key="paper-order-t1-buy",
        now=NOW,
        name="半导体设备ETF",
        stamp_duty_exempt=True,
    )
    next_day = NOW + timedelta(days=1)
    next_quote = LiveQuote.minimum(
        INSTRUMENT,
        event_time=next_day,
        last_price=Decimal("0.720"),
        previous_close=Decimal("0.714"),
        bid=(QuoteLevel(Decimal("0.719"), Decimal("10000")),),
    )

    sold = ledger.execute_market_order(
        bought.state,
        quote=next_quote,
        side=OrderSide.SELL,
        quantity=1_000,
        idempotency_key="paper-order-t1-sell",
        now=next_day,
        stamp_duty_exempt=True,
    )

    assert sold.order.status is OrderStatus.FILLED
    assert sold.state.positions == ()


def test_sell_uses_best_bid_and_reduces_available_quantity() -> None:
    ledger = PaperLedger()
    state = ledger.add_opening_position(
        LedgerState(account=account("1000")),
        instrument_id=INSTRUMENT,
        name="半导体设备ETF",
        quantity=1_000,
        available_quantity=800,
        average_cost=Decimal("0.68"),
    )

    result = ledger.execute_market_order(
        state,
        quote=quote(),
        side=OrderSide.SELL,
        quantity=300,
        idempotency_key="paper-order-0002",
        now=NOW,
        stamp_duty_exempt=True,
    )

    assert result.fill is not None
    assert result.fill.price == Decimal("0.713")
    assert result.state.positions[0].quantity == 700
    assert result.state.positions[0].available_quantity == 500
    assert result.state.account.cash == Decimal("1208.89")


def test_market_order_falls_back_to_last_price_without_depth() -> None:
    result = PaperLedger().execute_market_order(
        LedgerState(account=account()),
        quote=quote(bid=None, ask=None),
        side=OrderSide.BUY,
        quantity=100,
        idempotency_key="paper-order-0003",
        now=NOW,
        stamp_duty_exempt=True,
    )

    assert result.fill is not None
    assert result.fill.price == Decimal("0.714")


def test_insufficient_cash_rejects_without_changing_balances() -> None:
    initial = LedgerState(account=account("10"))
    result = PaperLedger().execute_market_order(
        initial,
        quote=quote(),
        side=OrderSide.BUY,
        quantity=100,
        idempotency_key="paper-order-0004",
        now=NOW,
    )

    assert result.order.status is OrderStatus.REJECTED
    assert result.order.reject_reason == RejectionCode.INSUFFICIENT_CASH.value
    assert result.fill is None
    assert result.state.account.cash == Decimal("10")
    assert result.state.positions == ()


def test_unavailable_quantity_rejects_sell() -> None:
    ledger = PaperLedger()
    state = ledger.add_opening_position(
        LedgerState(account=account()),
        instrument_id=INSTRUMENT,
        name=None,
        quantity=100,
        available_quantity=0,
        average_cost=Decimal("0.7"),
    )
    result = ledger.execute_market_order(
        state,
        quote=quote(),
        side=OrderSide.SELL,
        quantity=100,
        idempotency_key="paper-order-0005",
        now=NOW,
    )

    assert result.order.status is OrderStatus.REJECTED
    assert result.order.reject_reason == RejectionCode.INSUFFICIENT_AVAILABLE_QUANTITY.value
    assert result.state.positions == state.positions


def test_duplicate_idempotency_key_returns_original_result_without_second_fill() -> None:
    ledger = PaperLedger()
    first = ledger.execute_market_order(
        LedgerState(account=account()),
        quote=quote(),
        side=OrderSide.BUY,
        quantity=100,
        idempotency_key="paper-order-0006",
        now=NOW,
        stamp_duty_exempt=True,
    )
    second = ledger.execute_market_order(
        first.state,
        quote=quote(last="0.80", bid="0.79", ask="0.81"),
        side=OrderSide.BUY,
        quantity=100,
        idempotency_key="paper-order-0006",
        now=NOW,
        stamp_duty_exempt=True,
    )

    assert second.order == first.order
    assert second.fill == first.fill
    assert second.state == first.state
    assert len(second.state.fills) == 1


def test_mark_to_market_only_changes_position_quote_and_equity() -> None:
    ledger = PaperLedger()
    state = ledger.add_opening_position(
        LedgerState(account=account("1000")),
        instrument_id=INSTRUMENT,
        name=None,
        quantity=1_000,
        available_quantity=1_000,
        average_cost=Decimal("0.68"),
    )

    marked = ledger.mark_to_market(state, (quote(last="0.72"),), now=NOW)

    assert marked.account == state.account
    assert marked.positions[0].average_cost == Decimal("0.68")
    assert marked.positions[0].last_price == Decimal("0.72")
    assert marked.snapshots[-1].total_equity == Decimal("1720.00")


def test_opening_position_rejects_duplicate_instrument() -> None:
    ledger = PaperLedger()
    state = ledger.add_opening_position(
        LedgerState(account=account()),
        instrument_id=INSTRUMENT,
        name=None,
        quantity=100,
        available_quantity=100,
        average_cost=Decimal("0.7"),
    )

    with pytest.raises(ValueError, match="opening position already exists"):
        ledger.add_opening_position(
            state,
            instrument_id=INSTRUMENT,
            name=None,
            quantity=100,
            available_quantity=100,
            average_cost=Decimal("0.7"),
        )

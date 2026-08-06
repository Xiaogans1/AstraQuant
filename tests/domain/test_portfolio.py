from datetime import UTC, datetime
from decimal import Decimal

import pytest

from astraquant_domain import InstrumentId, OrderSide, OrderStatus
from astraquant_domain.portfolio import (
    AccountMode,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PortfolioSnapshot,
    Position,
)

NOW = datetime(2026, 8, 6, 6, 30, tzinfo=UTC)
INSTRUMENT = InstrumentId.parse("159516.SZSE")


def test_account_modes_are_paper_and_mirror_only() -> None:
    assert {mode.value for mode in AccountMode} == {"PAPER", "MIRROR"}


def test_position_calculates_market_value_and_unrealized_pnl() -> None:
    position = Position(
        account_id="account-1",
        instrument_id=INSTRUMENT,
        name="半导体设备ETF",
        quantity=1_000,
        available_quantity=800,
        average_cost=Decimal("0.6800"),
        last_price=Decimal("0.7140"),
        marked_at=NOW,
    )

    assert position.market_value == Decimal("714.0000")
    assert position.unrealized_pnl == Decimal("34.0000")
    assert position.unrealized_pnl_percent == Decimal("5.0000")


def test_position_without_quote_uses_cost_for_initial_valuation() -> None:
    position = Position(
        account_id="account-1",
        instrument_id=INSTRUMENT,
        name=None,
        quantity=100,
        available_quantity=100,
        average_cost=Decimal("0.7000"),
    )

    assert position.mark_price == Decimal("0.7000")
    assert position.market_value == Decimal("70.0000")
    assert position.unrealized_pnl == Decimal("0.0000")


@pytest.mark.parametrize(
    ("quantity", "available"),
    [(0, 0), (-1, 0), (100, -1), (100, 101)],
)
def test_position_rejects_invalid_quantities(quantity: int, available: int) -> None:
    with pytest.raises(ValueError):
        Position(
            account_id="account-1",
            instrument_id=INSTRUMENT,
            name=None,
            quantity=quantity,
            available_quantity=available,
            average_cost=Decimal("0.7"),
        )


def test_portfolio_snapshot_total_asset_equals_cash_plus_positions() -> None:
    positions = (
        Position(
            account_id="account-1",
            instrument_id=INSTRUMENT,
            name=None,
            quantity=1_000,
            available_quantity=1_000,
            average_cost=Decimal("0.68"),
            last_price=Decimal("0.71"),
            marked_at=NOW,
        ),
    )
    snapshot = PortfolioSnapshot.create(
        snapshot_id="snapshot-1",
        account_id="account-1",
        cash=Decimal("300.00"),
        initial_equity=Decimal("980.00"),
        positions=positions,
        as_of=NOW,
    )

    assert snapshot.market_value == Decimal("710.00")
    assert snapshot.total_equity == Decimal("1010.00")
    assert snapshot.total_pnl == Decimal("30.00")
    assert snapshot.total_pnl_percent == Decimal("3.0612")


def test_trade_records_require_aware_times_and_stable_links() -> None:
    account = PaperAccount(
        account_id="account-1",
        name="主模拟账户",
        mode=AccountMode.PAPER,
        initial_cash=Decimal("100000"),
        cash=Decimal("100000"),
        created_at=NOW,
        updated_at=NOW,
    )
    order = PaperOrder(
        order_id="order-1",
        account_id=account.account_id,
        idempotency_key="paper-order-0001",
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        quantity=100,
        status=OrderStatus.FILLED,
        submitted_at=NOW,
        updated_at=NOW,
    )
    fill = PaperFill(
        fill_id="fill-1",
        order_id=order.order_id,
        account_id=account.account_id,
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        quantity=100,
        price=Decimal("0.714"),
        gross_amount=Decimal("71.4"),
        commission=Decimal("5"),
        stamp_duty=Decimal("0"),
        transfer_fee=Decimal("0"),
        occurred_at=NOW,
    )

    assert fill.total_fee == Decimal("5")
    assert fill.net_cash_flow == Decimal("-76.4")


def test_account_rejects_negative_cash() -> None:
    with pytest.raises(ValueError, match="cash must be non-negative"):
        PaperAccount(
            account_id="account-1",
            name="主模拟账户",
            mode=AccountMode.PAPER,
            initial_cash=Decimal("100"),
            cash=Decimal("-0.01"),
            created_at=NOW,
            updated_at=NOW,
        )

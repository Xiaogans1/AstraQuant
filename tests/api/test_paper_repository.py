from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa

from astraquant_api.database import create_database, migrate_database
from astraquant_api.paper_repository import PaperRepository
from astraquant_domain import (
    AccountMode,
    InstrumentId,
    LiveQuote,
    OrderSide,
    PaperAccount,
    QuoteLevel,
)
from astraquant_paper import LedgerState, PaperLedger

NOW = datetime(2026, 8, 6, 6, 30, tzinfo=UTC)
INSTRUMENT = InstrumentId.parse("159516.SZSE")


def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'state.sqlite3'}"


def build_repository(tmp_path: Path) -> PaperRepository:
    url = database_url(tmp_path)
    migrate_database(url)
    return PaperRepository(create_database(url))


def make_account() -> PaperAccount:
    return PaperAccount(
        account_id="account-1",
        name="主模拟账户",
        mode=AccountMode.PAPER,
        initial_cash=Decimal("100000"),
        cash=Decimal("100000"),
        created_at=NOW,
        updated_at=NOW,
    )


def make_quote() -> LiveQuote:
    return LiveQuote.minimum(
        INSTRUMENT,
        event_time=NOW,
        last_price=Decimal("0.714"),
        previous_close=Decimal("0.701"),
        bid=(QuoteLevel(Decimal("0.713"), Decimal("10000")),),
        ask=(QuoteLevel(Decimal("0.715"), Decimal("10000")),),
    )


def test_migration_creates_paper_ledger_tables(tmp_path: Path) -> None:
    url = database_url(tmp_path)
    migrate_database(url)
    inspector = sa.inspect(create_database(url))

    assert {
        "paper_accounts",
        "paper_positions",
        "paper_orders",
        "paper_fills",
        "paper_equity_snapshots",
    }.issubset(inspector.get_table_names())


def test_round_trip_account_opening_position_and_fill_across_restart(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    repository.create_account(make_account())
    ledger = PaperLedger()
    state = ledger.add_opening_position(
        repository.load_state("account-1"),
        instrument_id=INSTRUMENT,
        name="半导体设备ETF",
        quantity=1_000,
        available_quantity=800,
        average_cost=Decimal("0.68"),
    )
    state = ledger.execute_market_order(
        state,
        quote=make_quote(),
        side=OrderSide.SELL,
        quantity=100,
        idempotency_key="paper-order-0001",
        now=NOW,
        stamp_duty_exempt=True,
    ).state
    repository.save_state(state)

    restarted = PaperRepository(repository.engine).load_state("account-1")

    assert restarted.account.cash == state.account.cash
    assert restarted.initial_equity == Decimal("100680.00")
    assert restarted.positions == state.positions
    assert restarted.orders == state.orders
    assert restarted.fills == state.fills
    assert restarted.snapshots == state.snapshots


def test_saving_same_state_twice_is_idempotent(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    repository.create_account(make_account())
    result = PaperLedger().execute_market_order(
        LedgerState(account=make_account()),
        quote=make_quote(),
        side=OrderSide.BUY,
        quantity=100,
        idempotency_key="paper-order-0002",
        now=NOW,
        stamp_duty_exempt=True,
    )

    repository.save_state(result.state)
    repository.save_state(result.state)

    stored = repository.load_state("account-1")
    assert len(stored.orders) == 1
    assert len(stored.fills) == 1
    assert len(stored.snapshots) == 1


def test_list_accounts_orders_newest_first(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    first = make_account()
    second = PaperAccount(
        account_id="account-2",
        name="ETF 轮动",
        mode=AccountMode.MIRROR,
        initial_cash=Decimal("20000"),
        cash=Decimal("20000"),
        created_at=NOW.replace(minute=31),
        updated_at=NOW.replace(minute=31),
    )
    repository.create_account(first)
    repository.create_account(second)

    assert [item.account_id for item in repository.list_accounts()] == [
        "account-2",
        "account-1",
    ]

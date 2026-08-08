from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from astraquant_api.database import create_database, migrate_database
from astraquant_api.market_service import MarketDataService
from astraquant_api.paper_repository import PaperRepository
from astraquant_api.paper_service import PaperService, QuoteUnavailable
from astraquant_api.secret_store import MemorySecretStore
from astraquant_data.subscriptions import SubscriptionBudget
from astraquant_domain import AccountMode, InstrumentId, LiveQuote, OrderSide, PaperAccount

NOW = datetime(2026, 8, 6, 6, 30, tzinfo=UTC)
INSTRUMENT = InstrumentId.parse("159516.SZSE")


def build_services(tmp_path: Path) -> tuple[PaperService, PaperRepository, MarketDataService]:
    database_url = f"sqlite:///{tmp_path / 'state.sqlite3'}"
    migrate_database(database_url)
    repository = PaperRepository(create_database(database_url))
    market = MarketDataService(
        provider=None,
        budget=SubscriptionBudget(),
        secret_store=MemorySecretStore(None),
    )
    return PaperService(repository=repository, market_service=market), repository, market


def add_account_and_position(service: PaperService) -> None:
    service.create_account(
        PaperAccount(
            account_id="account-1",
            name="主模拟账户",
            mode=AccountMode.PAPER,
            initial_cash=Decimal("1000"),
            cash=Decimal("1000"),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    service.add_opening_position(
        "account-1",
        instrument_id=INSTRUMENT,
        name="半导体设备ETF",
        quantity=1_000,
        available_quantity=1_000,
        average_cost=Decimal("0.68"),
    )


def test_real_quote_marks_related_account_and_is_not_duplicated(tmp_path: Path) -> None:
    service, repository, market = build_services(tmp_path)
    add_account_and_position(service)
    service.start()
    quote = LiveQuote.minimum(
        INSTRUMENT,
        event_time=NOW,
        last_price=Decimal("0.72"),
        previous_close=Decimal("0.70"),
    )

    market.record_quotes([quote])
    market.record_quotes([quote])

    state = repository.load_state("account-1")
    assert state.positions[0].last_price == Decimal("0.72")
    assert state.snapshots[-1].total_equity == Decimal("1720.00")
    assert len(state.snapshots) == 1
    service.stop()


def test_start_restores_position_subscriptions(tmp_path: Path) -> None:
    service, _, market = build_services(tmp_path)
    add_account_and_position(service)

    service.start()

    assert "159516.SZSE" in market.active_instruments()


def test_start_creates_the_default_local_account_before_the_page_opens(tmp_path: Path) -> None:
    service, repository, _ = build_services(tmp_path)

    service.start()
    service.start()

    accounts = repository.list_accounts()
    assert len(accounts) == 1
    assert accounts[0].name == "主模拟账户"
    assert accounts[0].initial_cash == Decimal("100000")


def test_order_requires_a_real_latest_quote(tmp_path: Path) -> None:
    service, repository, _ = build_services(tmp_path)
    add_account_and_position(service)

    with pytest.raises(QuoteUnavailable):
        service.submit_market_order(
            "account-1",
            instrument_id=INSTRUMENT,
            side=OrderSide.BUY,
            quantity=100,
            idempotency_key="paper-order-0001",
            now=NOW,
            stamp_duty_exempt=True,
        )

    assert repository.load_state("account-1").orders == ()

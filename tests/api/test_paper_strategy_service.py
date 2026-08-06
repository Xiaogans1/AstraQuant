import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from astraquant_api.database import create_database, migrate_database
from astraquant_api.market_service import MarketDataService
from astraquant_api.paper_repository import PaperRepository
from astraquant_api.paper_service import PaperService
from astraquant_api.paper_strategy_service import PaperStrategyService, StrategyOutcome
from astraquant_api.secret_store import MemorySecretStore
from astraquant_data.live_providers import ProviderHealth
from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_data.subscriptions import SubscriptionBudget
from astraquant_domain import AccountMode, InstrumentId, LiveQuote, PaperAccount

INSTRUMENT = InstrumentId.parse("159516.SZSE")
START = datetime(2026, 8, 6, 1, 30, tzinfo=UTC)


class BarProvider:
    def __init__(self, bars: list[MarketBar]) -> None:
        self._bars = bars

    def connect(self, _token: str) -> None: ...
    def disconnect(self) -> None: ...
    def poll(self, _instruments: Sequence[InstrumentId]) -> list[LiveQuote]:
        return []

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id="test")

    def history_n(self, _instrument_id: InstrumentId, *, count: int):
        return []

    def bars(self, _instrument_id: InstrumentId, *, period: MarketPeriod, count: int):
        assert period is MarketPeriod.MINUTE_1
        return self._bars[-count:]

    def search(self, _query: str):
        return []

    def trading_dates(self, start: date, _end: date):
        return [start]


def bars(closes: list[str], *, last_volume: str = "100") -> list[MarketBar]:
    result: list[MarketBar] = []
    for index, raw_close in enumerate(closes):
        close = Decimal(raw_close)
        volume = Decimal(last_volume if index == len(closes) - 1 else "100")
        result.append(
            MarketBar(
                timestamp=START + timedelta(minutes=index),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=volume,
                turnover=close * volume,
                previous_close=Decimal("9.90"),
            )
        )
    return result


def build_service(
    tmp_path: Path, market_bars: list[MarketBar]
) -> tuple[PaperStrategyService, PaperRepository]:
    url = f"sqlite:///{tmp_path / 'state.sqlite3'}"
    migrate_database(url)
    repository = PaperRepository(create_database(url))
    market = MarketDataService(
        provider=BarProvider(market_bars),
        budget=SubscriptionBudget(),
        secret_store=MemorySecretStore(None),
    )
    paper = PaperService(repository=repository, market_service=market)
    paper.create_account(
        PaperAccount(
            account_id="account-1",
            name="策略账户",
            mode=AccountMode.PAPER,
            initial_cash=Decimal("100000"),
            cash=Decimal("100000"),
            created_at=START,
            updated_at=START,
        )
    )
    market.request_quote(str(INSTRUMENT))
    market.record_quotes(
        [
            LiveQuote.minimum(
                INSTRUMENT,
                event_time=market_bars[-1].timestamp + timedelta(minutes=1),
                last_price=market_bars[-1].close,
                previous_close=Decimal("9.90"),
            )
        ]
    )
    return PaperStrategyService(paper_service=paper, market_service=market), repository


def test_hold_signal_never_creates_an_order(tmp_path: Path) -> None:
    market_bars = bars(["10"] * 20)
    service, repository = build_service(tmp_path, market_bars)

    result = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=True,
            max_position_percent=Decimal("20"),
            decision_time=market_bars[-1].timestamp + timedelta(minutes=1),
        )
    )

    assert result.outcome is StrategyOutcome.HOLD
    assert repository.load_state("account-1").orders == ()


def test_buy_signal_is_only_a_suggestion_when_auto_execute_is_off(tmp_path: Path) -> None:
    market_bars = bars(
        ["10"] * 15 + ["10.01", "10.02", "10.03", "10.04", "10.05"],
        last_volume="400",
    )
    service, repository = build_service(tmp_path, market_bars)

    result = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=False,
            max_position_percent=Decimal("20"),
            decision_time=market_bars[-1].timestamp + timedelta(minutes=1),
        )
    )

    assert result.outcome is StrategyOutcome.SUGGESTED
    assert repository.load_state("account-1").orders == ()


def test_risk_limit_blocks_auto_execution(tmp_path: Path) -> None:
    market_bars = bars(
        ["10"] * 15 + ["10.01", "10.02", "10.03", "10.04", "10.05"],
        last_volume="400",
    )
    service, repository = build_service(tmp_path, market_bars)

    result = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=True,
            max_position_percent=Decimal("0.5"),
            decision_time=market_bars[-1].timestamp + timedelta(minutes=1),
        )
    )

    assert result.outcome is StrategyOutcome.BLOCKED
    assert result.risk_reason == "max_position_value_exceeded"
    assert repository.load_state("account-1").orders == ()


def test_auto_execution_is_idempotent_for_the_same_decision(tmp_path: Path) -> None:
    market_bars = bars(
        ["10"] * 15 + ["10.01", "10.02", "10.03", "10.04", "10.05"],
        last_volume="400",
    )
    service, repository = build_service(tmp_path, market_bars)
    request = {
        "instrument_id": INSTRUMENT,
        "quantity": 100,
        "auto_execute": True,
        "max_position_percent": Decimal("20"),
        "decision_time": market_bars[-1].timestamp + timedelta(minutes=1),
    }

    first = asyncio.run(service.run("account-1", **request))
    second = asyncio.run(service.run("account-1", **request))

    assert first.outcome is StrategyOutcome.EXECUTED
    assert second.order == first.order
    assert len(repository.load_state("account-1").orders) == 1

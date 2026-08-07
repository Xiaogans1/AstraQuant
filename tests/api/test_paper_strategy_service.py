import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from astraquant_api.database import create_database, migrate_database
from astraquant_api.market_service import MarketDataService
from astraquant_api.paper_repository import PaperRepository
from astraquant_api.paper_service import PaperService
from astraquant_api.paper_strategy_service import PaperStrategyService, StrategyOutcome
from astraquant_api.secret_store import MemorySecretStore
from astraquant_data.live_providers import ConnectionState, ProviderHealth
from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_data.subscriptions import SubscriptionBudget
from astraquant_domain import (
    AccountMode,
    InstrumentId,
    LiveQuote,
    OrderSide,
    PaperAccount,
)

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

    def history_n(self, _instrument_id: InstrumentId, *, count: int) -> list[dict[str, Any]]:
        return []

    def bars(
        self,
        _instrument_id: InstrumentId,
        *,
        period: MarketPeriod,
        count: int,
    ) -> list[MarketBar]:
        assert period is MarketPeriod.MINUTE_1
        return self._bars[-count:]

    def search(self, _query: str) -> list[dict[str, Any]]:
        return []

    def trading_dates(self, start: date, _end: date) -> list[date]:
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
    tmp_path: Path,
    market_bars: list[MarketBar],
    *,
    provider: BarProvider | None = None,
) -> tuple[PaperStrategyService, PaperRepository]:
    url = f"sqlite:///{tmp_path / 'state.sqlite3'}"
    migrate_database(url)
    repository = PaperRepository(create_database(url))
    market = MarketDataService(
        provider=provider if provider is not None else BarProvider(market_bars),
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
    return (
        PaperStrategyService(
            paper_service=paper,
            market_service=market,
            repository=repository,
        ),
        repository,
    )


def test_strategy_loop_scans_holdings_while_market_is_live(tmp_path: Path) -> None:
    service, repository = build_service(tmp_path, bars(["10"] * 20))
    service._paper_service.add_opening_position(
        "account-1",
        instrument_id=INSTRUMENT,
        name="半导体设备ETF",
        quantity=1000,
        available_quantity=1000,
        average_cost=Decimal("10"),
    )

    async def scenario() -> None:
        market = service._market_service
        assert market.connection().state is ConnectionState.LIVE

        await service._run_loop_once()
        assert service.last_scan_at is not None
        batch = repository.latest_strategy_run_batch("account-1")
        assert len(batch) == 1
        assert batch[0].instrument_id == str(INSTRUMENT)

    asyncio.run(scenario())


def test_strategy_loop_skips_when_market_is_not_live(tmp_path: Path) -> None:
    service, repository = build_service(tmp_path, bars(["10"] * 20))

    async def scenario() -> None:
        market = service._market_service
        assert market.connection().state is ConnectionState.LIVE
        market._connection = ProviderHealth(provider_id="eastmoney", state=ConnectionState.CLOSED)

        await service._run_loop_once()

        assert service.last_scan_at is None
        assert repository.latest_strategy_run_batch("account-1") == ()

    asyncio.run(scenario())


def test_strategy_loop_skips_accounts_without_positions(tmp_path: Path) -> None:
    service, repository = build_service(tmp_path, bars(["10"] * 20))

    async def scenario() -> None:
        market = service._market_service
        market.record_quotes(
            [
                LiveQuote.minimum(
                    INSTRUMENT,
                    event_time=START + timedelta(hours=1),
                    last_price=Decimal("10"),
                    previous_close=Decimal("9.9"),
                )
            ]
        )
        service._paper_service.create_account(
            PaperAccount(
                account_id="empty-account",
                name="空账户",
                mode=AccountMode.PAPER,
                initial_cash=Decimal("100000"),
                cash=Decimal("100000"),
                created_at=START,
                updated_at=START,
            )
        )

        await service._run_loop_once()

        assert repository.latest_strategy_run_batch("empty-account") == ()
        assert service.last_scan_at is not None

    asyncio.run(scenario())


def test_strategy_loop_skips_unchanged_one_minute_bar_and_rescans_on_new_bar(
    tmp_path: Path,
) -> None:
    class GrowingBarProvider(BarProvider):
        def __init__(self, bars: list[MarketBar]) -> None:
            super().__init__(bars)
            self._bars = bars
            self._call_count = 0

        def bars(
            self,
            _instrument_id: InstrumentId,
            *,
            period: MarketPeriod,
            count: int,
        ) -> list[MarketBar]:
            assert period is MarketPeriod.MINUTE_1
            self._call_count += 1
            if self._call_count >= 3:
                extra = bars(["10.05"], last_volume="400")
                self._bars = [*self._bars, extra[-1]]
            return self._bars[-count:]

    service, repository = build_service(
        tmp_path,
        bars(["10"] * 20),
        provider=GrowingBarProvider(bars(["10"] * 20)),
    )
    service._paper_service.add_opening_position(
        "account-1",
        instrument_id=INSTRUMENT,
        name="半导体设备ETF",
        quantity=1000,
        available_quantity=1000,
        average_cost=Decimal("10"),
    )

    async def scenario() -> None:
        market = service._market_service

        await service._run_loop_once()
        first_batch = repository.latest_strategy_run_batch("account-1")
        assert len(first_batch) == 1

        market._bar_history.clear()
        market._bar_history_fetched_at.clear()
        await service._run_loop_once()
        second_batch = repository.latest_strategy_run_batch("account-1")
        assert len(second_batch) == 1
        assert second_batch[0].decision_id == first_batch[0].decision_id

        market._bar_history.clear()
        market._bar_history_fetched_at.clear()
        await service._run_loop_once()
        third_batch = repository.latest_strategy_run_batch("account-1")
        assert len(third_batch) == 1
        assert third_batch[0].decision_id != first_batch[0].decision_id

    asyncio.run(scenario())


def test_strategy_loop_does_not_overlap_running_scans(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path, bars(["10"] * 20))

    async def scenario() -> None:
        assert service._scan_lock.locked() is False
        await service._scan_lock.acquire()
        try:
            await service._run_loop_once()
        finally:
            service._scan_lock.release()
        assert service.last_scan_at is None

    asyncio.run(scenario())


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
    assert result.proposed_quantity == 1900
    assert repository.load_state("account-1").orders == ()


def test_buy_quantity_is_computed_from_position_budget(tmp_path: Path) -> None:
    market_bars = bars(
        ["10"] * 15 + ["10.01", "10.02", "10.03", "10.04", "10.05"],
        last_volume="400",
    )
    service, _ = build_service(tmp_path, market_bars)

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

    assert result.proposed_quantity == 1900


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

    assert result.outcome is StrategyOutcome.HOLD
    assert result.risk_reason == "当前无可卖数量或买入预算不足 等待行情变化"
    assert repository.load_state("account-1").orders == ()


def test_same_direction_signal_executes_at_most_once_per_day(tmp_path: Path) -> None:
    market_bars = bars(
        ["10"] * 15 + ["10.01", "10.02", "10.03", "10.04", "10.05"],
        last_volume="400",
    )
    service, _ = build_service(tmp_path, market_bars)
    service._paper_service.add_opening_position(
        "account-1",
        instrument_id=INSTRUMENT,
        name="半导体设备ETF",
        quantity=1000,
        available_quantity=1000,
        average_cost=Decimal("10"),
    )
    decision_time = market_bars[-1].timestamp + timedelta(minutes=1)

    first = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=False,
            max_position_percent=Decimal("20"),
            decision_time=decision_time,
        )
    )
    assert first.outcome is StrategyOutcome.SUGGESTED
    assert first.proposed_quantity == 1100

    second = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=False,
            max_position_percent=Decimal("20"),
            decision_time=decision_time,
        )
    )
    assert second.outcome is StrategyOutcome.SUGGESTED


def test_sell_uses_available_quantity_and_does_not_repeat(tmp_path: Path) -> None:
    market_bars = bars(
        ["10"] * 15 + ["9.99", "9.98", "9.97", "9.96", "9.95"],
        last_volume="400",
    )
    service, repository = build_service(tmp_path, market_bars)
    service._paper_service.add_opening_position(
        "account-1",
        instrument_id=INSTRUMENT,
        name="半导体设备ETF",
        quantity=1000,
        available_quantity=1000,
        average_cost=Decimal("10"),
    )
    decision_time = market_bars[-1].timestamp + timedelta(minutes=1)

    first = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=True,
            max_position_percent=Decimal("20"),
            decision_time=decision_time,
        )
    )
    assert first.outcome is StrategyOutcome.EXECUTED
    assert first.fill is not None
    assert first.fill.quantity == 1000
    assert repository.load_state("account-1").positions == ()

    second = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=True,
            max_position_percent=Decimal("20"),
            decision_time=decision_time + timedelta(minutes=1),
        )
    )
    assert second.outcome is StrategyOutcome.HOLD
    assert second.risk_reason == "当前无可卖数量或买入预算不足 等待行情变化"
    assert len(repository.load_state("account-1").orders) == 1


def test_same_direction_dedup_recognizes_previous_execution(tmp_path: Path) -> None:
    from astraquant_quant import evaluate_intraday_signal

    market_bars = bars(
        ["10"] * 15 + ["10.01", "10.02", "10.03", "10.04", "10.05"],
        last_volume="400",
    )
    service, _ = build_service(tmp_path, market_bars)
    decision_time = market_bars[-1].timestamp + timedelta(minutes=1)

    first = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=True,
            max_position_percent=Decimal("100"),
            decision_time=decision_time,
        )
    )
    assert first.outcome is StrategyOutcome.EXECUTED

    later = decision_time + timedelta(minutes=1)
    decision = evaluate_intraday_signal(
        INSTRUMENT,
        market_bars,
        later,
        market_live=True,
    )
    assert (
        service._same_direction_already_executed(
            "account-1",
            instrument_id=INSTRUMENT,
            side=OrderSide.BUY,
            decision_time=later,
            current_decision_id=decision.decision_record.decision_id,
        )
        is True
    )


def test_auto_execution_is_idempotent_for_the_same_decision(tmp_path: Path) -> None:
    market_bars = bars(
        ["10"] * 15 + ["10.01", "10.02", "10.03", "10.04", "10.05"],
        last_volume="400",
    )
    service, repository = build_service(tmp_path, market_bars)
    decision_time = market_bars[-1].timestamp + timedelta(minutes=1)

    first = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=True,
            max_position_percent=Decimal("20"),
            decision_time=decision_time,
        )
    )
    second = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=True,
            max_position_percent=Decimal("20"),
            decision_time=decision_time,
        )
    )

    assert first.outcome is StrategyOutcome.EXECUTED
    assert second.order == first.order
    assert len(repository.load_state("account-1").orders) == 1


def test_run_uses_approved_model_signal_when_available(tmp_path: Path) -> None:
    import json as _json

    from astraquant_api.paper_repository import ModelRegistryRecord

    service, _ = build_service(tmp_path, bars(["10"] * 20))
    service._paper_service.save_model(
        ModelRegistryRecord(
            model_id="lgbm-minute-001",
            strategy_id="microstructure-lgbm",
            strategy_version="lgbm-v1",
            feature_version="minute-v1",
            artifact_path="models/does-not-exist.txt",
            metrics_json=_json.dumps({"auc": 0.58, "net_return": 0.03}),
            status="APPROVED",
            created_at=START,
            updated_at=START,
            approved_at=START,
        )
    )
    market = service._market_service
    market.record_quotes(
        [
            LiveQuote.minimum(
                INSTRUMENT,
                event_time=START + timedelta(hours=1),
                last_price=Decimal("9.70"),
                previous_close=Decimal("9.90"),
            )
        ]
    )

    result = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=True,
            max_position_percent=Decimal("20"),
            decision_time=START + timedelta(hours=1, minutes=1),
        )
    )

    assert result.decision.signal.strategy_id == "intraday-momentum-volume"
    assert result.outcome is StrategyOutcome.HOLD


def test_run_uses_approved_model_artifact_end_to_end(tmp_path: Path) -> None:
    import json as _json

    import lightgbm as lgb

    from astraquant_api.paper_repository import ModelRegistryRecord
    from astraquant_quant.research_features import build_feature_rows, label_future_return
    from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS

    closes = ["10.00"] * 20 + [
        "10.01",
        "10.02",
        "10.03",
        "10.04",
        "10.05",
        "10.04",
        "10.03",
        "10.02",
        "10.01",
        "10.00",
    ] * 6
    market_bars = bars(closes, last_volume="400")
    training: list[dict[str, float | int]] = []
    for index, row in enumerate(build_feature_rows(market_bars)):
        label = label_future_return(
            market_bars,
            index=index + 30,
            horizon=5,
            threshold=Decimal("0.002"),
        )
        if label < 0:
            continue
        training.append({**row, "label": label})
    assert any(row["label"] == 1 for row in training)
    assert any(row["label"] == 0 for row in training)
    import numpy as np

    dataset = lgb.Dataset(
        np.asarray(
            [[float(row[key]) for key in MODEL_FEATURE_COLUMNS] for row in training],
            dtype=float,
        ),
        label=[int(row["label"]) for row in training],
    )
    booster = lgb.train(
        {
            "objective": "binary",
            "verbosity": -1,
            "num_leaves": 4,
            "min_data_in_leaf": 2,
        },
        dataset,
        num_boost_round=8,
    )
    artifact = tmp_path / "model.txt"
    booster.save_model(str(artifact))

    service, _ = build_service(tmp_path, market_bars)
    service._paper_service.save_model(
        ModelRegistryRecord(
            model_id="lgbm-minute-001",
            strategy_id="microstructure-lgbm",
            strategy_version="lgbm-v1",
            feature_version="minute-v1",
            artifact_path=str(artifact),
            metrics_json=_json.dumps({"auc": 0.58, "net_return": 0.03}),
            status="APPROVED",
            created_at=START,
            updated_at=START,
            approved_at=START,
        )
    )
    market = service._market_service
    market.record_quotes(
        [
            LiveQuote.minimum(
                INSTRUMENT,
                event_time=START + timedelta(hours=1),
                last_price=Decimal("9.70"),
                previous_close=Decimal("9.90"),
            )
        ]
    )

    result = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=False,
            max_position_percent=Decimal("20"),
            decision_time=START + timedelta(hours=1, minutes=1),
        )
    )

    assert result.decision.signal.strategy_id == "microstructure-lgbm"
    assert result.outcome in (StrategyOutcome.HOLD, StrategyOutcome.SUGGESTED)

"""Application service connecting real read-only quotes to the Paper ledger."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Lock

from astraquant_api.market_service import MarketDataService
from astraquant_api.paper_repository import (
    ExperimentRecord,
    ModelRegistryRecord,
    PaperRepository,
    StrategyRunRecord,
)
from astraquant_domain import AccountMode, InstrumentId, LiveQuote, OrderSide, PaperAccount
from astraquant_paper import ExecutionResult, FeeSchedule, LedgerState, PaperLedger


class QuoteUnavailable(RuntimeError):
    pass


class PaperService:
    def __init__(
        self,
        *,
        repository: PaperRepository,
        market_service: MarketDataService,
        ledger: PaperLedger | None = None,
        fee_schedule: FeeSchedule | None = None,
    ) -> None:
        self._repository = repository
        self._market_service = market_service
        self._ledger = ledger or PaperLedger(fee_schedule)
        self._started = False
        self._account_creation_lock = Lock()

    def set_fee_schedule(self, fee_schedule: FeeSchedule) -> None:
        self._ledger = PaperLedger(fee_schedule)

    def start(self) -> None:
        if self._started:
            return
        self.ensure_default_account()
        for account in self._repository.list_accounts():
            state = self._repository.load_state(account.account_id)
            for position in state.positions:
                self._market_service.request_quote(str(position.instrument_id))
        self._market_service.add_quote_observer(self.on_quotes)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._market_service.remove_quote_observer(self.on_quotes)
        self._started = False

    def list_accounts(self) -> list[PaperAccount]:
        return self._repository.list_accounts()

    def save_model(self, record: ModelRegistryRecord) -> None:
        self._repository.save_model(record)

    def get_model(self, model_id: str) -> ModelRegistryRecord | None:
        return self._repository.get_model(model_id)

    def list_models(self) -> list[ModelRegistryRecord]:
        return self._repository.list_models()

    def save_experiment(self, record: ExperimentRecord) -> None:
        self._repository.save_experiment(record)

    def list_experiments(self, limit: int = 50) -> list[ExperimentRecord]:
        return self._repository.list_experiments(limit=limit)

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None:
        return self._repository.get_experiment(experiment_id)

    def get_state(self, account_id: str) -> LedgerState:
        return self._repository.load_state(account_id)

    def create_account(self, account: PaperAccount) -> LedgerState:
        self._repository.create_account(account)
        return self._repository.load_state(account.account_id)

    def ensure_default_account(self) -> LedgerState:
        """Return the primary local ledger, creating it once when none exists."""
        with self._account_creation_lock:
            accounts = self._repository.list_accounts()
            if accounts:
                return self._repository.load_state(accounts[0].account_id)
            now = datetime.now(UTC)
            account = PaperAccount(
                account_id="default-paper-account",
                name="主模拟账户",
                mode=AccountMode.PAPER,
                initial_cash=Decimal("100000"),
                cash=Decimal("100000"),
                created_at=now,
                updated_at=now,
            )
            self._repository.create_account(account)
            return self._repository.load_state(account.account_id)

    def reset_account(self, account_id: str) -> LedgerState:
        """Delete the account ledger so a fresh position setup can begin."""
        self._repository.delete_account(account_id)
        return self.ensure_default_account()

    def add_opening_position(
        self,
        account_id: str,
        *,
        instrument_id: InstrumentId,
        name: str | None,
        quantity: int,
        available_quantity: int,
        average_cost: Decimal,
    ) -> LedgerState:
        state = self._repository.load_state(account_id)
        next_state = self._ledger.add_opening_position(
            state,
            instrument_id=instrument_id,
            name=name,
            quantity=quantity,
            available_quantity=available_quantity,
            average_cost=average_cost,
        )
        self._repository.save_state(next_state)
        self._market_service.request_quote(str(instrument_id))
        return next_state

    def set_cash_balance(self, account_id: str, *, cash: Decimal) -> LedgerState:
        state = self._repository.load_state(account_id)
        next_state = self._ledger.set_cash_balance(
            state,
            cash=cash,
            now=datetime.now(UTC),
        )
        self._repository.save_state(next_state)
        return next_state

    def submit_market_order(
        self,
        account_id: str,
        *,
        instrument_id: InstrumentId,
        side: OrderSide,
        quantity: int,
        idempotency_key: str,
        now: datetime,
        name: str | None = None,
        stamp_duty_exempt: bool = False,
    ) -> ExecutionResult:
        quote = self._market_service.latest_quote(str(instrument_id))
        if quote is None:
            self._market_service.request_quote(str(instrument_id))
            raise QuoteUnavailable(str(instrument_id))
        state = self._repository.load_state(account_id)
        result = self._ledger.execute_market_order(
            state,
            quote=quote,
            side=side,
            quantity=quantity,
            idempotency_key=idempotency_key,
            now=now,
            name=name,
            stamp_duty_exempt=stamp_duty_exempt,
        )
        self._repository.save_state(result.state)
        return result

    def previous_close_map(self, account_id: str) -> dict[str, Decimal]:
        state = self._repository.load_state(account_id)
        return {
            str(position.instrument_id): quote.previous_close
            for position in state.positions
            if (quote := self._market_service.latest_quote(str(position.instrument_id))) is not None
            and quote.previous_close is not None
        }

    def get_daily_open(self, account_id: str, trading_date: date) -> dict[str, object] | None:
        return self._repository.get_daily_open(account_id, trading_date)

    def runs_on_date(self, account_id: str, trading_date: date) -> tuple[StrategyRunRecord, ...]:
        return self._repository.runs_on_date(account_id, trading_date)

    def save_daily_open(
        self,
        *,
        account_id: str,
        trading_date: date,
        cash: Decimal,
        positions_json: str,
    ) -> None:
        self._repository.save_daily_open(
            account_id=account_id,
            trading_date=trading_date,
            cash=str(cash),
            positions_json=positions_json,
            now=datetime.now(UTC),
        )

    def daily_summary(self, account_id: str) -> list[dict[str, object]]:
        """Per-trading-day equity PnL with external cash flows separated."""
        from collections import defaultdict
        from zoneinfo import ZoneInfo

        state = self._repository.load_state(account_id)
        china = ZoneInfo("Asia/Shanghai")
        day_equity: dict[date, Decimal] = {}
        day_equity_time: dict[date, datetime] = {}
        for snapshot in state.snapshots:
            day = snapshot.as_of.astimezone(china).date()
            if day not in day_equity_time or snapshot.as_of > day_equity_time[day]:
                day_equity[day] = snapshot.total_equity
                day_equity_time[day] = snapshot.as_of
        day_fills: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
        for fill in state.fills:
            day = fill.occurred_at.astimezone(china).date()
            day_fills[day] += fill.net_cash_flow
        day_cash: dict[date, Decimal] = {}
        day_cash_time: dict[date, datetime] = {}
        for snapshot in state.snapshots:
            day = snapshot.as_of.astimezone(china).date()
            if day not in day_cash_time or snapshot.as_of > day_cash_time[day]:
                day_cash[day] = snapshot.cash
                day_cash_time[day] = snapshot.as_of
        ordered = sorted(day_equity)
        rows: list[dict[str, object]] = []
        previous_equity: Decimal | None = None
        previous_cash = Decimal("0")
        for day in ordered:
            equity_end = day_equity[day]
            cash_end = day_cash.get(day, Decimal("0"))
            fills_net = day_fills.get(day, Decimal("0"))
            equity_prev = previous_equity
            equity_pnl = equity_end - equity_prev if equity_prev is not None else Decimal("0")
            cash_delta = cash_end - previous_cash
            external_flow = cash_delta - fills_net
            strategy_pnl = equity_pnl - external_flow
            strategy_pnl_percent = (
                None
                if equity_prev is None or equity_prev == 0
                else float(strategy_pnl / equity_prev * 100)
            )
            rows.append(
                {
                    "trading_date": day.isoformat(),
                    "equity_end": str(equity_end),
                    "cash_end": str(cash_end),
                    "equity_pnl": str(equity_pnl),
                    "external_flow": str(external_flow),
                    "strategy_pnl": str(strategy_pnl),
                    "strategy_pnl_percent": strategy_pnl_percent,
                    "fills": str(fills_net),
                    "has_daily_open": self.get_daily_open(account_id, day) is not None,
                }
            )
            previous_equity = equity_end
            previous_cash = cash_end
        return rows

    def on_quotes(self, quotes: tuple[LiveQuote, ...]) -> None:
        if not quotes:
            return
        for account in self._repository.list_accounts():
            state = self._repository.load_state(account.account_id)
            held_instruments = {position.instrument_id for position in state.positions}
            relevant = tuple(item for item in quotes if item.instrument_id in held_instruments)
            if not relevant:
                continue
            newest = max(item.event_time for item in relevant)
            if state.snapshots and state.snapshots[-1].as_of >= newest:
                continue
            marked = self._ledger.mark_to_market(state, relevant, now=newest)
            self._repository.save_state(marked)

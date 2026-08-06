"""Application service connecting real read-only quotes to the Paper ledger."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from astraquant_api.market_service import MarketDataService
from astraquant_api.paper_repository import PaperRepository
from astraquant_domain import InstrumentId, LiveQuote, OrderSide, PaperAccount
from astraquant_paper import ExecutionResult, PaperLedger


class QuoteUnavailable(RuntimeError):
    pass


class PaperService:
    def __init__(
        self,
        *,
        repository: PaperRepository,
        market_service: MarketDataService,
        ledger: PaperLedger | None = None,
    ) -> None:
        self._repository = repository
        self._market_service = market_service
        self._ledger = ledger or PaperLedger()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
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

    def create_account(self, account: PaperAccount) -> None:
        self._repository.create_account(account)

    def add_opening_position(
        self,
        account_id: str,
        *,
        instrument_id: InstrumentId,
        name: str | None,
        quantity: int,
        available_quantity: int,
        average_cost: Decimal,
    ) -> None:
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

    def on_quotes(self, quotes: tuple[LiveQuote, ...]) -> None:
        if not quotes:
            return
        for account in self._repository.list_accounts():
            state = self._repository.load_state(account.account_id)
            held_instruments = {position.instrument_id for position in state.positions}
            relevant = tuple(
                item
                for item in quotes
                if item.instrument_id in held_instruments
            )
            if not relevant:
                continue
            newest = max(item.event_time for item in relevant)
            if state.snapshots and state.snapshots[-1].as_of >= newest:
                continue
            marked = self._ledger.mark_to_market(state, relevant, now=newest)
            self._repository.save_state(marked)

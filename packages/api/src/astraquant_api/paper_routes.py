"""Authenticated routes for local Paper portfolio operations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Header

from astraquant_api.app import ApiProblem
from astraquant_api.paper_schemas import (
    AccountCreateRequest,
    AccountDetailView,
    AccountSummaryView,
    CashBalanceRequest,
    EquityView,
    FillView,
    MarketOrderRequest,
    OpeningPositionRequest,
    OrderExecutionView,
    OrderView,
    StrategyRunRequest,
    StrategyRunView,
    StrategySignalView,
)
from astraquant_api.paper_service import PaperService, QuoteUnavailable
from astraquant_api.paper_strategy_service import PaperStrategyService, StrategyRunResult
from astraquant_domain import InstrumentId, PaperAccount
from astraquant_paper import LedgerState


def build_paper_router(
    *,
    service: PaperService,
    strategy_service: PaperStrategyService | None,
    authenticated: Any,
    validate_idempotency_key: Callable[[str | None], str],
) -> APIRouter:
    router = APIRouter(prefix="/v1/paper", dependencies=[authenticated])

    @router.post("/accounts", response_model=AccountDetailView, status_code=201)
    def create_account(request: AccountCreateRequest) -> AccountDetailView:
        now = datetime.now(UTC)
        state = service.create_account(
            PaperAccount(
                account_id=str(uuid4()),
                name=request.name,
                mode=request.mode,
                initial_cash=request.initial_cash,
                cash=request.initial_cash,
                created_at=now,
                updated_at=now,
            )
        )
        return AccountDetailView.from_state(state)

    @router.get("/accounts", response_model=list[AccountSummaryView])
    def list_accounts() -> list[AccountSummaryView]:
        summaries: list[AccountSummaryView] = []
        for account in service.list_accounts():
            state = service.get_state(account.account_id)
            latest = state.snapshots[-1] if state.snapshots else None
            initial_equity = state.initial_equity or account.initial_cash
            total_equity = latest.total_equity if latest is not None else initial_equity
            summaries.append(
                AccountSummaryView(
                    account_id=account.account_id,
                    name=account.name,
                    mode=account.mode,
                    initial_cash=account.initial_cash,
                    cash=account.cash,
                    created_at=account.created_at,
                    updated_at=account.updated_at,
                    initial_equity=initial_equity,
                    total_equity=total_equity,
                    total_pnl=total_equity - initial_equity,
                )
            )
        return summaries

    @router.put("/accounts/default", response_model=AccountDetailView)
    def ensure_default_account() -> AccountDetailView:
        return AccountDetailView.from_state(service.ensure_default_account())

    @router.get("/accounts/{account_id}", response_model=AccountDetailView)
    def get_account(account_id: str) -> AccountDetailView:
        return AccountDetailView.from_state(_state_or_404(service, account_id))

    @router.patch("/accounts/{account_id}/cash", response_model=AccountDetailView)
    def update_cash_balance(
        account_id: str,
        request: CashBalanceRequest,
    ) -> AccountDetailView:
        try:
            state = service.set_cash_balance(account_id, cash=request.cash)
        except KeyError:
            raise ApiProblem(404, "paper_account_not_found", "未找到模拟账户") from None
        except ValueError as error:
            raise ApiProblem(409, "cash_balance_conflict", str(error)) from None
        return AccountDetailView.from_state(state)

    @router.post(
        "/accounts/{account_id}/positions/opening",
        response_model=AccountDetailView,
    )
    def add_opening_position(
        account_id: str,
        request: OpeningPositionRequest,
    ) -> AccountDetailView:
        try:
            state = service.add_opening_position(
                account_id,
                instrument_id=InstrumentId.parse(request.instrument_id),
                name=request.name,
                quantity=request.quantity,
                available_quantity=request.available_quantity,
                average_cost=request.average_cost,
            )
        except KeyError:
            raise ApiProblem(404, "paper_account_not_found", "未找到模拟账户") from None
        except ValueError as error:
            raise ApiProblem(409, "opening_position_conflict", str(error)) from None
        return AccountDetailView.from_state(state)

    @router.post(
        "/accounts/{account_id}/orders",
        response_model=OrderExecutionView,
    )
    def submit_order(
        account_id: str,
        request: MarketOrderRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OrderExecutionView:
        key = validate_idempotency_key(idempotency_key)
        try:
            result = service.submit_market_order(
                account_id,
                instrument_id=InstrumentId.parse(request.instrument_id),
                side=request.side,
                quantity=request.quantity,
                idempotency_key=key,
                now=datetime.now(UTC),
                name=request.name,
                stamp_duty_exempt=request.stamp_duty_exempt,
            )
        except KeyError:
            raise ApiProblem(404, "paper_account_not_found", "未找到模拟账户") from None
        except QuoteUnavailable:
            raise ApiProblem(409, "quote_unavailable", "尚未收到该证券的真实行情") from None
        return OrderExecutionView(
            order=OrderView.from_domain(result.order),
            fill=None if result.fill is None else FillView.from_domain(result.fill),
            portfolio=AccountDetailView.from_state(result.state),
        )

    @router.get("/accounts/{account_id}/orders", response_model=list[OrderView])
    def list_orders(account_id: str) -> list[OrderView]:
        state = _state_or_404(service, account_id)
        return [OrderView.from_domain(item) for item in reversed(state.orders)]

    @router.get("/accounts/{account_id}/fills", response_model=list[FillView])
    def list_fills(account_id: str) -> list[FillView]:
        state = _state_or_404(service, account_id)
        return [FillView.from_domain(item) for item in reversed(state.fills)]

    @router.get("/accounts/{account_id}/equity", response_model=list[EquityView])
    def list_equity(account_id: str) -> list[EquityView]:
        state = _state_or_404(service, account_id)
        return [EquityView.from_domain(item) for item in state.snapshots]

    if strategy_service is not None:

        @router.post(
            "/accounts/{account_id}/strategy/run",
            response_model=StrategyRunView,
        )
        async def run_strategy(
            account_id: str,
            request: StrategyRunRequest,
        ) -> StrategyRunView:
            try:
                result = await strategy_service.run(
                    account_id,
                    instrument_id=InstrumentId.parse(request.instrument_id),
                    quantity=request.quantity,
                    auto_execute=request.auto_execute,
                    max_position_percent=request.max_position_percent,
                    decision_time=datetime.now(UTC),
                )
            except KeyError:
                raise ApiProblem(404, "paper_account_not_found", "未找到模拟账户") from None
            except ValueError as error:
                raise ApiProblem(422, "invalid_strategy_request", str(error)) from None
            return _strategy_view(result)

        @router.post(
            "/accounts/{account_id}/strategy/scan",
            response_model=list[StrategyRunView],
        )
        async def scan_strategy(
            account_id: str,
            request: StrategyRunRequest,
        ) -> list[StrategyRunView]:
            try:
                results = await strategy_service.scan_account(
                    account_id,
                    quantity=request.quantity,
                    auto_execute=request.auto_execute,
                    max_position_percent=request.max_position_percent,
                    decision_time=datetime.now(UTC),
                )
            except KeyError:
                raise ApiProblem(404, "paper_account_not_found", "未找到模拟账户") from None
            except ValueError as error:
                raise ApiProblem(422, "invalid_strategy_request", str(error)) from None
            return [_strategy_view(result) for result in results]

    return router


def _strategy_view(result: StrategyRunResult) -> StrategyRunView:
    decision = result.decision.decision_record
    return StrategyRunView(
        outcome=result.outcome,
        proposed_side=result.proposed_side,
        proposed_quantity=result.proposed_quantity,
        risk_reason=result.risk_reason,
        decision_id=decision.decision_id,
        advisory_checks=list(decision.advisory_checks),
        signal=StrategySignalView.from_domain(result.decision.signal),
        order=None if result.order is None else OrderView.from_domain(result.order),
        fill=None if result.fill is None else FillView.from_domain(result.fill),
    )


def _state_or_404(service: PaperService, account_id: str) -> LedgerState:
    try:
        return service.get_state(account_id)
    except KeyError:
        raise ApiProblem(404, "paper_account_not_found", "未找到模拟账户") from None

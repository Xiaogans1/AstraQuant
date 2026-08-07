"""Authenticated routes for local Paper portfolio operations."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Protocol
from uuid import uuid4

from fastapi import APIRouter, Header

from astraquant_api.app import ApiProblem
from astraquant_api.paper_repository import ModelRegistryRecord, StrategyRunRecord
from astraquant_api.paper_schemas import (
    AccountCreateRequest,
    AccountDetailView,
    AccountSummaryView,
    CashBalanceRequest,
    EquityView,
    FeeConfigView,
    FillView,
    MarketOrderRequest,
    ModelRegisterRequest,
    ModelRegistryView,
    OpeningPositionRequest,
    OrderExecutionView,
    OrderView,
    StrategyRunRequest,
    StrategyRunView,
    StrategySignalView,
    StrategyStatusView,
)
from astraquant_api.paper_service import PaperService, QuoteUnavailable
from astraquant_api.paper_strategy_service import PaperStrategyService, StrategyRunResult
from astraquant_domain import InstrumentId, OrderSide, PaperAccount
from astraquant_paper import FeeSchedule, LedgerState


class SettingsStore(Protocol):
    def get_setting(self, key: str) -> object | None: ...

    def set_setting(self, key: str, value: object) -> None: ...


_FEE_CONFIG_KEY = "paper.fee_schedule"


def build_paper_router(
    *,
    service: PaperService,
    strategy_service: PaperStrategyService | None,
    authenticated: Any,
    validate_idempotency_key: Callable[[str | None], str],
    settings_store: SettingsStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/paper", dependencies=[authenticated])

    @router.get("/fee-config", response_model=FeeConfigView)
    def get_fee_config() -> FeeConfigView:
        stored = None if settings_store is None else settings_store.get_setting(_FEE_CONFIG_KEY)
        if not isinstance(stored, dict):
            return FeeConfigView.from_schedule(FeeSchedule())
        try:
            return FeeConfigView(
                commission_rate=Decimal(str(stored["commission_rate"])),
                minimum_commission=Decimal(str(stored["minimum_commission"])),
                stamp_duty_rate=Decimal(str(stored["stamp_duty_rate"])),
                transfer_fee_rate=Decimal(str(stored["transfer_fee_rate"])),
            )
        except (KeyError, TypeError, ValueError):
            return FeeConfigView.from_schedule(FeeSchedule())

    @router.put("/fee-config", response_model=FeeConfigView)
    def update_fee_config(request: FeeConfigView) -> FeeConfigView:
        for label, rate in (
            ("commission_rate", request.commission_rate),
            ("stamp_duty_rate", request.stamp_duty_rate),
            ("transfer_fee_rate", request.transfer_fee_rate),
        ):
            if not Decimal("0") <= rate <= Decimal("1"):
                raise ApiProblem(422, "invalid_fee_config", f"{label} 必须在 0 到 1 之间")
        if request.minimum_commission < 0:
            raise ApiProblem(422, "invalid_fee_config", "最低佣金不能为负")
        if settings_store is not None:
            settings_store.set_setting(
                _FEE_CONFIG_KEY,
                {
                    "commission_rate": str(request.commission_rate),
                    "minimum_commission": str(request.minimum_commission),
                    "stamp_duty_rate": str(request.stamp_duty_rate),
                    "transfer_fee_rate": str(request.transfer_fee_rate),
                },
            )
        service.set_fee_schedule(request.to_schedule())
        return request

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
        return _detail_view(service, state)

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

    @router.post("/models", response_model=ModelRegistryView, status_code=201)
    def register_model(request: ModelRegisterRequest) -> ModelRegistryView:
        now = datetime.now(UTC)
        record = ModelRegistryRecord(
            model_id=request.model_id,
            strategy_id=request.strategy_id,
            strategy_version=request.strategy_version,
            feature_version=request.feature_version,
            artifact_path=request.artifact_path,
            metrics_json=request.metrics_json,
            status="DRAFT",
            created_at=now,
            updated_at=now,
            approved_at=None,
        )
        service.save_model(record)
        return _model_view(record)

    @router.get("/models", response_model=list[ModelRegistryView])
    def list_models() -> list[ModelRegistryView]:
        return [_model_view(record) for record in service.list_models()]

    @router.patch("/models/{model_id}", response_model=ModelRegistryView)
    def update_model_metrics(model_id: str, request: ModelRegisterRequest) -> ModelRegistryView:
        current = service.get_model(model_id)
        if current is None:
            raise ApiProblem(404, "model_not_found", "未找到模型")
        if current.status == "APPROVED":
            raise ApiProblem(409, "model_immutable", "已批准模型不可修改")
        now = datetime.now(UTC)
        updated = ModelRegistryRecord(
            model_id=current.model_id,
            strategy_id=request.strategy_id,
            strategy_version=request.strategy_version,
            feature_version=request.feature_version,
            artifact_path=request.artifact_path,
            metrics_json=request.metrics_json,
            status=current.status,
            created_at=current.created_at,
            updated_at=now,
            approved_at=None,
        )
        service.save_model(updated)
        return _model_view(updated)

    @router.post("/models/{model_id}/approve", response_model=ModelRegistryView)
    def approve_model(model_id: str) -> ModelRegistryView:
        current = service.get_model(model_id)
        if current is None:
            raise ApiProblem(404, "model_not_found", "未找到模型")
        try:
            metrics = json.loads(current.metrics_json)
        except (TypeError, ValueError):
            raise ApiProblem(409, "model_publish_gate_failed", "模型指标无法解析") from None
        auc = float(metrics.get("auc", 0.0))
        net_return = float(metrics.get("net_return", 0.0))
        if auc <= 0.55 or net_return <= 0.0:
            raise ApiProblem(
                409,
                "model_publish_gate_failed",
                "样本外 AUC 需 > 0.55 且含费用净收益需 > 0",
            )
        now = datetime.now(UTC)
        approved = ModelRegistryRecord(
            model_id=current.model_id,
            strategy_id=current.strategy_id,
            strategy_version=current.strategy_version,
            feature_version=current.feature_version,
            artifact_path=current.artifact_path,
            metrics_json=current.metrics_json,
            status="APPROVED",
            created_at=current.created_at,
            updated_at=now,
            approved_at=now,
        )
        service.save_model(approved)
        return _model_view(approved)

    @router.put("/accounts/default", response_model=AccountDetailView)
    def ensure_default_account() -> AccountDetailView:
        return _detail_view(service, service.ensure_default_account())

    @router.delete("/accounts/{account_id}", response_model=AccountDetailView)
    def reset_account(account_id: str) -> AccountDetailView:
        try:
            state = service.reset_account(account_id)
        except KeyError:
            raise ApiProblem(404, "paper_account_not_found", "未找到模拟账户") from None
        return _detail_view(service, state)

    @router.get("/accounts/{account_id}", response_model=AccountDetailView)
    def get_account(account_id: str) -> AccountDetailView:
        return _detail_view(service, _state_or_404(service, account_id))

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
        return _detail_view(service, state)

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
        return _detail_view(service, state)

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
            portfolio=_detail_view(service, result.state),
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

        @router.get("/strategy/status", response_model=StrategyStatusView)
        def strategy_status() -> StrategyStatusView:
            return StrategyStatusView(
                loop_enabled=True,
                loop_interval_seconds=int(strategy_service.loop_interval_seconds),
                last_scan_at=strategy_service.last_scan_at,
            )

        @router.get(
            "/accounts/{account_id}/strategy/runs",
            response_model=list[StrategyRunView],
        )
        def list_strategy_runs(account_id: str) -> list[StrategyRunView]:
            _state_or_404(service, account_id)
            records = strategy_service.latest_runs(account_id)
            return [_strategy_view_from_record(record) for record in records]

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


def _model_view(record: ModelRegistryRecord) -> ModelRegistryView:
    return ModelRegistryView(
        model_id=record.model_id,
        strategy_id=record.strategy_id,
        strategy_version=record.strategy_version,
        feature_version=record.feature_version,
        artifact_path=record.artifact_path,
        metrics_json=record.metrics_json,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        approved_at=record.approved_at,
    )


def _strategy_view_from_record(record: StrategyRunRecord) -> StrategyRunView:
    return StrategyRunView(
        outcome=record.outcome,
        proposed_side=(None if record.proposed_side is None else OrderSide(record.proposed_side)),
        proposed_quantity=record.proposed_quantity,
        risk_reason=record.risk_reason,
        decision_id=record.decision_id,
        advisory_checks=list(record.advisory_checks),
        signal=StrategySignalView.model_validate(json.loads(record.signal_json)),
        order=(
            None
            if record.order_json is None
            else OrderView.model_validate(json.loads(record.order_json))
        ),
        fill=(
            None
            if record.fill_json is None
            else FillView.model_validate(json.loads(record.fill_json))
        ),
    )


def _state_or_404(service: PaperService, account_id: str) -> LedgerState:
    try:
        return service.get_state(account_id)
    except KeyError:
        raise ApiProblem(404, "paper_account_not_found", "未找到模拟账户") from None


def _detail_view(service: PaperService, state: LedgerState) -> AccountDetailView:
    try:
        previous_close = service.previous_close_map(state.account.account_id)
    except KeyError:
        previous_close = {}
    return AccountDetailView.from_state_with_previous_close(state, previous_close)

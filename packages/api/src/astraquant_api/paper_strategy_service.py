"""Auditable bridge from the baseline signal engine to Paper orders."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from astraquant_api.market_service import MarketDataService
from astraquant_api.paper_repository import PaperRepository, StrategyRunRecord
from astraquant_api.paper_service import PaperService
from astraquant_data.live_providers import ConnectionState
from astraquant_data.market_bars import MarketPeriod
from astraquant_domain import InstrumentId, OrderSide, PaperFill, PaperOrder, SignalAction
from astraquant_quant import QuantDecision, evaluate_intraday_signal

LOGGER = logging.getLogger(__name__)


class StrategyOutcome(StrEnum):
    HOLD = "HOLD"
    SUGGESTED = "SUGGESTED"
    BLOCKED = "BLOCKED"
    EXECUTED = "EXECUTED"


@dataclass(frozen=True, slots=True)
class StrategyRunResult:
    decision: QuantDecision
    outcome: StrategyOutcome
    proposed_side: OrderSide | None
    proposed_quantity: int
    risk_reason: str | None = None
    order: PaperOrder | None = None
    fill: PaperFill | None = None


class PaperStrategyService:
    def __init__(
        self,
        *,
        paper_service: PaperService,
        market_service: MarketDataService,
        repository: PaperRepository,
        loop_interval_seconds: float = 60,
    ) -> None:
        self._paper_service = paper_service
        self._market_service = market_service
        self._repository = repository
        self._loop_interval_seconds = loop_interval_seconds
        self._scan_lock = asyncio.Lock()
        self._last_scan_at: datetime | None = None

    @property
    def last_scan_at(self) -> datetime | None:
        return self._last_scan_at

    @property
    def loop_interval_seconds(self) -> float:
        return self._loop_interval_seconds

    async def run_loop(self) -> None:
        """Periodically scan every account while the market is live."""
        while True:
            try:
                await self._run_loop_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.warning("strategy loop iteration failed", exc_info=True)
            await asyncio.sleep(self._loop_interval_seconds)

    async def _run_loop_once(self) -> None:
        if self._scan_lock.locked():
            return
        if self._market_service.connection().state is not ConnectionState.LIVE:
            return
        accounts = self._paper_service.list_accounts()
        if not accounts:
            return
        async with self._scan_lock:
            for account in accounts:
                state = self._paper_service.get_state(account.account_id)
                if not state.positions:
                    continue
                await self.scan_account(
                    account.account_id,
                    quantity=100,
                    auto_execute=True,
                    max_position_percent=Decimal("20"),
                    decision_time=datetime.now(UTC),
                )
            self._last_scan_at = datetime.now(UTC)

    async def run(
        self,
        account_id: str,
        *,
        instrument_id: InstrumentId,
        quantity: int,
        auto_execute: bool,
        max_position_percent: Decimal,
        decision_time: datetime,
    ) -> StrategyRunResult:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if not Decimal("0") < max_position_percent <= Decimal("100"):
            raise ValueError("max_position_percent must be between 0 and 100")
        rows = await self._market_service.bars(
            str(instrument_id),
            period=MarketPeriod.MINUTE_1,
            count=60,
        )
        decision = evaluate_intraday_signal(
            instrument_id,
            rows,
            decision_time,
            market_live=self._market_service.connection().state is ConnectionState.LIVE,
        )
        side = self._side(decision.signal.action)
        if side is None:
            return StrategyRunResult(
                decision=decision,
                outcome=StrategyOutcome.HOLD,
                proposed_side=None,
                proposed_quantity=quantity,
            )
        if not auto_execute:
            return StrategyRunResult(
                decision=decision,
                outcome=StrategyOutcome.SUGGESTED,
                proposed_side=side,
                proposed_quantity=quantity,
            )
        risk_reason = self._risk_reason(
            account_id,
            instrument_id=instrument_id,
            side=side,
            quantity=quantity,
            max_position_percent=max_position_percent,
        )
        if risk_reason is not None:
            return StrategyRunResult(
                decision=decision,
                outcome=StrategyOutcome.BLOCKED,
                proposed_side=side,
                proposed_quantity=quantity,
                risk_reason=risk_reason,
            )
        execution = self._paper_service.submit_market_order(
            account_id,
            instrument_id=instrument_id,
            side=side,
            quantity=quantity,
            idempotency_key=f"strategy-{decision.decision_record.decision_id}",
            now=decision_time,
            stamp_duty_exempt=instrument_id.symbol.startswith(("1", "5")),
        )
        result = StrategyRunResult(
            decision=decision,
            outcome=StrategyOutcome.EXECUTED,
            proposed_side=side,
            proposed_quantity=quantity,
            order=execution.order,
            fill=execution.fill,
        )
        self._persist_run(account_id, result, batch_id=str(uuid4()))
        return result

    async def scan_account(
        self,
        account_id: str,
        *,
        quantity: int,
        auto_execute: bool,
        max_position_percent: Decimal,
        decision_time: datetime,
    ) -> list[StrategyRunResult]:
        """Concurrently run the baseline check for every current holding."""
        state = self._paper_service.get_state(account_id)
        if not state.positions:
            return []
        batch_id = str(uuid4())
        results = await asyncio.gather(
            *(
                self.run(
                    account_id,
                    instrument_id=position.instrument_id,
                    quantity=quantity,
                    auto_execute=auto_execute,
                    max_position_percent=max_position_percent,
                    decision_time=decision_time,
                )
                for position in state.positions
            )
        )
        self._persist_run_batch(account_id, results, batch_id=batch_id)
        return list(results)

    def latest_runs(self, account_id: str) -> tuple[StrategyRunRecord, ...]:
        """Return the newest persisted strategy-run batch for an account."""
        return self._repository.latest_strategy_run_batch(account_id)

    def _persist_run(
        self,
        account_id: str,
        result: StrategyRunResult,
        *,
        batch_id: str,
    ) -> None:
        self._persist_run_batch(account_id, (result,), batch_id=batch_id)

    def _persist_run_batch(
        self,
        account_id: str,
        results: tuple[StrategyRunResult, ...] | list[StrategyRunResult],
        *,
        batch_id: str,
    ) -> None:
        try:
            self._repository.save_strategy_runs(
                tuple(self._record(account_id, result, batch_id=batch_id) for result in results)
            )
        except Exception:
            LOGGER.warning("failed to persist strategy run batch", exc_info=True)

    @staticmethod
    def _record(
        account_id: str,
        result: StrategyRunResult,
        *,
        batch_id: str,
    ) -> StrategyRunRecord:
        signal = result.decision.signal
        return StrategyRunRecord(
            decision_id=result.decision.decision_record.decision_id,
            batch_id=batch_id,
            account_id=account_id,
            instrument_id=str(signal.instrument_id),
            outcome=result.outcome.value,
            proposed_side=None if result.proposed_side is None else result.proposed_side.value,
            proposed_quantity=result.proposed_quantity,
            risk_reason=result.risk_reason,
            signal_json=json.dumps(
                {
                    "signal_id": signal.signal_id,
                    "instrument_id": str(signal.instrument_id),
                    "action": signal.action.value,
                    "state": signal.state.value,
                    "reference_price": (
                        None if signal.reference_price is None else str(signal.reference_price)
                    ),
                    "confidence": str(signal.confidence),
                    "strategy_id": signal.strategy_id,
                    "strategy_version": signal.strategy_version,
                    "feature_version": signal.feature_version,
                    "reason_codes": list(signal.reason_codes),
                    "event_time": signal.event_time.isoformat(),
                    "decision_time": signal.decision_time.isoformat(),
                    "expires_at": signal.expires_at.isoformat(),
                }
            ),
            advisory_checks=tuple(result.decision.decision_record.advisory_checks),
            order_json=_order_json(result.order),
            fill_json=_fill_json(result.fill),
            decision_time=result.decision.decision_record.decision_time,
        )

    def _risk_reason(
        self,
        account_id: str,
        *,
        instrument_id: InstrumentId,
        side: OrderSide,
        quantity: int,
        max_position_percent: Decimal,
    ) -> str | None:
        state = self._paper_service.get_state(account_id)
        position = next(
            (item for item in state.positions if item.instrument_id == instrument_id),
            None,
        )
        if side is OrderSide.SELL:
            if position is None or position.available_quantity < quantity:
                return "insufficient_available_quantity"
            return None
        quote = self._market_service.latest_quote(str(instrument_id))
        if quote is None:
            return "quote_unavailable"
        current_value = Decimal("0") if position is None else position.market_value
        assert state.initial_equity is not None
        limit = state.initial_equity * max_position_percent / Decimal("100")
        if current_value + quote.last_price * quantity > limit:
            return "max_position_value_exceeded"
        return None

    @staticmethod
    def _side(action: SignalAction) -> OrderSide | None:
        if action is SignalAction.BUY:
            return OrderSide.BUY
        if action is SignalAction.SELL:
            return OrderSide.SELL
        return None


def _order_json(order: PaperOrder | None) -> str | None:
    if order is None:
        return None
    return json.dumps(
        {
            "order_id": order.order_id,
            "account_id": order.account_id,
            "idempotency_key": order.idempotency_key,
            "instrument_id": str(order.instrument_id),
            "side": order.side.value,
            "quantity": order.quantity,
            "status": order.status.value,
            "submitted_at": order.submitted_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
            "reject_reason": order.reject_reason,
        }
    )


def _fill_json(fill: PaperFill | None) -> str | None:
    if fill is None:
        return None
    return json.dumps(
        {
            "fill_id": fill.fill_id,
            "order_id": fill.order_id,
            "account_id": fill.account_id,
            "instrument_id": str(fill.instrument_id),
            "side": fill.side.value,
            "quantity": fill.quantity,
            "price": str(fill.price),
            "gross_amount": str(fill.gross_amount),
            "commission": str(fill.commission),
            "stamp_duty": str(fill.stamp_duty),
            "transfer_fee": str(fill.transfer_fee),
            "occurred_at": fill.occurred_at.isoformat(),
        }
    )

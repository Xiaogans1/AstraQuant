"""Auditable bridge from the baseline signal engine to Paper orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from astraquant_api.market_service import MarketDataService
from astraquant_api.paper_service import PaperService
from astraquant_data.live_providers import ConnectionState
from astraquant_data.market_bars import MarketPeriod
from astraquant_domain import InstrumentId, OrderSide, PaperFill, PaperOrder, SignalAction
from astraquant_quant import QuantDecision, evaluate_intraday_signal


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
    ) -> None:
        self._paper_service = paper_service
        self._market_service = market_service

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
        return StrategyRunResult(
            decision=decision,
            outcome=StrategyOutcome.EXECUTED,
            proposed_side=side,
            proposed_quantity=quantity,
            order=execution.order,
            fill=execution.fill,
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

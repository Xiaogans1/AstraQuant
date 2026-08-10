"""Auditable bridge from the baseline signal engine to Paper orders."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import lightgbm as lgb

from astraquant_api.market_service import MarketDataService
from astraquant_api.paper_repository import ModelRegistryRecord, PaperRepository, StrategyRunRecord
from astraquant_api.paper_service import PaperService
from astraquant_data.live_providers import ConnectionState
from astraquant_data.market_bars import MarketPeriod
from astraquant_domain import (
    InstrumentId,
    LiveQuote,
    OrderSide,
    PaperFill,
    PaperOrder,
    Position,
    SignalAction,
)
from astraquant_quant import QuantDecision, evaluate_intraday_signal
from astraquant_quant.research_features import build_feature_rows
from astraquant_quant.strategy_layer import (
    MODEL_FEATURE_COLUMNS,
    PortfolioConstructor,
    RiskPolicy,
    build_model_signal,
    build_target_position,
)

LOGGER = logging.getLogger(__name__)

_CHINA_ZONE = ZoneInfo("Asia/Shanghai")


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
        loop_interval_seconds: float = 5,
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
                self._ensure_daily_open(account.account_id)
                await self.scan_account(
                    account.account_id,
                    quantity=100,
                    auto_execute=True,
                    max_position_percent=Decimal("20"),
                    decision_time=datetime.now(UTC),
                )
            self._last_scan_at = datetime.now(UTC)

    def _ensure_daily_open(self, account_id: str) -> None:
        """Snapshot the account state once per trading day (idempotent)."""
        from zoneinfo import ZoneInfo as _ZI

        now = datetime.now(UTC)
        today = now.astimezone(_ZI("Asia/Shanghai")).date()
        if self._paper_service.get_daily_open(account_id, today) is not None:
            return
        state = self._paper_service.get_state(account_id)
        positions_json = json.dumps(
            [
                {
                    "instrument_id": str(position.instrument_id),
                    "quantity": position.quantity,
                    "available_quantity": position.available_quantity,
                    "average_cost": str(position.average_cost),
                }
                for position in state.positions
            ],
            ensure_ascii=False,
        )
        self._paper_service.save_daily_open(
            account_id=account_id,
            trading_date=today,
            cash=state.account.cash,
            positions_json=positions_json,
        )

    async def _scan_account_skipping_unchanged_bars(self, account_id: str) -> None:
        """Scan holdings, skipping any whose latest one-minute bar is unchanged.

        The automatic loop is more frequent than the one-minute bar cadence;
        re-evaluating (and re-executing) the same bar would duplicate orders.
        """
        state = self._paper_service.get_state(account_id)
        if not state.positions:
            return
        latest = self._repository.latest_strategy_run_batch(account_id)
        latest_event_by_instrument: dict[str, str] = {}
        for record in latest:
            try:
                signal = json.loads(record.signal_json)
            except (ValueError, TypeError):
                continue
            event_time = signal.get("event_time")
            if isinstance(event_time, str):
                latest_event_by_instrument[record.instrument_id] = event_time

        pending: list[Position] = []
        for position in state.positions:
            bars = await self._market_service.bars(
                str(position.instrument_id),
                period=MarketPeriod.MINUTE_1,
                count=60,
            )
            if not bars:
                pending.append(position)
                continue
            current_event = bars[-1].timestamp.isoformat()
            if latest_event_by_instrument.get(str(position.instrument_id)) == current_event:
                continue
            pending.append(position)
        if not pending:
            return
        batch_id = str(uuid4())
        results = await asyncio.gather(
            *(
                self.run(
                    account_id,
                    instrument_id=position.instrument_id,
                    quantity=100,
                    auto_execute=True,
                    max_position_percent=Decimal("20"),
                    decision_time=datetime.now(UTC),
                )
                for position in pending
            )
        )
        self._persist_run_batch(account_id, results, batch_id=batch_id)

    async def run(
        self,
        account_id: str,
        *,
        instrument_id: InstrumentId,
        quantity: int | None = None,
        auto_execute: bool,
        max_position_percent: Decimal,
        decision_time: datetime,
    ) -> StrategyRunResult:
        """Run the approved-model signal first, falling back to the baseline rule engine.

        ``quantity`` is accepted for call-site compatibility but ignored: the
        engine decides how many shares to trade so trends cannot nibble 100
        shares at a time. The rule fallback executes the same direction at most
        once per trading day until the signal reverses; an approved model
        re-decides on every new completed bar.
        """
        if not Decimal("0") < max_position_percent <= Decimal("100"):
            raise ValueError("max_position_percent must be between 0 and 100")
        state = self._paper_service.get_state(account_id)
        model = self._repository.latest_approved_legacy_model()
        if model is not None and self._market_service.connection().state is ConnectionState.LIVE:
            quote = self._market_service.latest_quote(str(instrument_id))
            if quote is not None:
                decision = await self._model_decision(
                    model,
                    instrument_id=instrument_id,
                    quote=quote,
                    decision_time=decision_time,
                )
                if decision is not None:
                    side = self._side(decision.signal.action)
                    if side is None:
                        return StrategyRunResult(
                            decision=decision,
                            outcome=StrategyOutcome.HOLD,
                            proposed_side=None,
                            proposed_quantity=0,
                            risk_reason="模型建议观望",
                        )
                    assert state.initial_equity is not None
                    target = build_target_position(
                        PortfolioConstructor(max_position_percent=max_position_percent),
                        RiskPolicy(max_position_percent=max_position_percent),
                        signal_strength=Decimal("1"),
                        equity=state.initial_equity,
                        price=quote.last_price,
                    )
                    if side is OrderSide.SELL:
                        position = next(
                            (
                                item
                                for item in state.positions
                                if item.instrument_id == instrument_id
                            ),
                            None,
                        )
                        target = min(target, 0 if position is None else position.available_quantity)
                    if target <= 0:
                        return StrategyRunResult(
                            decision=decision,
                            outcome=StrategyOutcome.HOLD,
                            proposed_side=side,
                            proposed_quantity=0,
                            risk_reason=(
                                "无可卖数量" if side is OrderSide.SELL else "目标仓位不足一手"
                            ),
                        )
                    decision_id = decision.decision_record.decision_id
                    if auto_execute and self._decision_already_executed(account_id, decision_id):
                        execution = self._paper_service.submit_market_order(
                            account_id,
                            instrument_id=instrument_id,
                            side=side,
                            quantity=100,
                            idempotency_key=f"strategy-{decision_id}",
                            now=decision_time,
                            stamp_duty_exempt=instrument_id.symbol.startswith(("1", "5")),
                        )
                        return StrategyRunResult(
                            decision=decision,
                            outcome=StrategyOutcome.EXECUTED,
                            proposed_side=side,
                            proposed_quantity=(
                                execution.fill.quantity if execution.fill is not None else 100
                            ),
                            order=execution.order,
                            fill=execution.fill,
                        )
                    if not auto_execute:
                        return StrategyRunResult(
                            decision=decision,
                            outcome=StrategyOutcome.SUGGESTED,
                            proposed_side=side,
                            proposed_quantity=target,
                        )
                    risk_reason = self._risk_reason(
                        account_id,
                        instrument_id=instrument_id,
                        side=side,
                        quantity=target,
                        max_position_percent=max_position_percent,
                    )
                    if risk_reason is not None:
                        return StrategyRunResult(
                            decision=decision,
                            outcome=StrategyOutcome.BLOCKED,
                            proposed_side=side,
                            proposed_quantity=target,
                            risk_reason=risk_reason,
                        )
                    execution = self._paper_service.submit_market_order(
                        account_id,
                        instrument_id=instrument_id,
                        side=side,
                        quantity=target,
                        idempotency_key=f"strategy-{decision_id}",
                        now=decision_time,
                        stamp_duty_exempt=instrument_id.symbol.startswith(("1", "5")),
                    )
                    result = StrategyRunResult(
                        decision=decision,
                        outcome=StrategyOutcome.EXECUTED,
                        proposed_side=side,
                        proposed_quantity=target,
                        order=execution.order,
                        fill=execution.fill,
                    )
                    self._persist_run(account_id, result, batch_id=str(uuid4()))
                    return result
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
                proposed_quantity=quantity if quantity is not None else 0,
            )
        suggested = self._suggested_quantity(
            account_id,
            instrument_id=instrument_id,
            side=side,
            max_position_percent=max_position_percent,
        )
        if suggested <= 0:
            return StrategyRunResult(
                decision=decision,
                outcome=StrategyOutcome.HOLD,
                proposed_side=side,
                proposed_quantity=0,
                risk_reason="当前无可卖数量或买入预算不足 等待行情变化",
            )
        return StrategyRunResult(
            decision=decision,
            outcome=StrategyOutcome.SUGGESTED,
            proposed_side=side,
            proposed_quantity=suggested,
            risk_reason="rule fallback observes only (loss-making on real data)",
        )

    async def _model_decision(
        self,
        model: ModelRegistryRecord,
        *,
        instrument_id: InstrumentId,
        quote: LiveQuote,
        decision_time: datetime,
    ) -> QuantDecision | None:
        """Run approved-model inference; None means inference unavailable (fall back)."""
        artifact = Path(model.artifact_path)
        if not artifact.exists():
            return None
        rows = await self._market_service.bars(
            str(instrument_id),
            period=MarketPeriod.MINUTE_1,
            count=60,
        )
        if not rows:
            return None
        try:
            features = build_feature_rows(rows)
            if not features:
                return None
            latest = features[-1]
            booster = lgb.Booster(model_file=str(artifact))
            proba = float(
                booster.predict([[float(latest[key]) for key in MODEL_FEATURE_COLUMNS]])[0]
            )
        except Exception:
            LOGGER.warning("model inference failed, falling back", exc_info=True)
            return None
        try:
            params = json.loads(model.params_json)
        except (TypeError, ValueError):
            params = {}
        buy_threshold = float(params.get("buy_threshold", 0.6))
        sell_threshold = float(params.get("sell_threshold", 0.4))
        action = (
            SignalAction.BUY
            if proba >= buy_threshold
            else SignalAction.SELL
            if proba <= sell_threshold
            else SignalAction.HOLD
        )
        confidence = Decimal(str(proba)) if action is not SignalAction.HOLD else Decimal("0")
        reason = f"model {model.strategy_version} up-probability {proba:.2f}"
        return _model_decision_frame(
            instrument_id=instrument_id,
            action=action,
            price=quote.last_price,
            decision_time=decision_time,
            strategy_id=model.strategy_id,
            strategy_version=model.strategy_version,
            feature_version=model.feature_version,
            reason=reason,
            confidence=confidence,
        )

    def _decision_already_executed(self, account_id: str, decision_id: str) -> bool:
        batch = self._repository.latest_strategy_run_batch(account_id)
        return any(
            record.decision_id == decision_id and record.order_json is not None for record in batch
        )

    def _suggested_quantity(
        self,
        account_id: str,
        *,
        instrument_id: InstrumentId,
        side: OrderSide,
        max_position_percent: Decimal,
    ) -> int:
        state = self._paper_service.get_state(account_id)
        position = next(
            (item for item in state.positions if item.instrument_id == instrument_id),
            None,
        )
        if side is OrderSide.SELL:
            return 0 if position is None else position.available_quantity
        quote = self._market_service.latest_quote(str(instrument_id))
        if quote is None or quote.last_price <= 0:
            return 0
        assert state.initial_equity is not None
        budget = state.initial_equity * max_position_percent / Decimal("100")
        current_value = Decimal("0") if position is None else position.market_value
        available = budget - current_value
        if available <= 0:
            return 0
        lots = int(available / quote.last_price / 100)
        return lots * 100

    def _same_direction_already_executed(
        self,
        account_id: str,
        *,
        instrument_id: InstrumentId,
        side: OrderSide,
        decision_time: datetime,
        current_decision_id: str,
    ) -> bool:
        today = decision_time.astimezone(_CHINA_ZONE).date()
        batch = self._repository.latest_strategy_run_batch(account_id)
        for record in batch:
            if record.instrument_id != str(instrument_id):
                continue
            if record.order_json is None:
                continue
            if record.decision_id == current_decision_id:
                continue
            try:
                signal = json.loads(record.signal_json)
            except (ValueError, TypeError):
                continue
            executed_day = record.decision_time.astimezone(_CHINA_ZONE).date()
            if executed_day != today:
                continue
            action = signal.get("action")
            return isinstance(action, str) and action == side.value
        return False

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


def _model_decision_frame(
    *,
    instrument_id: InstrumentId,
    action: SignalAction,
    price: Decimal,
    decision_time: datetime,
    strategy_id: str,
    strategy_version: str,
    feature_version: str,
    reason: str,
    confidence: Decimal,
) -> QuantDecision:
    """Assemble the model decision via the shared strategy-layer helper.

    The model signal has no online feature frame, so the snapshot is a
    placeholder with zero completed bars.
    """
    return build_model_signal(
        instrument_id=instrument_id,
        action=action,
        price=price,
        decision_time=decision_time,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        feature_version=feature_version,
        reason=reason,
        confidence=confidence,
    )


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

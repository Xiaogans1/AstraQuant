from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_domain import InstrumentId, SignalAction, SignalState
from astraquant_quant.engine import evaluate_intraday_signal


def _bars(closes: list[str], *, last_volume: str = "100") -> list[MarketBar]:
    start = datetime(2026, 8, 6, 1, 30, tzinfo=UTC)
    result: list[MarketBar] = []
    for index, raw_close in enumerate(closes):
        close = Decimal(raw_close)
        volume = Decimal(last_volume if index == len(closes) - 1 else "100")
        result.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index),
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


def _decision_time(bars: list[MarketBar]) -> datetime:
    return bars[-1].timestamp + timedelta(minutes=1)


def test_engine_suppresses_signals_when_market_is_not_live() -> None:
    bars = _bars(["10"] * 20)
    decision = evaluate_intraday_signal(
        InstrumentId.parse("159516.SZSE"),
        bars,
        _decision_time(bars),
        market_live=False,
    )

    assert decision.signal.state is SignalState.SUPPRESSED
    assert decision.signal.action is SignalAction.HOLD
    assert "MARKET_NOT_LIVE" in decision.signal.reason_codes


def test_engine_suppresses_stale_completed_bars() -> None:
    bars = _bars(["10"] * 20)
    decision = evaluate_intraday_signal(
        InstrumentId.parse("159516.SZSE"),
        bars,
        _decision_time(bars) + timedelta(seconds=121),
        market_live=True,
    )

    assert decision.signal.state is SignalState.SUPPRESSED
    assert decision.signal.action is SignalAction.HOLD
    assert "MARKET_DATA_STALE" in decision.signal.reason_codes


def test_engine_reports_warming_up_without_inventing_a_signal() -> None:
    bars = _bars(["10"] * 5)
    decision = evaluate_intraday_signal(
        InstrumentId.parse("159516.SZSE"),
        bars,
        _decision_time(bars),
        market_live=True,
    )

    assert decision.signal.state is SignalState.WARMING_UP
    assert decision.signal.action is SignalAction.HOLD
    assert decision.features.completed_bar_count == 5


def test_engine_emits_buy_for_confirmed_momentum_and_volume() -> None:
    bars = _bars(
        ["10"] * 15 + ["10.01", "10.02", "10.03", "10.04", "10.05"],
        last_volume="400",
    )
    decision = evaluate_intraday_signal(
        InstrumentId.parse("159516.SZSE"),
        bars,
        _decision_time(bars),
        market_live=True,
    )

    assert decision.signal.state is SignalState.ACTIVE
    assert decision.signal.action is SignalAction.BUY
    assert decision.signal.reference_price == Decimal("10.05")
    assert "MOMENTUM_VOLUME_BREAKOUT" in decision.signal.reason_codes


def test_engine_emits_sell_only_as_an_exit_or_avoidance_signal() -> None:
    bars = _bars(["10"] * 15 + ["9.99", "9.98", "9.97", "9.96", "9.95"])
    decision = evaluate_intraday_signal(
        InstrumentId.parse("159516.SZSE"),
        bars,
        _decision_time(bars),
        market_live=True,
    )

    assert decision.signal.action is SignalAction.SELL
    assert "DOWNTREND_EXIT" in decision.signal.reason_codes


def test_engine_holds_when_thresholds_are_not_confirmed() -> None:
    bars = _bars(["10"] * 20)
    decision = evaluate_intraday_signal(
        InstrumentId.parse("159516.SZSE"),
        bars,
        _decision_time(bars),
        market_live=True,
    )

    assert decision.signal.state is SignalState.ACTIVE
    assert decision.signal.action is SignalAction.HOLD
    assert decision.signal.reason_codes == ("NO_CONFIRMED_EDGE",)


def test_engine_ids_are_reproducible_for_the_same_market_cutoff() -> None:
    bars = _bars(["10"] * 20)
    first = evaluate_intraday_signal(
        InstrumentId.parse("159516.SZSE"),
        bars,
        _decision_time(bars),
        market_live=True,
    )
    second = evaluate_intraday_signal(
        InstrumentId.parse("159516.SZSE"),
        list(reversed(bars)),
        _decision_time(bars),
        market_live=True,
    )

    assert first.signal.signal_id == second.signal.signal_id
    assert first.decision_record.decision_id == second.decision_record.decision_id
    assert first.decision_record.feature_snapshot_id == first.features.feature_snapshot_id

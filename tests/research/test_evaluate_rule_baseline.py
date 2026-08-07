from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_domain import InstrumentId
from tools.research.evaluate_rule_baseline import run_rule_backtest


def _bars(closes: list[str]) -> list[MarketBar]:
    start = datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    result: list[MarketBar] = []
    for index, close in enumerate(closes):
        volume = Decimal("400") if 15 <= index < 22 else Decimal("100")
        result.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index),
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=volume,
                turnover=Decimal(close) * volume,
                previous_close=Decimal("10"),
            )
        )
    return result


def test_rule_backtest_tracks_buy_sell_round_trip() -> None:
    # Ramp up with volume (BUY), then drop hard (SELL).
    closes = ["10"] * 15 + ["10.01", "10.02", "10.03", "10.04", "10.05"]
    closes += ["9.99", "9.98", "9.97", "9.96", "9.95"] + ["10"] * 10
    result = run_rule_backtest(
        _bars(closes),
        instrument_id=InstrumentId.parse("159516.SZSE"),
    )

    assert result["buys"] >= 1
    assert result["sells"] >= 1
    assert result["holds"] > 0
    assert result["open_position"] == 0
    assert result["realized_pnl"] < 0  # bought high, sold low

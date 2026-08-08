from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_domain import InstrumentId
from astraquant_quant.features import (
    RealtimeFeatureStatus,
    build_intraday_features,
)


def _bar(index: int, *, volume: str | None = None) -> MarketBar:
    close = Decimal("10") + Decimal(index) / Decimal("100")
    return MarketBar(
        timestamp=datetime(2026, 8, 6, 1, 30, tzinfo=UTC) + timedelta(minutes=index),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal(volume) if volume is not None else Decimal(index + 10),
        turnover=close * Decimal(index + 10),
        previous_close=Decimal("9.90"),
    )


def test_features_exclude_the_current_unfinished_minute() -> None:
    bars = [_bar(index) for index in range(21)]
    decision_time = datetime(2026, 8, 6, 1, 50, 30, tzinfo=UTC)

    snapshot = build_intraday_features(
        InstrumentId.parse("159516.SZSE"),
        bars,
        decision_time,
    )

    assert snapshot.status is RealtimeFeatureStatus.READY
    assert snapshot.completed_bar_count == 20
    assert snapshot.latest_bar == bars[19]
    assert snapshot.frame is not None
    row = snapshot.frame.rows[0]
    assert row.event_time == bars[19].timestamp
    assert row.available_time == bars[19].timestamp + timedelta(minutes=1)
    assert tuple(row.values) == (
        "ma_20_gap",
        "ma_5_gap",
        "realized_volatility_20",
        "return_1m",
        "return_5m",
        "volume_ratio_20",
    )


def test_feature_snapshot_identity_is_deterministic() -> None:
    bars = [_bar(index) for index in range(20)]
    decision_time = datetime(2026, 8, 6, 1, 50, tzinfo=UTC)

    first = build_intraday_features(
        InstrumentId.parse("159516.SZSE"),
        bars,
        decision_time,
    )
    second = build_intraday_features(
        InstrumentId.parse("159516.SZSE"),
        list(reversed(bars)),
        decision_time,
    )

    assert first.feature_snapshot_id == second.feature_snapshot_id
    assert first.frame == second.frame


def test_feature_builder_reports_warming_up_instead_of_guessing() -> None:
    snapshot = build_intraday_features(
        InstrumentId.parse("159516.SZSE"),
        [_bar(index) for index in range(19)],
        datetime(2026, 8, 6, 1, 50, tzinfo=UTC),
    )

    assert snapshot.status is RealtimeFeatureStatus.WARMING_UP
    assert snapshot.frame is None
    assert snapshot.reason_codes == ("INSUFFICIENT_COMPLETED_BARS",)
    assert snapshot.completed_bar_count == 19


def test_volume_ratio_uses_only_completed_bars() -> None:
    bars = [_bar(index, volume="100") for index in range(20)]
    bars.append(_bar(20, volume="1000000"))

    snapshot = build_intraday_features(
        InstrumentId.parse("159516.SZSE"),
        bars,
        datetime(2026, 8, 6, 1, 50, 30, tzinfo=UTC),
    )

    assert snapshot.frame is not None
    assert snapshot.frame.rows[0].values["volume_ratio_20"] == 1.0

"""Point-in-time intraday features built only from completed minute bars."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from itertools import pairwise
from typing import Final

from astraquant_data.market_bars import MarketBar
from astraquant_domain import FeatureFrame, FeatureRow, InstrumentId

FEATURE_VERSION: Final = "intraday-v1"
_MINIMUM_BARS: Final = 20
_ONE_MINUTE: Final = timedelta(minutes=1)


class RealtimeFeatureStatus(StrEnum):
    READY = "READY"
    WARMING_UP = "WARMING_UP"


@dataclass(frozen=True, slots=True)
class RealtimeFeatureSnapshot:
    feature_snapshot_id: str
    status: RealtimeFeatureStatus
    completed_bar_count: int
    latest_bar: MarketBar | None
    frame: FeatureFrame | None
    reason_codes: tuple[str, ...]


def build_intraday_features(
    instrument_id: InstrumentId,
    bars: list[MarketBar],
    decision_time: datetime,
) -> RealtimeFeatureSnapshot:
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise ValueError("decision_time must be timezone-aware")
    unique = {item.timestamp: item for item in bars}
    completed = [
        unique[timestamp]
        for timestamp in sorted(unique)
        if timestamp + _ONE_MINUTE <= decision_time
    ]
    latest = completed[-1] if completed else None
    if len(completed) < _MINIMUM_BARS:
        reason_codes = ("INSUFFICIENT_COMPLETED_BARS",)
        return RealtimeFeatureSnapshot(
            feature_snapshot_id=_snapshot_id(
                instrument_id,
                completed,
                decision_time,
                values=None,
            ),
            status=RealtimeFeatureStatus.WARMING_UP,
            completed_bar_count=len(completed),
            latest_bar=latest,
            frame=None,
            reason_codes=reason_codes,
        )

    values = _feature_values(completed)
    assert latest is not None
    frame = FeatureFrame(
        decision_time=decision_time,
        definition_version=FEATURE_VERSION,
        rows=(
            FeatureRow(
                instrument_id=instrument_id,
                event_time=latest.timestamp,
                available_time=latest.timestamp + _ONE_MINUTE,
                values={
                    name: None if value is None else float(value) for name, value in values.items()
                },
            ),
        ),
    )
    return RealtimeFeatureSnapshot(
        feature_snapshot_id=_snapshot_id(
            instrument_id,
            completed,
            decision_time,
            values=values,
        ),
        status=RealtimeFeatureStatus.READY,
        completed_bar_count=len(completed),
        latest_bar=latest,
        frame=frame,
        reason_codes=("FEATURES_READY",),
    )


def _feature_values(bars: list[MarketBar]) -> dict[str, Decimal | None]:
    recent = bars[-_MINIMUM_BARS:]
    close = recent[-1].close
    closes = [item.close for item in recent]
    volumes = [item.volume for item in recent]
    returns = [(current / previous) - Decimal("1") for previous, current in pairwise(closes)]
    mean_return = sum(returns, start=Decimal("0")) / Decimal(len(returns))
    variance = sum(((item - mean_return) ** 2 for item in returns), start=Decimal("0")) / Decimal(
        len(returns)
    )
    mean_volume = sum(volumes, start=Decimal("0")) / Decimal(len(volumes))
    with localcontext() as context:
        context.prec = 28
        realized_volatility = variance.sqrt()
    return {
        "return_1m": (close / closes[-2]) - Decimal("1"),
        "return_5m": (close / closes[-6]) - Decimal("1"),
        "ma_5_gap": (close / _mean(closes[-5:])) - Decimal("1"),
        "ma_20_gap": (close / _mean(closes)) - Decimal("1"),
        "volume_ratio_20": None if mean_volume == 0 else volumes[-1] / mean_volume,
        "realized_volatility_20": realized_volatility,
    }


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, start=Decimal("0")) / Decimal(len(values))


def _snapshot_id(
    instrument_id: InstrumentId,
    bars: list[MarketBar],
    decision_time: datetime,
    *,
    values: dict[str, Decimal | None] | None,
) -> str:
    payload = {
        "instrument_id": str(instrument_id),
        "decision_time": decision_time.isoformat(),
        "definition_version": FEATURE_VERSION,
        "bars": [
            {
                "timestamp": item.timestamp.isoformat(),
                "open": str(item.open),
                "high": str(item.high),
                "low": str(item.low),
                "close": str(item.close),
                "volume": str(item.volume),
                "turnover": str(item.turnover),
            }
            for item in bars
        ],
        "values": (
            None
            if values is None
            else {
                name: None if value is None else str(value)
                for name, value in sorted(values.items())
            }
        ),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"feature-{digest[:24]}"

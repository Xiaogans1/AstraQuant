"""Bounded subscription lanes for the Eastmoney free realtime quota."""

from collections import OrderedDict
from dataclasses import dataclass

from astraquant_domain import InstrumentId


@dataclass(frozen=True, slots=True)
class InstrumentDefinition:
    instrument_id: str
    name: str
    kind: str
    lane: str

    def __post_init__(self) -> None:
        canonical = str(InstrumentId.parse(self.instrument_id))
        object.__setattr__(self, "instrument_id", canonical)
        if not self.name.strip():
            raise ValueError("instrument name must not be empty")


CORE_INDICES = (
    InstrumentDefinition("000001.SSE", "上证指数", "index", "core"),
    InstrumentDefinition("399001.SZSE", "深证成指", "index", "core"),
    InstrumentDefinition("399006.SZSE", "创业板指", "index", "core"),
    InstrumentDefinition("000688.SSE", "科创50", "index", "core"),
    InstrumentDefinition("000300.SSE", "沪深300", "index", "core"),
    InstrumentDefinition("399852.SZSE", "中证1000", "index", "core"),
)
_CORE_IDS = frozenset(item.instrument_id for item in CORE_INDICES)


class SubscriptionLimitReached(ValueError):
    pass


class SubscriptionBudget:
    """Reserve 6 core, 34 persistent and 10 LRU temporary instruments."""

    persistent_capacity = 34
    temporary_capacity = 10
    maximum_instruments = 50

    def __init__(self) -> None:
        self._persistent: OrderedDict[str, None] = OrderedDict()
        self._temporary: OrderedDict[str, None] = OrderedDict()

    @property
    def persistent_instruments(self) -> tuple[str, ...]:
        return tuple(self._persistent)

    @property
    def temporary_instruments(self) -> tuple[str, ...]:
        return tuple(self._temporary)

    def add_persistent(self, instrument_id: str) -> None:
        canonical = str(InstrumentId.parse(instrument_id))
        if canonical in _CORE_IDS or canonical in self._persistent:
            return
        if len(self._persistent) >= self.persistent_capacity:
            raise SubscriptionLimitReached("persistent watchlist limit reached")
        self._temporary.pop(canonical, None)
        self._persistent[canonical] = None

    def add_temporary(self, instrument_id: str) -> None:
        canonical = str(InstrumentId.parse(instrument_id))
        if canonical in _CORE_IDS or canonical in self._persistent:
            return
        if canonical in self._temporary:
            self._temporary.move_to_end(canonical)
            return
        self._temporary[canonical] = None
        while len(self._temporary) > self.temporary_capacity:
            self._temporary.popitem(last=False)

    def remove(self, instrument_id: str) -> None:
        canonical = str(InstrumentId.parse(instrument_id))
        if canonical in _CORE_IDS:
            raise ValueError("core index subscriptions cannot be removed")
        self._persistent.pop(canonical, None)
        self._temporary.pop(canonical, None)

    def active_instruments(self) -> tuple[str, ...]:
        active = (
            tuple(item.instrument_id for item in CORE_INDICES)
            + tuple(self._persistent)
            + tuple(self._temporary)
        )
        if len(active) > self.maximum_instruments:
            raise AssertionError("subscription budget exceeded")
        return active

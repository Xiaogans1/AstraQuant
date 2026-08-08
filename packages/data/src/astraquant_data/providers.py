"""Read-only contracts for historical and streaming market-data providers."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId, Tick


@dataclass(frozen=True, slots=True)
class HistoryRequest:
    instrument_id: InstrumentId
    frequency: BarFrequency
    start: date
    end: date
    adjustment: Adjustment = Adjustment.NONE

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("end must not precede start")


class HistoricalDataProvider(Protocol):
    def provider_id(self) -> str: ...

    def fetch_bars(self, request: HistoryRequest) -> Sequence[Bar]: ...


class StreamingDataProvider(Protocol):
    def provider_id(self) -> str: ...

    def subscribe(
        self,
        instruments: Sequence[InstrumentId],
    ) -> AsyncIterator[Tick | Bar]: ...

"""Deterministic streaming replay for tests and offline development."""

from collections.abc import AsyncIterator, Iterable, Sequence

from astraquant_domain import Bar, InstrumentId, Tick


class ReplayStreamingProvider:
    def __init__(self, events: Iterable[Tick | Bar]) -> None:
        self._events = tuple(
            sorted(events, key=lambda event: (event.event_time, event.available_time))
        )

    def provider_id(self) -> str:
        return "replay"

    async def subscribe(
        self,
        instruments: Sequence[InstrumentId],
    ) -> AsyncIterator[Tick | Bar]:
        selected = set(instruments)
        for event in self._events:
            if event.instrument_id in selected:
                yield event

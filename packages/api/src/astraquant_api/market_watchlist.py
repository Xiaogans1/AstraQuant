"""Versioned local persistence for the ordered market watchlist."""

from __future__ import annotations

from dataclasses import dataclass

from astraquant_api.market_config import SettingsStore
from astraquant_data.subscriptions import CORE_INDICES, SubscriptionBudget
from astraquant_domain import InstrumentId, Venue

_SETTING_KEY = "market.watchlist"
_FORMAT_VERSION = 1
_CORE_IDS = frozenset(item.instrument_id for item in CORE_INDICES)
_FUTURE_VENUES = frozenset(
    {
        Venue.CFFEX,
        Venue.SHFE,
        Venue.DCE,
        Venue.CZCE,
        Venue.INE,
        Venue.GFEX,
    }
)


@dataclass(frozen=True, slots=True)
class WatchlistEntry:
    instrument_id: str
    name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            str(InstrumentId.parse(self.instrument_id)),
        )
        normalized_name = None if self.name is None else self.name.strip() or None
        object.__setattr__(self, "name", normalized_name)


def load_watchlist(settings: SettingsStore) -> tuple[WatchlistEntry, ...]:
    stored = settings.get_setting(_SETTING_KEY)
    if not isinstance(stored, dict) or stored.get("version") != _FORMAT_VERSION:
        return ()
    items = stored.get("items")
    if not isinstance(items, list):
        return ()

    restored: list[WatchlistEntry] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("instrument_id")
        raw_name = item.get("name")
        if not isinstance(raw_id, str):
            continue
        name = raw_name if isinstance(raw_name, str) else None
        try:
            entry = WatchlistEntry(raw_id, name)
        except ValueError:
            continue
        instrument_id = InstrumentId.parse(entry.instrument_id)
        if instrument_id.venue in _FUTURE_VENUES and instrument_id.symbol.endswith("0"):
            continue
        if entry.instrument_id in _CORE_IDS or entry.instrument_id in seen:
            continue
        restored.append(entry)
        seen.add(entry.instrument_id)
        if len(restored) >= SubscriptionBudget.persistent_capacity:
            break
    return tuple(restored)


def save_watchlist(
    settings: SettingsStore,
    entries: tuple[WatchlistEntry, ...],
) -> None:
    settings.set_setting(
        _SETTING_KEY,
        {
            "version": _FORMAT_VERSION,
            "items": [
                {
                    "instrument_id": entry.instrument_id,
                    "name": entry.name,
                }
                for entry in entries
            ],
        },
    )

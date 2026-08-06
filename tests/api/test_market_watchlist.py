from astraquant_api.market_watchlist import (
    WatchlistEntry,
    load_watchlist,
    save_watchlist,
)
from astraquant_data.subscriptions import SubscriptionBudget


class MemorySettings:
    def __init__(self, value: object | None = None) -> None:
        self.value = value

    def get_setting(self, key: str) -> object | None:
        assert key == "market.watchlist"
        return self.value

    def set_setting(self, key: str, value: object) -> None:
        assert key == "market.watchlist"
        self.value = value


def test_load_watchlist_preserves_valid_order_and_skips_bad_records() -> None:
    items: list[object] = [
        {"instrument_id": "600000.SSE", "name": " 浦发银行 "},
        {"instrument_id": "invalid", "name": "损坏记录"},
        {"instrument_id": "600000.SSE", "name": "重复记录"},
        {"instrument_id": "000001.SSE", "name": "核心指数"},
        {"instrument_id": "RB0.SHFE", "name": "连续期货"},
        {"instrument_id": "159516.SZSE", "name": ""},
        "not-an-object",
    ]
    items.extend(
        {"instrument_id": f"{600001 + index}.SSE", "name": f"证券{index}"} for index in range(40)
    )
    settings = MemorySettings({"version": 1, "items": items})

    restored = load_watchlist(settings)

    assert restored[0] == WatchlistEntry("600000.SSE", "浦发银行")
    assert restored[1] == WatchlistEntry("159516.SZSE", None)
    assert len(restored) == SubscriptionBudget.persistent_capacity
    assert len({entry.instrument_id for entry in restored}) == len(restored)
    assert all(entry.instrument_id != "000001.SSE" for entry in restored)
    assert all(entry.instrument_id != "RB0.SHFE" for entry in restored)


def test_load_watchlist_treats_unknown_shapes_as_empty() -> None:
    assert load_watchlist(MemorySettings(None)) == ()
    assert load_watchlist(MemorySettings(["600000.SSE"])) == ()
    assert load_watchlist(MemorySettings({"version": 2, "items": []})) == ()
    assert load_watchlist(MemorySettings({"version": 1, "items": "bad"})) == ()


def test_save_watchlist_writes_only_versioned_identity_metadata() -> None:
    settings = MemorySettings()

    save_watchlist(
        settings,
        (
            WatchlistEntry("600000.SSE", "浦发银行"),
            WatchlistEntry("159516.SZSE", None),
        ),
    )

    assert settings.value == {
        "version": 1,
        "items": [
            {"instrument_id": "600000.SSE", "name": "浦发银行"},
            {"instrument_id": "159516.SZSE", "name": None},
        ],
    }
    serialized = str(settings.value).lower()
    assert "price" not in serialized
    assert "token" not in serialized
    assert "account" not in serialized

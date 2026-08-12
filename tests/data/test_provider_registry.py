import pytest

from astraquant_data.provider_registry import ProviderRegistry


def test_registry_selects_registered_provider_by_generic_id() -> None:
    registry = ProviderRegistry[object]()
    expected = object()
    registry.register("akshare", lambda: expected)

    assert registry.create("AKSHARE") is expected
    assert registry.provider_ids() == ("akshare",)


def test_registry_fails_closed_for_duplicates_and_unknown_ids() -> None:
    registry = ProviderRegistry[str]()
    registry.register("eastmoney", lambda: "one")

    with pytest.raises(ValueError, match="already registered"):
        registry.register("EASTMONEY", lambda: "two")
    with pytest.raises(ValueError, match=r"unknown provider.*eastmoney"):
        registry.create("akshare")

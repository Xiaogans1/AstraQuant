"""Provider selection without coupling callers to a vendor implementation."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class ProviderRegistry[T]:
    """Small fail-closed registry for provider factories."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], T]] = {}

    def register(self, provider_id: str, factory: Callable[[], T]) -> None:
        normalized = _provider_id(provider_id)
        if normalized in self._factories:
            raise ValueError(f"provider already registered: {normalized}")
        self._factories[normalized] = factory

    def create(self, provider_id: str) -> T:
        normalized = _provider_id(provider_id)
        try:
            factory = self._factories[normalized]
        except KeyError:
            available = ", ".join(self.provider_ids()) or "none"
            raise ValueError(
                f"unknown provider {normalized!r}; registered providers: {available}"
            ) from None
        return factory()

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


def _provider_id(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or not normalized.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"invalid provider_id: {value!r}")
    return normalized

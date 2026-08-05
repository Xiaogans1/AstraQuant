from collections.abc import MutableMapping

import pytest

from astraquant_api.secret_store import (
    CredentialSecretStore,
    MemorySecretStore,
    SecretStoreUnavailable,
)


class FakeKeyring:
    def __init__(self) -> None:
        self.values: MutableMapping[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def test_memory_store_round_trips_without_exposing_backend_metadata() -> None:
    store = MemorySecretStore()
    store.set_eastmoney_token("a-secure-token-value")
    assert store.get_eastmoney_token() == "a-secure-token-value"
    assert not hasattr(store, "service")
    store.delete_eastmoney_token()
    assert store.get_eastmoney_token() is None


@pytest.mark.parametrize("value", ["", "   ", "short"])
def test_secret_stores_reject_blank_or_short_values(value: str) -> None:
    with pytest.raises(ValueError, match="token"):
        MemorySecretStore().set_eastmoney_token(value)


def test_credential_store_uses_fixed_non_account_metadata() -> None:
    backend = FakeKeyring()
    store = CredentialSecretStore(backend=backend)
    store.set_eastmoney_token("valid-token-value")

    assert backend.values == {
        ("com.xiaogans1.astraquant/eastmoney", "market-data-token"): "valid-token-value"
    }
    assert store.get_eastmoney_token() == "valid-token-value"
    store.delete_eastmoney_token()
    assert store.get_eastmoney_token() is None


def test_credential_backend_failures_are_sanitized() -> None:
    class BrokenKeyring(FakeKeyring):
        def set_password(self, service: str, account: str, value: str) -> None:
            raise RuntimeError(f"failed for {value}")

    with pytest.raises(SecretStoreUnavailable) as captured:
        CredentialSecretStore(backend=BrokenKeyring()).set_eastmoney_token("never-leak-this")
    assert "never-leak-this" not in str(captured.value)

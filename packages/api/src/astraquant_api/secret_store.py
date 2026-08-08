"""Operating-system credential storage for market-data secrets."""

from __future__ import annotations

from typing import Protocol

_SERVICE = "com.xiaogans1.astraquant/eastmoney"
_ACCOUNT = "market-data-token"
_MINIMUM_TOKEN_LENGTH = 8


class SecretStoreUnavailable(RuntimeError):
    """Raised when the operating-system credential backend cannot be used."""


class SecretStore(Protocol):
    def get_eastmoney_token(self) -> str | None: ...

    def set_eastmoney_token(self, token: str) -> None: ...

    def delete_eastmoney_token(self) -> None: ...


class _KeyringBackend(Protocol):
    def get_password(self, service: str, account: str) -> str | None: ...

    def set_password(self, service: str, account: str, value: str) -> None: ...

    def delete_password(self, service: str, account: str) -> None: ...


def _validated_token(token: str) -> str:
    normalized = token.strip()
    if len(normalized) < _MINIMUM_TOKEN_LENGTH:
        raise ValueError("Eastmoney token is blank or too short")
    return normalized


class MemorySecretStore:
    """In-memory implementation for tests and unsupported environments."""

    def __init__(self, token: str | None = None) -> None:
        self._token = None if token is None else _validated_token(token)

    def get_eastmoney_token(self) -> str | None:
        return self._token

    def set_eastmoney_token(self, token: str) -> None:
        self._token = _validated_token(token)

    def delete_eastmoney_token(self) -> None:
        self._token = None


class CredentialSecretStore:
    """Store the Eastmoney token through the platform keyring backend."""

    def __init__(self, *, backend: _KeyringBackend | None = None) -> None:
        if backend is None:
            import keyring

            backend = keyring
        self._backend = backend

    def get_eastmoney_token(self) -> str | None:
        try:
            token = self._backend.get_password(_SERVICE, _ACCOUNT)
        except Exception as error:
            raise SecretStoreUnavailable("Credential store is unavailable") from error
        return token.strip() if token and token.strip() else None

    def set_eastmoney_token(self, token: str) -> None:
        normalized = _validated_token(token)
        try:
            self._backend.set_password(_SERVICE, _ACCOUNT, normalized)
        except Exception as error:
            raise SecretStoreUnavailable("Credential store is unavailable") from error

    def delete_eastmoney_token(self) -> None:
        try:
            self._backend.delete_password(_SERVICE, _ACCOUNT)
        except Exception as error:
            raise SecretStoreUnavailable("Credential store is unavailable") from error

"""Non-secret Eastmoney runtime configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_SETTING_KEY = "market.eastmoney"
_SCHEMA_VERSION = 2


class SettingsStore(Protocol):
    def get_setting(self, key: str) -> object | None: ...

    def set_setting(self, key: str, value: object) -> None: ...


@dataclass(frozen=True, slots=True)
class EastmoneyRuntimeConfig:
    sdk_python: Path | None
    poll_interval_seconds: float = 1.0
    stale_after_seconds: float = 10.0
    request_timeout_seconds: float = 8.0
    maximum_instruments: int = 50

    def __post_init__(self) -> None:
        if self.sdk_python is not None:
            object.__setattr__(self, "sdk_python", self.sdk_python.expanduser().resolve())
        if self.poll_interval_seconds < 1:
            raise ValueError("poll interval must be at least one second")
        if self.stale_after_seconds <= self.poll_interval_seconds:
            raise ValueError("stale threshold must be greater than the poll interval")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request timeout must be positive")
        if self.maximum_instruments != 50:
            raise ValueError("Eastmoney free provider currently requires a 50-instrument limit")


def _existing_file(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser().resolve()
    return path if path.is_file() else None


def load_eastmoney_runtime_config(
    settings: SettingsStore,
    *,
    environ: Mapping[str, str] | None = None,
) -> EastmoneyRuntimeConfig:
    environment = os.environ if environ is None else environ
    stored = settings.get_setting(_SETTING_KEY)
    stored_values = stored if isinstance(stored, dict) else {}
    schema_version = int(stored_values.get("schema_version", 1))
    sdk_python = _existing_file(environment.get("ASTRAQUANT_EASTMONEY_PYTHON"))
    if sdk_python is None:
        sdk_python = _existing_file(stored_values.get("sdk_python_path"))
    return EastmoneyRuntimeConfig(
        sdk_python=sdk_python,
        poll_interval_seconds=(
            float(stored_values.get("poll_interval_seconds", 1.0))
            if schema_version >= _SCHEMA_VERSION
            else 1.0
        ),
        stale_after_seconds=float(stored_values.get("stale_after_seconds", 10.0)),
        request_timeout_seconds=float(stored_values.get("request_timeout_seconds", 8.0)),
        maximum_instruments=int(stored_values.get("maximum_instruments", 50)),
    )


def save_eastmoney_runtime_config(
    settings: SettingsStore,
    config: EastmoneyRuntimeConfig,
) -> None:
    settings.set_setting(
        _SETTING_KEY,
        {
            "schema_version": _SCHEMA_VERSION,
            "sdk_python_path": None if config.sdk_python is None else str(config.sdk_python),
            "poll_interval_seconds": config.poll_interval_seconds,
            "stale_after_seconds": config.stale_after_seconds,
            "request_timeout_seconds": config.request_timeout_seconds,
            "maximum_instruments": config.maximum_instruments,
        },
    )

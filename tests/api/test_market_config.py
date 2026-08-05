from pathlib import Path

import pytest

from astraquant_api.market_config import (
    EastmoneyRuntimeConfig,
    load_eastmoney_runtime_config,
    save_eastmoney_runtime_config,
)


class MemorySettings:
    def __init__(self, value: object | None = None) -> None:
        self.value = value

    def get_setting(self, key: str) -> object | None:
        assert key == "market.eastmoney"
        return self.value

    def set_setting(self, key: str, value: object) -> None:
        assert key == "market.eastmoney"
        self.value = value


def test_environment_sdk_path_takes_precedence(tmp_path: Path) -> None:
    stored = tmp_path / "stored-python.exe"
    stored.touch()
    environment = tmp_path / "environment-python.exe"
    environment.touch()
    settings = MemorySettings({"sdk_python_path": str(stored)})

    config = load_eastmoney_runtime_config(
        settings,
        environ={"ASTRAQUANT_EASTMONEY_PYTHON": str(environment)},
    )

    assert config.sdk_python == environment.resolve()


def test_stored_non_secret_path_is_used_when_it_exists(tmp_path: Path) -> None:
    sdk_python = tmp_path / "python.exe"
    sdk_python.touch()
    settings = MemorySettings({"sdk_python_path": str(sdk_python)})

    config = load_eastmoney_runtime_config(settings, environ={})

    assert config.sdk_python == sdk_python.resolve()


def test_missing_sdk_path_resolves_to_none(tmp_path: Path) -> None:
    settings = MemorySettings({"sdk_python_path": str(tmp_path / "missing.exe")})
    assert load_eastmoney_runtime_config(settings, environ={}).sdk_python is None


def test_runtime_config_rejects_a_subsecond_poll_interval() -> None:
    with pytest.raises(ValueError):
        EastmoneyRuntimeConfig(sdk_python=None, poll_interval_seconds=0.9)


def test_runtime_config_requires_stale_threshold_after_poll_interval() -> None:
    with pytest.raises(ValueError):
        EastmoneyRuntimeConfig(
            sdk_python=None,
            poll_interval_seconds=3,
            stale_after_seconds=3,
        )


def test_runtime_config_fixes_the_free_provider_limit_at_fifty() -> None:
    with pytest.raises(ValueError):
        EastmoneyRuntimeConfig(sdk_python=None, maximum_instruments=49)


def test_save_persists_only_non_secret_configuration(tmp_path: Path) -> None:
    sdk_python = tmp_path / "python.exe"
    sdk_python.touch()
    settings = MemorySettings()
    config = EastmoneyRuntimeConfig(sdk_python=sdk_python)

    save_eastmoney_runtime_config(settings, config)

    assert settings.value == {
        "sdk_python_path": str(sdk_python.resolve()),
        "poll_interval_seconds": 3.0,
        "stale_after_seconds": 10.0,
        "request_timeout_seconds": 8.0,
        "maximum_instruments": 50,
    }
    assert "token" not in str(settings.value).lower()

from pathlib import Path

import pytest

from astraquant_api.config import RuntimeConfig


def test_load_config_requires_token_and_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASTRAQUANT_SESSION_TOKEN", "x" * 43)
    monkeypatch.setenv("ASTRAQUANT_STATE_DIR", str(tmp_path))

    config = RuntimeConfig.from_environment()

    assert config.host == "127.0.0.1"
    assert config.port == 0
    assert config.database_path.parent == tmp_path / "state"
    assert config.log_dir == tmp_path / "logs"


def test_reject_short_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASTRAQUANT_SESSION_TOKEN", "short")
    monkeypatch.setenv("ASTRAQUANT_STATE_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="session token"):
        RuntimeConfig.from_environment()

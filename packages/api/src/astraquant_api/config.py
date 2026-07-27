from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    session_token: str
    state_dir: Path
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = 0
    shutdown_grace_seconds: float = 5.0

    def __post_init__(self) -> None:
        if len(self.session_token) < 43:
            raise ValueError("session token must contain at least 43 characters")
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.shutdown_grace_seconds <= 0:
            raise ValueError("shutdown grace period must be positive")

    @property
    def database_path(self) -> Path:
        return self.state_dir / "state" / "astraquant.sqlite3"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @classmethod
    def from_environment(cls) -> RuntimeConfig:
        token = os.environ.get("ASTRAQUANT_SESSION_TOKEN", "")
        raw_state_dir = os.environ.get("ASTRAQUANT_STATE_DIR", ".astraquant")
        state_dir = Path(raw_state_dir).expanduser().resolve()
        config = cls(
            session_token=token,
            state_dir=state_dir,
            port=int(os.environ.get("ASTRAQUANT_PORT", "0")),
            shutdown_grace_seconds=float(os.environ.get("ASTRAQUANT_SHUTDOWN_GRACE_SECONDS", "5")),
        )
        config.database_path.parent.mkdir(parents=True, exist_ok=True)
        config.log_dir.mkdir(parents=True, exist_ok=True)
        return config

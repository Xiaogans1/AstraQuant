from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


def validate_runtime_root_layout(
    state_dir: Path,
    roots: Mapping[str, Path],
) -> dict[str, Path]:
    """Resolve leaf roots and reject escapes or overlapping write domains."""

    canonical_state = state_dir.expanduser().resolve()
    canonical: dict[str, Path] = {}
    for name, path in roots.items():
        resolved = path.expanduser().resolve()
        if not resolved.is_relative_to(canonical_state):
            raise ValueError(f"runtime root {name!r} escapes state directory")
        canonical[name] = resolved
    items = tuple(canonical.items())
    for index, (first_name, first) in enumerate(items):
        for second_name, second in items[index + 1 :]:
            if first == second or first in second.parents or second in first.parents:
                raise ValueError(f"runtime roots {first_name!r} and {second_name!r} overlap")
    return canonical


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    session_token: str
    state_dir: Path
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = 0
    shutdown_grace_seconds: float = 5.0
    allowed_data_instruments: frozenset[str] = frozenset({"600000.SSE", "RB0.SHFE"})
    enable_akshare: bool = False
    market_provider_id: Literal["auto", "eastmoney", "akshare", "none"] = "auto"

    def __post_init__(self) -> None:
        if len(self.session_token) < 43:
            raise ValueError("session token must contain at least 43 characters")
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.shutdown_grace_seconds <= 0:
            raise ValueError("shutdown grace period must be positive")
        if self.market_provider_id not in {"auto", "eastmoney", "akshare", "none"}:
            raise ValueError("unsupported market provider")

    @property
    def database_path(self) -> Path:
        return self.state_dir / "state" / "astraquant.sqlite3"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def legacy_data_root(self) -> Path:
        return self.state_dir / "data"

    @property
    def formal_root(self) -> Path:
        return self.state_dir / "formal"

    @property
    def formal_qualification_root(self) -> Path:
        return self.formal_root / "qualification"

    @property
    def formal_capture_root(self) -> Path:
        return self.formal_root / "capture"

    @property
    def formal_publication_root(self) -> Path:
        return self.formal_root / "publication"

    @property
    def formal_verification_root(self) -> Path:
        return self.formal_root / "verification"

    def prepare_directories(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.formal_root.mkdir(parents=True, exist_ok=True)
        roots = validate_runtime_root_layout(
            self.state_dir,
            {
                "legacy_data": self.legacy_data_root,
                "formal_qualification": self.formal_qualification_root,
                "formal_capture": self.formal_capture_root,
                "formal_publication": self.formal_publication_root,
                "formal_verification": self.formal_verification_root,
            },
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for path in roots.values():
            path.mkdir(parents=True, exist_ok=True)
        validate_runtime_root_layout(self.state_dir, roots)

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
            allowed_data_instruments=frozenset(
                item.strip().upper()
                for item in os.environ.get(
                    "ASTRAQUANT_DATA_INSTRUMENTS",
                    "600000.SSE,RB0.SHFE",
                ).split(",")
                if item.strip()
            ),
            enable_akshare=os.environ.get("ASTRAQUANT_ENABLE_AKSHARE", "0") == "1",
            market_provider_id=os.environ.get("ASTRAQUANT_MARKET_PROVIDER", "auto").lower(),  # type: ignore[arg-type]
        )
        config.prepare_directories()
        return config

"""Run a bounded Eastmoney session probe without persisting raw market data."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from astraquant_api.database import create_database, migrate_database
from astraquant_api.market_config import load_eastmoney_runtime_config
from astraquant_api.repository import TaskRepository
from astraquant_api.secret_store import CredentialSecretStore
from astraquant_data.adapters.eastmoney import EastmoneyProvider
from astraquant_data.eastmoney_client import EastmoneyBridgeClient
from astraquant_domain import InstrumentId, LiveQuote, SystemClock

CORE_INDICES = tuple(
    InstrumentId.parse(value)
    for value in (
        "000001.SSE",
        "399001.SZSE",
        "399006.SZSE",
        "000688.SSE",
        "000300.SSE",
        "399852.SZSE",
    )
)


class ProbeProvider(Protocol):
    def connect(self, token: str) -> None: ...

    def poll(self, instruments: Sequence[InstrumentId]) -> list[LiveQuote]: ...

    def disconnect(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ProbeResult:
    provider_id: str
    started_at: str
    ended_at: str
    requested_instrument_count: int
    received_instrument_count: int
    poll_count: int
    successful_poll_count: int
    first_event_at: str | None
    last_event_at: str | None
    median_age_ms: int | None
    maximum_age_ms: int | None
    parse_error_count: int
    reconnect_count: int
    result: str
    error_code: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def run_probe(
    provider: ProbeProvider,
    *,
    token: str,
    seconds: int,
    poll_interval: float = 3.0,
) -> ProbeResult:
    if seconds < 15 or seconds > 300:
        raise ValueError("seconds must be between 15 and 300")
    started = datetime.now(UTC)
    deadline = time.monotonic() + seconds
    poll_count = 0
    successful_poll_count = 0
    received: set[InstrumentId] = set()
    event_times: list[datetime] = []
    ages_ms: list[int] = []
    result = "NO_DATA"
    error_code: str | None = None
    try:
        provider.connect(token)
        while time.monotonic() < deadline:
            poll_count += 1
            quotes = provider.poll(CORE_INDICES)
            successful_poll_count += 1
            observed_at = datetime.now(UTC)
            for quote in quotes:
                received.add(quote.instrument_id)
                event_times.append(quote.event_time)
                ages_ms.append(max(0, int((observed_at - quote.event_time).total_seconds() * 1000)))
            if poll_interval <= 0:
                break
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        if event_times:
            result = "PASSED"
    except Exception:
        result = "PROVIDER_ERROR"
        error_code = "provider_failure"
    finally:
        try:
            provider.disconnect()
        except Exception:
            if result != "PROVIDER_ERROR":
                result = "PROVIDER_ERROR"
                error_code = "provider_disconnect_failed"
    ended = datetime.now(UTC)
    return ProbeResult(
        provider_id="eastmoney",
        started_at=started.isoformat(),
        ended_at=ended.isoformat(),
        requested_instrument_count=len(CORE_INDICES),
        received_instrument_count=len(received),
        poll_count=poll_count,
        successful_poll_count=successful_poll_count,
        first_event_at=min(event_times).isoformat() if event_times else None,
        last_event_at=max(event_times).isoformat() if event_times else None,
        median_age_ms=int(statistics.median(ages_ms)) if ages_ms else None,
        maximum_age_ms=max(ages_ms) if ages_ms else None,
        parse_error_count=0,
        reconnect_count=0,
        result=result,
        error_code=error_code,
    )


def _build_provider() -> tuple[ProbeProvider, str] | None:
    state_dir = Path(os.environ.get("ASTRAQUANT_STATE_DIR", ".astraquant")).expanduser().resolve()
    database_path = state_dir / "state" / "astraquant.sqlite3"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{database_path}"
    migrate_database(database_url)
    engine = create_database(database_url)
    try:
        config = load_eastmoney_runtime_config(TaskRepository(engine))
    finally:
        engine.dispose()
    token = CredentialSecretStore().get_eastmoney_token()
    if config.sdk_python is None or token is None:
        return None
    client = EastmoneyBridgeClient(
        python_executable=config.sdk_python,
        bridge_script=Path(__file__).with_name("eastmoney_bridge.py"),
        timeout_seconds=config.request_timeout_seconds,
    )
    return EastmoneyProvider(client=client, clock=SystemClock()), token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=60, choices=range(15, 301))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    configured = _build_provider()
    if configured is None:
        print(json.dumps({"provider_id": "eastmoney", "result": "CONFIG_UNAVAILABLE"}))
        return 2
    provider, token = configured
    result = run_probe(provider, token=token, seconds=args.seconds)
    payload = json.dumps(result.as_dict(), ensure_ascii=False, indent=2)
    print(payload)
    if args.output is not None:
        args.output.write_text(payload + "\n", encoding="utf-8")
    if result.result == "PASSED":
        return 0
    return 3 if result.result == "NO_DATA" else 4


if __name__ == "__main__":
    raise SystemExit(main())

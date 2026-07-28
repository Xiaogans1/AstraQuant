# Phase 3A Realtime Market Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only, replaceable A-share realtime market-data vertical slice with deterministic simulation, QMT/XtQuant integration, provider health, local API visibility, and a desktop connection panel.

**Architecture:** Keep exchange-specific payloads inside adapters and publish canonical `LiveTick` records through a narrow async provider protocol. A local `MarketDataService` owns one active provider, consumes its stream, tracks latest ticks and health, and exposes only authenticated loopback endpoints; the desktop polls this diagnostic slice while later phases add recording, scanning, strategy inference, and Paper simulation.

**Tech Stack:** Python 3.12, dataclasses and asyncio, FastAPI/Pydantic, XtQuant loaded lazily from the user's local QMT installation, React 19, TypeScript, TanStack Query, Vitest, Rust/Tauri, uv, GitHub Actions.

---

## Scope and non-goals

This plan implements only Phase 3A from
`docs/superpowers/specs/2026-07-28-realtime-intelligence-foundation-design.md`.

In scope:

- repair the existing PR quality gate before new behavior;
- canonical source metadata and realtime Tick envelopes;
- explicit provider capabilities, connection state, health and failures;
- a deterministic simulated full-market provider for development and CI;
- a lazily loaded QMT/XtQuant full-market read-only adapter;
- a single-provider local runtime service with bounded latest-Tick memory;
- authenticated start, stop, health and latest-Tick endpoints;
- a desktop “数据与连接” status panel;
- a QMT market-session probe and feasibility report template.

Out of scope:

- Tick persistence, minute aggregation and deterministic replay (Phase 3B);
- full-market ranking, index/sector dashboards and candlestick charts (Phase 3C);
- news, Agent Runtime, `daily-market-intelligence` Skill and `DailyStrategyPlan`
  (Phase 4B);
- strategies, model training, `SignalFrame`, Paper matching or real orders;
- CTP implementation; Phase 3A only keeps the provider boundary compatible with it.

The simulated provider must always display `SIMULATED`; it can prove software behavior but
cannot satisfy the real-session QMT acceptance gate.

## File map

| Path | Responsibility |
| --- | --- |
| `.github/workflows/ci.yml` | Run Python formatting only over Python source roots |
| `apps/desktop/src-tauri/Cargo.toml` | Add test-only temporary-directory support |
| `apps/desktop/src-tauri/src/runtime.rs` | Make runtime-launch tests independent of a developer `.venv` |
| `packages/domain/src/astraquant_domain/live_market.py` | Canonical source metadata, quality and `LiveTick` |
| `packages/data/src/astraquant_data/live_providers.py` | Provider capability, health and protocol |
| `packages/data/src/astraquant_data/adapters/disabled.py` | Explicit disabled provider without simulation |
| `packages/data/src/astraquant_data/adapters/simulated.py` | Deterministic CI/development stream |
| `packages/data/src/astraquant_data/adapters/qmt.py` | Lazy XtQuant import, QMT mapping and callback bridge |
| `packages/api/src/astraquant_api/market_service.py` | Provider lifecycle and bounded latest-Tick state |
| `packages/api/src/astraquant_api/market_config.py` | Environment-only realtime provider configuration |
| `packages/api/src/astraquant_api/market_schemas.py` | Strict local API response models |
| `packages/api/src/astraquant_api/market_routes.py` | Authenticated connection and Tick routes |
| `packages/api/src/astraquant_api/app.py` | Attach market service and its router/lifespan |
| `packages/api/src/astraquant_api/cli.py` | Construct selected provider without importing XtQuant early |
| `apps/desktop/src/api/market-contracts.ts` | Realtime API contracts |
| `apps/desktop/src/api/client.ts` | Realtime API client methods |
| `apps/desktop/src/api/queries.ts` | Health polling and start/stop mutations |
| `apps/desktop/src/components/MarketConnectionPanel.tsx` | Provider state, latency and controls |
| `apps/desktop/src/pages/DataPage.tsx` | Promote connections above sample imports |
| `apps/desktop/src/styles/app.css` | Connection panel states and responsive layout |
| `tools/qmt_probe.py` | Explicit real-session feasibility probe |
| `docs/operations/realtime-market-data.md` | Configuration, safety and troubleshooting |
| `docs/research/qmt-feasibility-report.md` | Real-session measurement record |

## Task 0: Restore a trustworthy CI baseline

**Files:**

- Modify: `.github/workflows/ci.yml`
- Modify: `apps/desktop/src-tauri/Cargo.toml`
- Modify: `apps/desktop/src-tauri/src/runtime.rs`
- Test: `apps/desktop/src-tauri/src/runtime.rs`

- [ ] **Step 1: Restrict Ruff to Python source roots**

Replace both Python quality commands in `.github/workflows/ci.yml`:

```yaml
      - run: uv run ruff format --check packages tools tests
      - run: uv run ruff check packages tools tests
```

This prevents Ruff from treating Python examples inside Markdown plans as production source.

- [ ] **Step 2: Add a test-only temporary directory dependency**

Append to `apps/desktop/src-tauri/Cargo.toml`:

```toml
[dev-dependencies]
tempfile = "3.23"
```

Run:

```powershell
cargo update --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Expected: `Cargo.lock` records `tempfile`; production dependencies are unchanged.

- [ ] **Step 3: Replace environment-dependent Rust tests**

In the `runtime.rs` test module, import filesystem support and create an isolated fake managed
environment:

```rust
use std::fs;

use tempfile::TempDir;

fn managed_project_root() -> TempDir {
    let root = tempfile::tempdir().unwrap();
    let virtual_environment = root.path().join(".venv");
    if cfg!(windows) {
        let python_home = root.path().join("python-home");
        fs::create_dir_all(&python_home).unwrap();
        fs::write(python_home.join("python.exe"), b"fixture").unwrap();
        fs::create_dir_all(&virtual_environment).unwrap();
        fs::write(
            virtual_environment.join("pyvenv.cfg"),
            format!("home = {}", python_home.display()),
        )
        .unwrap();
    } else {
        let bin = virtual_environment.join("bin");
        fs::create_dir_all(&bin).unwrap();
        fs::write(bin.join("python"), b"fixture").unwrap();
    }
    root
}
```

Replace the two failing tests with:

```rust
#[test]
fn launches_the_managed_python_process_directly() {
    let root = managed_project_root();
    let spec = runtime_launch_spec(root.path());
    assert!(spec.program.ends_with(if cfg!(windows) {
        "python.exe"
    } else {
        "python"
    }));
    assert_eq!(spec.arguments, ["-m", "astraquant_api.cli", "serve"]);
}

#[test]
fn windows_runtime_exposes_every_workspace_python_package() {
    if !cfg!(windows) {
        return;
    }
    let root = managed_project_root();
    let spec = runtime_launch_spec(root.path());
    let python_path = spec
        .environment
        .iter()
        .find(|(name, _)| name == "PYTHONPATH")
        .map(|(_, value)| value.to_string_lossy())
        .expect("Windows managed runtime must define PYTHONPATH");

    assert!(python_path.contains("packages\\api\\src"));
    assert!(python_path.contains("packages\\data\\src"));
    assert!(python_path.contains("packages\\domain\\src"));
}
```

- [ ] **Step 4: Verify the repaired baseline**

Run:

```powershell
uv run ruff format --check packages tools tests
uv run ruff check packages tools tests
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Expected: Ruff passes; all six Rust tests pass on Windows without relying on the repository
`.venv`.

- [ ] **Step 5: Commit the baseline repair**

```powershell
git add .github/workflows/ci.yml apps/desktop/src-tauri/Cargo.toml apps/desktop/src-tauri/Cargo.lock apps/desktop/src-tauri/src/runtime.rs
git commit -m "fix(ci): 修复跨环境质量门禁"
```

## Task 1: Define canonical realtime market events

**Files:**

- Create: `packages/domain/src/astraquant_domain/live_market.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`
- Create: `tests/domain/test_live_market.py`

- [ ] **Step 1: Write failing source-metadata and LiveTick tests**

Create `tests/domain/test_live_market.py`:

```python
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from astraquant_domain import (
    InstrumentId,
    LiveTick,
    MarketEventMetadata,
    MarketEventQuality,
    QuoteLevel,
    Tick,
)


def make_live_tick() -> LiveTick:
    event_time = datetime(2026, 7, 28, 1, 30, tzinfo=UTC)
    return LiveTick(
        tick=Tick(
            instrument_id=InstrumentId.parse("600000.SSE"),
            event_time=event_time,
            available_time=event_time,
            last_price=Decimal("12.34"),
            volume=Decimal("1200"),
            turnover=Decimal("14808"),
            open_interest=None,
        ),
        trading_date=date(2026, 7, 28),
        metadata=MarketEventMetadata(
            source_id="qmt",
            source_session_id="qmt-session-1",
            received_time=event_time,
            sequence=42,
            quality=frozenset({MarketEventQuality.NORMAL}),
        ),
        bid=(QuoteLevel(Decimal("12.33"), Decimal("300")),),
        ask=(QuoteLevel(Decimal("12.35"), Decimal("200")),),
        limit_up=Decimal("13.57"),
        limit_down=Decimal("11.11"),
        trading_status="OPEN",
    )


def test_live_tick_keeps_source_and_depth_separate_from_canonical_tick() -> None:
    live = make_live_tick()
    assert live.tick.instrument_id == InstrumentId.parse("600000.SSE")
    assert live.metadata.source_id == "qmt"
    assert live.bid[0].price == Decimal("12.33")


def test_market_metadata_rejects_naive_received_time() -> None:
    with pytest.raises(ValueError, match="received_time"):
        MarketEventMetadata(
            source_id="qmt",
            source_session_id="session",
            received_time=datetime(2026, 7, 28),
            sequence=None,
            quality=frozenset({MarketEventQuality.NORMAL}),
        )


def test_depth_rejects_non_positive_price_or_negative_volume() -> None:
    with pytest.raises(ValueError, match="price"):
        QuoteLevel(Decimal("0"), Decimal("1"))
    with pytest.raises(ValueError, match="volume"):
        QuoteLevel(Decimal("1"), Decimal("-1"))
```

- [ ] **Step 2: Run the tests and observe the missing contract**

Run:

```powershell
uv run pytest tests/domain/test_live_market.py -v
```

Expected: collection fails because `LiveTick`, `MarketEventMetadata`,
`MarketEventQuality`, and `QuoteLevel` are not exported.

- [ ] **Step 3: Implement immutable realtime envelopes**

Create `packages/domain/src/astraquant_domain/live_market.py`:

```python
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from astraquant_domain.market_data import Tick


class MarketEventQuality(StrEnum):
    NORMAL = "NORMAL"
    DELAYED = "DELAYED"
    GAP_DETECTED = "GAP_DETECTED"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    CLOCK_SKEW = "CLOCK_SKEW"


@dataclass(frozen=True, slots=True)
class QuoteLevel:
    price: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("quote price must be positive")
        if self.volume < 0:
            raise ValueError("quote volume must be non-negative")


@dataclass(frozen=True, slots=True)
class MarketEventMetadata:
    source_id: str
    source_session_id: str
    received_time: datetime
    sequence: int | None
    quality: frozenset[MarketEventQuality]

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.source_session_id.strip():
            raise ValueError("market source identifiers must not be empty")
        if self.received_time.tzinfo is None or self.received_time.utcoffset() is None:
            raise ValueError("received_time must be timezone-aware")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if not self.quality:
            raise ValueError("market quality must not be empty")


@dataclass(frozen=True, slots=True)
class LiveTick:
    tick: Tick
    trading_date: date
    metadata: MarketEventMetadata
    bid: tuple[QuoteLevel, ...] = ()
    ask: tuple[QuoteLevel, ...] = ()
    limit_up: Decimal | None = None
    limit_down: Decimal | None = None
    trading_status: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if len(self.bid) > 10 or len(self.ask) > 10:
            raise ValueError("market depth cannot exceed ten levels")
        if self.limit_up is not None and self.limit_up <= 0:
            raise ValueError("limit_up must be positive")
        if self.limit_down is not None and self.limit_down <= 0:
            raise ValueError("limit_down must be positive")
        if not self.trading_status.strip():
            raise ValueError("trading_status must not be empty")
```

Export all four symbols from `astraquant_domain.__init__` and add them to `__all__`.

- [ ] **Step 4: Verify domain behavior**

Run:

```powershell
uv run pytest tests/domain/test_live_market.py tests/domain/test_market_data.py -v
uv run mypy packages/domain/src tests/domain
```

Expected: all realtime and existing market-data tests pass.

- [ ] **Step 5: Commit the contracts**

```powershell
git add packages/domain/src/astraquant_domain tests/domain/test_live_market.py
git commit -m "feat(domain): 定义实时行情事件契约"
```

## Task 2: Add provider capability, health and deterministic simulation

**Files:**

- Create: `packages/data/src/astraquant_data/live_providers.py`
- Create: `packages/data/src/astraquant_data/adapters/simulated.py`
- Modify: `packages/data/src/astraquant_data/adapters/__init__.py`
- Create: `tests/data/test_live_providers.py`
- Create: `tests/data/test_simulated_provider.py`

- [ ] **Step 1: Write failing provider-contract tests**

Create `tests/data/test_live_providers.py`:

```python
from datetime import UTC, datetime

import pytest

from astraquant_data.live_providers import (
    ConnectionState,
    MarketDataCapability,
    ProviderHealth,
)


def test_provider_health_exposes_capabilities_and_last_event() -> None:
    now = datetime(2026, 7, 28, 1, 30, tzinfo=UTC)
    health = ProviderHealth(
        provider_id="simulated",
        display_name="确定性模拟行情",
        state=ConnectionState.STREAMING,
        capabilities=frozenset({MarketDataCapability.FULL_MARKET_STREAM}),
        connected_at=now,
        last_event_at=now,
        last_error=None,
        reconnect_count=0,
        dropped_event_count=0,
        parse_error_count=0,
        is_simulated=True,
    )
    assert health.state is ConnectionState.STREAMING
    assert health.is_simulated is True


def test_provider_health_rejects_negative_counters() -> None:
    with pytest.raises(ValueError, match="counters"):
        ProviderHealth.disconnected("qmt", "QMT", reconnect_count=-1)
```

Create `tests/data/test_simulated_provider.py`:

```python
import asyncio

from astraquant_data.adapters.simulated import SimulatedMarketDataProvider
from astraquant_data.live_providers import ConnectionState


def test_simulated_provider_emits_a_deterministic_marked_stream() -> None:
    async def scenario() -> None:
        provider = SimulatedMarketDataProvider(interval_seconds=0)
        await provider.connect()
        stream = provider.stream()
        first = await anext(stream)
        second = await anext(stream)
        await provider.disconnect()

        assert str(first.tick.instrument_id) == "000001.SSE"
        assert str(second.tick.instrument_id) == "399001.SZSE"
        assert first.metadata.source_id == "simulated"
        assert provider.health().state is ConnectionState.DISCONNECTED

    asyncio.run(scenario())
```

- [ ] **Step 2: Verify both tests fail**

Run:

```powershell
uv run pytest tests/data/test_live_providers.py tests/data/test_simulated_provider.py -v
```

Expected: collection fails for missing modules.

- [ ] **Step 3: Implement the provider protocol**

Create `packages/data/src/astraquant_data/live_providers.py`:

```python
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from astraquant_domain import LiveTick


class MarketDataCapability(StrEnum):
    FULL_MARKET_SNAPSHOT = "full_market_snapshot"
    FULL_MARKET_STREAM = "full_market_stream"
    INSTRUMENT_STREAM = "instrument_stream"
    MARKET_DEPTH = "market_depth"
    BAR_HISTORY = "bar_history"
    REFERENCE_DATA = "reference_data"


class ConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    STREAMING = "STREAMING"
    STALE = "STALE"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider_id: str
    display_name: str
    state: ConnectionState
    capabilities: frozenset[MarketDataCapability]
    connected_at: datetime | None
    last_event_at: datetime | None
    last_error: str | None
    reconnect_count: int
    dropped_event_count: int
    parse_error_count: int
    is_simulated: bool

    def __post_init__(self) -> None:
        counters = (
            self.reconnect_count,
            self.dropped_event_count,
            self.parse_error_count,
        )
        if any(value < 0 for value in counters):
            raise ValueError("provider counters must be non-negative")

    @classmethod
    def disconnected(
        cls,
        provider_id: str,
        display_name: str,
        *,
        reconnect_count: int = 0,
        is_simulated: bool = False,
    ) -> "ProviderHealth":
        return cls(
            provider_id=provider_id,
            display_name=display_name,
            state=ConnectionState.DISCONNECTED,
            capabilities=frozenset(),
            connected_at=None,
            last_event_at=None,
            last_error=None,
            reconnect_count=reconnect_count,
            dropped_event_count=0,
            parse_error_count=0,
            is_simulated=is_simulated,
        )


class LiveMarketDataProvider(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    def stream(self) -> AsyncIterator[LiveTick]: ...
    def health(self) -> ProviderHealth: ...
```

- [ ] **Step 4: Implement the deterministic simulated stream**

Create `packages/data/src/astraquant_data/adapters/simulated.py` with two fixed index-like
instruments, prices derived only from sequence number, and `is_simulated=True`:

```python
import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal

from astraquant_data.live_providers import (
    ConnectionState,
    MarketDataCapability,
    ProviderHealth,
)
from astraquant_domain import (
    InstrumentId,
    LiveTick,
    MarketEventMetadata,
    MarketEventQuality,
    Tick,
)


class SimulatedMarketDataProvider:
    def __init__(self, interval_seconds: float = 1.0) -> None:
        self._interval_seconds = interval_seconds
        self._connected = False
        self._sequence = 0
        self._connected_at: datetime | None = None
        self._last_event_at: datetime | None = None

    async def connect(self) -> None:
        self._connected = True
        self._connected_at = datetime.now(UTC)

    async def disconnect(self) -> None:
        self._connected = False

    async def stream(self) -> AsyncIterator[LiveTick]:
        instruments = ("000001.SSE", "399001.SZSE")
        while self._connected:
            now = datetime.now(UTC)
            instrument = instruments[self._sequence % len(instruments)]
            price = Decimal("3000") + Decimal(self._sequence) / Decimal("10")
            yield LiveTick(
                tick=Tick(
                    instrument_id=InstrumentId.parse(instrument),
                    event_time=now,
                    available_time=now,
                    last_price=price,
                    volume=Decimal(self._sequence * 100),
                    turnover=None,
                    open_interest=None,
                ),
                trading_date=now.date(),
                metadata=MarketEventMetadata(
                    source_id="simulated",
                    source_session_id="simulated-session",
                    received_time=now,
                    sequence=self._sequence,
                    quality=frozenset({MarketEventQuality.NORMAL}),
                ),
                trading_status="SIMULATED",
            )
            self._last_event_at = now
            self._sequence += 1
            await asyncio.sleep(self._interval_seconds)

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id="simulated",
            display_name="确定性模拟行情",
            state=(ConnectionState.STREAMING if self._connected else ConnectionState.DISCONNECTED),
            capabilities=frozenset(
                {
                    MarketDataCapability.FULL_MARKET_STREAM,
                    MarketDataCapability.INSTRUMENT_STREAM,
                }
            ),
            connected_at=self._connected_at,
            last_event_at=self._last_event_at,
            last_error=None,
            reconnect_count=0,
            dropped_event_count=0,
            parse_error_count=0,
            is_simulated=True,
        )
```

Export `SimulatedMarketDataProvider` from `adapters.__init__`.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
uv run pytest tests/data/test_live_providers.py tests/data/test_simulated_provider.py -v
uv run mypy packages/data/src tests/data
uv run ruff check packages/data tests/data
```

Expected: all provider tests and static checks pass.

```powershell
git add packages/data/src/astraquant_data tests/data
git commit -m "feat(data): 增加实时行情 Provider 契约"
```

## Task 3: Implement the lazy read-only QMT adapter

**Files:**

- Create: `packages/data/src/astraquant_data/adapters/qmt.py`
- Modify: `packages/data/src/astraquant_data/adapters/__init__.py`
- Create: `tests/data/test_qmt_adapter.py`

- [ ] **Step 1: Write failing payload and lifecycle tests**

Create `tests/data/test_qmt_adapter.py` with an injected fake client:

```python
import asyncio
from collections.abc import Callable
from typing import Any

from astraquant_data.adapters.qmt import QmtMarketDataProvider, QmtSettings


class FakeXtData:
    def __init__(self) -> None:
        self.callback: Callable[[dict[str, dict[str, Any]]], None] | None = None
        self.unsubscribed: list[int] = []

    def connect(self, port: int) -> None:
        assert port == 58610

    def subscribe_whole_quote(
        self,
        markets: list[str],
        callback: Callable[[dict[str, dict[str, Any]]], None],
    ) -> int:
        assert markets == ["SH", "SZ"]
        self.callback = callback
        return 17

    def unsubscribe_quote(self, subscription_id: int) -> None:
        self.unsubscribed.append(subscription_id)


def test_qmt_maps_full_quote_and_unsubscribes_without_trade_api() -> None:
    async def scenario() -> None:
        client = FakeXtData()
        provider = QmtMarketDataProvider(QmtSettings(port=58610), client=client)
        await provider.connect()
        stream = provider.stream()
        assert client.callback is not None
        client.callback(
            {
                "600000.SH": {
                    "time": 1785202200000,
                    "lastPrice": 12.34,
                    "volume": 1200,
                    "amount": 14808,
                    "bidPrice": [12.33],
                    "bidVol": [300],
                    "askPrice": [12.35],
                    "askVol": [200],
                    "upStopPrice": 13.57,
                    "downStopPrice": 11.11,
                }
            }
        )
        tick = await asyncio.wait_for(anext(stream), timeout=1)
        await provider.disconnect()

        assert str(tick.tick.instrument_id) == "600000.SSE"
        assert str(tick.tick.last_price) == "12.34"
        assert client.unsubscribed == [17]

    asyncio.run(scenario())
```

Add tests that `000001.SZ` maps to `000001.SZSE`, negative subscription IDs become
`ConnectionState.ERROR`, and malformed payloads increment `parse_error_count` without terminating
the callback thread.

- [ ] **Step 2: Verify the adapter is missing**

Run:

```powershell
uv run pytest tests/data/test_qmt_adapter.py -v
```

Expected: collection fails for missing `astraquant_data.adapters.qmt`.

- [ ] **Step 3: Implement settings, lazy import and symbol mapping**

The new module must define:

```python
@dataclass(frozen=True, slots=True)
class QmtSettings:
    port: int = 58610
    module_path: Path | None = None
    markets: tuple[str, ...] = ("SH", "SZ")


def load_xtdata(settings: QmtSettings) -> object:
    if settings.module_path is not None:
        resolved = settings.module_path.resolve(strict=True)
        if not resolved.is_dir():
            raise QmtUnavailable("ASTRAQUANT_XTQUANT_PATH must be a directory")
        sys.path.insert(0, str(resolved))
    try:
        return importlib.import_module("xtquant.xtdata")
    except ImportError as error:
        raise QmtUnavailable("未找到 xtquant；请在设置中配置本机 QMT 的 Python 库目录") from error


def qmt_instrument(value: str) -> InstrumentId:
    symbol, separator, venue = value.rpartition(".")
    mapped = {"SH": "SSE", "SZ": "SZSE"}.get(venue)
    if not separator or mapped is None:
        raise ValueError(f"unsupported QMT instrument: {value}")
    return InstrumentId.parse(f"{symbol}.{mapped}")
```

`QmtUnavailable` is a dedicated exception. The module must not import anything from a QMT trade
namespace.

- [ ] **Step 4: Implement the callback-to-async bridge**

`QmtMarketDataProvider.connect()` captures the running event loop, calls only
`xtdata.connect(port=...)` and `subscribe_whole_quote`, and stores the subscription ID. The callback
maps every symbol payload through a pure `_decode_tick()` function and uses
`loop.call_soon_threadsafe(self._enqueue, tick)`. `_enqueue()` calls `queue.put_nowait(tick)` and
catches `asyncio.QueueFull` to increment `dropped_event_count`. The queue has `maxsize=20_000`; it
never blocks the QMT callback.

`disconnect()` calls only `unsubscribe_quote(subscription_id)`, marks the provider disconnected,
and inserts a private sentinel so an awaiting stream exits. `health()` returns QMT capabilities:

```python
frozenset(
    {
        MarketDataCapability.FULL_MARKET_SNAPSHOT,
        MarketDataCapability.FULL_MARKET_STREAM,
        MarketDataCapability.INSTRUMENT_STREAM,
        MarketDataCapability.MARKET_DEPTH,
        MarketDataCapability.BAR_HISTORY,
        MarketDataCapability.REFERENCE_DATA,
    }
)
```

Decode `time` as Unix milliseconds in UTC, use `datetime.now(UTC)` for `received_time`, convert all
numeric values through `Decimal(str(value))`, drop zero-price depth levels, and set
`source_id="qmt"`. Never synthesize missing prices.

- [ ] **Step 5: Verify adapter isolation and commit**

Run:

```powershell
uv run pytest tests/data/test_qmt_adapter.py -v
uv run python -c "import astraquant_data.adapters.qmt; print('lazy import ok')"
uv run mypy packages/data/src tests/data
uv run ruff check packages/data tests/data
```

Expected: tests pass without QMT installed; importing the adapter does not import `xtquant`.

```powershell
git add packages/data/src/astraquant_data/adapters tests/data/test_qmt_adapter.py
git commit -m "feat(data): 接入 QMT 只读全市场行情"
```

## Task 4: Build the single-provider MarketDataService

**Files:**

- Create: `packages/api/src/astraquant_api/market_service.py`
- Create: `tests/api/test_market_service.py`

- [ ] **Step 1: Write failing lifecycle, latest-value and stale tests**

Create tests around `SimulatedMarketDataProvider(interval_seconds=0)`:

```python
import asyncio

from astraquant_api.market_service import MarketDataService
from astraquant_data.adapters.simulated import SimulatedMarketDataProvider


def test_service_starts_collects_latest_values_and_stops() -> None:
    async def scenario() -> None:
        service = MarketDataService(
            SimulatedMarketDataProvider(interval_seconds=0),
            stale_after_seconds=5,
            latest_limit=10,
        )
        await service.start()
        await service.wait_for_events(2, timeout_seconds=1)
        ticks = service.latest_ticks(limit=10)
        assert {str(item.tick.instrument_id) for item in ticks} == {
            "000001.SSE",
            "399001.SZSE",
        }
        await service.stop()
        assert service.snapshot().state == "DISCONNECTED"

    asyncio.run(scenario())
```

Add tests that calling `start()` twice is idempotent, `stop()` twice is idempotent, only the latest
Tick per instrument is retained, and an unexpected provider exception produces `ERROR` without
escaping the consumer task.

- [ ] **Step 2: Verify service tests fail**

Run:

```powershell
uv run pytest tests/api/test_market_service.py -v
```

Expected: collection fails for missing service.

- [ ] **Step 3: Implement bounded lifecycle state**

`MarketDataService` must own:

```python
self._provider: LiveMarketDataProvider
self._task: asyncio.Task[None] | None
self._lock: asyncio.Lock
self._latest: OrderedDict[str, LiveTick]
self._event_count: int
self._event_signal: asyncio.Condition
self._service_error: str | None
```

`start()` connects then creates exactly one `_consume()` task. `_consume()` iterates
`provider.stream()`, replaces the instrument's latest value, moves it to the end, and evicts the
oldest key when `latest_limit` is exceeded. `stop()` disconnects, cancels and awaits the task while
suppressing only `asyncio.CancelledError`.

Expose:

```python
async def start(self) -> None: ...
async def stop(self) -> None: ...
async def wait_for_events(self, count: int, timeout_seconds: float) -> None: ...
def snapshot(self) -> ProviderHealth: ...
def latest_ticks(self, limit: int) -> list[LiveTick]: ...
```

`snapshot()` converts a streaming provider to `STALE` when its last event is older than
`stale_after_seconds`; it never rewrites provider counters.

- [ ] **Step 4: Verify and commit**

Run:

```powershell
uv run pytest tests/api/test_market_service.py -v
uv run mypy packages/api/src tests/api
uv run ruff check packages/api tests/api
```

Expected: lifecycle and stale behavior pass without leaked tasks.

```powershell
git add packages/api/src/astraquant_api/market_service.py tests/api/test_market_service.py
git commit -m "feat(api): 管理本地实时行情生命周期"
```

## Task 5: Expose authenticated market connection endpoints

**Files:**

- Create: `packages/api/src/astraquant_api/market_config.py`
- Create: `packages/api/src/astraquant_api/market_schemas.py`
- Create: `packages/api/src/astraquant_api/market_routes.py`
- Create: `packages/data/src/astraquant_data/adapters/disabled.py`
- Modify: `packages/data/src/astraquant_data/adapters/__init__.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Modify: `packages/api/src/astraquant_api/cli.py`
- Create: `tests/api/test_market_config.py`
- Create: `tests/api/test_market_routes.py`

- [ ] **Step 1: Write failing configuration tests**

Test exact environment semantics:

```python
def test_market_config_defaults_to_explicit_simulation(monkeypatch) -> None:
    monkeypatch.delenv("ASTRAQUANT_MARKET_PROVIDER", raising=False)
    config = MarketRuntimeConfig.from_environment()
    assert config.provider == "simulated"
    assert config.auto_start is True


def test_qmt_configuration_requires_valid_port(monkeypatch) -> None:
    monkeypatch.setenv("ASTRAQUANT_MARKET_PROVIDER", "qmt")
    monkeypatch.setenv("ASTRAQUANT_QMT_PORT", "70000")
    with pytest.raises(ValueError, match="QMT port"):
        MarketRuntimeConfig.from_environment()
```

Accepted providers are exactly `disabled`, `simulated`, and `qmt`. Parse
`ASTRAQUANT_MARKET_AUTO_START` as `0` or `1`; reject other strings. Resolve an optional absolute
`ASTRAQUANT_XTQUANT_PATH`.

- [ ] **Step 2: Implement and test the explicit disabled provider**

Create `packages/data/src/astraquant_data/adapters/disabled.py`:

```python
from collections.abc import AsyncIterator

from astraquant_data.live_providers import ProviderHealth
from astraquant_domain import LiveTick


class ProviderUnavailable(RuntimeError):
    pass


class DisabledMarketDataProvider:
    async def connect(self) -> None:
        raise ProviderUnavailable("实时行情已禁用")

    async def disconnect(self) -> None:
        return None

    async def stream(self) -> AsyncIterator[LiveTick]:
        if False:
            yield

    def health(self) -> ProviderHealth:
        return ProviderHealth.disconnected("disabled", "实时行情已禁用")
```

Export both symbols from `adapters.__init__`. Add a unit test asserting `connect()` raises
`ProviderUnavailable`, health is `DISCONNECTED`, and `is_simulated` is false.

- [ ] **Step 3: Write failing authenticated route tests**

Build `AppState` with a simulated `MarketDataService` and assert:

```python
with TestClient(create_app(state)) as client:
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    started = client.post("/v1/market/connection/start")
    health = client.get("/v1/market/connection")
    ticks = client.get("/v1/market/ticks", params={"limit": 10})
    stopped = client.post("/v1/market/connection/stop")

assert started.status_code == 202
assert health.json()["provider_id"] == "simulated"
assert health.json()["is_simulated"] is True
assert ticks.status_code == 200
assert stopped.status_code == 202
```

Anonymous access to all `/v1/market/*` endpoints must return `401`; `limit` accepts `1..500`.

- [ ] **Step 4: Implement strict response models and router**

`MarketConnectionResponse` contains:

```python
provider_id: str
display_name: str
state: Literal["DISCONNECTED", "CONNECTING", "STREAMING", "STALE", "ERROR"]
capabilities: list[str]
connected_at: str | None
last_event_at: str | None
last_error: str | None
reconnect_count: int
dropped_event_count: int
parse_error_count: int
is_simulated: bool
```

`LiveTickResponse` contains source ID, instrument ID, event/received times, last price, cumulative
volume, optional turnover, best bid/ask, quality and trading status. Serialize decimals as strings.

Create an `APIRouter(prefix="/v1/market", dependencies=[authenticated])` with:

```text
GET  /connection
POST /connection/start
POST /connection/stop
GET  /ticks?limit=100
```

Start/stop responses use status `202` and return the post-action connection snapshot.
Map `ProviderUnavailable` to a stable `503` response with code `market_provider_unavailable`; do
not leak import tracebacks or local installation paths.

- [ ] **Step 5: Wire configuration, provider factory and app lifespan**

Add optional fields after the existing defaulted `AppState` fields so older focused tests remain
valid:

```python
market_service: MarketDataService | None = None
market_auto_start: bool = False
```

Production `cli.py` always supplies a service. `create_app()` includes the market router only when
`market_service` is not `None` and uses an `asynccontextmanager` lifespan:

```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    if state.market_service is not None and state.market_auto_start:
        await state.market_service.start()
    try:
        yield
    finally:
        if state.market_service is not None:
            await state.market_service.stop()
```

Include `build_market_router(state, authenticated)`.

In `cli.py`, construct exactly one provider:

```python
def build_market_provider(config: MarketRuntimeConfig) -> LiveMarketDataProvider:
    if config.provider == "qmt":
        return QmtMarketDataProvider(
            QmtSettings(port=config.qmt_port, module_path=config.xtquant_path)
        )
    if config.provider == "simulated":
        return SimulatedMarketDataProvider()
    return DisabledMarketDataProvider()
```

Ensure shutdown calls `await market_service.stop()` through FastAPI lifespan before disposing the
database. No endpoint accepts account, order, position or trade fields.

- [ ] **Step 6: Run route regression and commit**

Run:

```powershell
uv run pytest tests/api/test_market_config.py tests/api/test_market_routes.py tests/api/test_app.py tests/api/test_data_routes.py -v
uv run mypy packages/api/src tests/api
uv run ruff check packages/api tests/api
```

Expected: market endpoints are authenticated; existing data and runtime endpoints remain passing.

```powershell
git add packages/api/src/astraquant_api packages/data/src/astraquant_data/adapters tests/api tests/data
git commit -m "feat(api): 发布实时行情连接接口"
```

## Task 6: Add the desktop data-source connection panel

**Files:**

- Create: `apps/desktop/src/api/market-contracts.ts`
- Modify: `apps/desktop/src/api/client.ts`
- Modify: `apps/desktop/src/api/queries.ts`
- Create: `apps/desktop/src/components/MarketConnectionPanel.tsx`
- Create: `apps/desktop/src/components/MarketConnectionPanel.test.tsx`
- Modify: `apps/desktop/src/pages/DataPage.tsx`
- Modify: `apps/desktop/src/App.tsx`
- Modify: `apps/desktop/src/styles/app.css`

- [ ] **Step 1: Write the failing connection-panel test**

Create `MarketConnectionPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MarketConnectionPanel } from "./MarketConnectionPanel";

const connection = {
  provider_id: "simulated",
  display_name: "确定性模拟行情",
  state: "STREAMING" as const,
  capabilities: ["full_market_stream"],
  connected_at: "2026-07-28T01:30:00Z",
  last_event_at: "2026-07-28T01:30:03Z",
  last_error: null,
  reconnect_count: 0,
  dropped_event_count: 0,
  parse_error_count: 0,
  is_simulated: true,
};

test("makes simulation and read-only boundaries impossible to miss", async () => {
  const user = userEvent.setup();
  const onStop = vi.fn();
  render(
    <MarketConnectionPanel
      connection={connection}
      ticks={[]}
      pending={false}
      onStart={vi.fn()}
      onStop={onStop}
    />,
  );

  expect(screen.getByText("模拟行情")).toBeVisible();
  expect(screen.getByText("只读连接 · 不含下单能力")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "断开行情" }));
  expect(onStop).toHaveBeenCalledOnce();
});
```

Add a second test for `ERROR` showing `last_error` and a “重新连接” button, and a third test for
`STALE` showing “行情已过期，暂停新信号”.

- [ ] **Step 2: Verify the component is missing**

Run:

```powershell
pnpm --dir apps/desktop test -- MarketConnectionPanel.test.tsx
```

Expected: module resolution fails.

- [ ] **Step 3: Add frontend contracts, client calls and queries**

Define exact TypeScript interfaces matching the Pydantic models. Add:

```ts
getMarketConnection(): Promise<MarketConnection>
startMarketConnection(): Promise<MarketConnection>
stopMarketConnection(): Promise<MarketConnection>
listLiveTicks(limit?: number): Promise<LiveTickPreview[]>
```

Add query keys:

```ts
marketConnection: ["market", "connection"] as const,
marketTicks: ["market", "ticks"] as const,
```

Poll connection every `1_000` ms and ticks every `1_000` ms only while state is `STREAMING` or
`STALE`. Start/stop mutations update `marketConnection` immediately and invalidate market ticks and
activity.

- [ ] **Step 4: Implement the panel and promote it above imports**

The panel must render:

- provider display name and an explicit `模拟行情` badge when `is_simulated`;
- connection state text and last event time;
- “只读连接 · 不含下单能力” at all times;
- received instrument count and up to six latest prices;
- reconnect, dropped and parse counters;
- start or stop button, disabled while a mutation is pending;
- error or stale explanation using text and icon, not color alone.

Place `MarketConnectionPanel` before `data-workbench` in `DataPage`. Rename the page eyebrow to
`DATA & CONNECTIONS`; keep the Phase 2 import form under a collapsible “历史与开发工具” section.
Wire queries and mutations in `App.tsx`; do not add WebSocket or SSE in Phase 3A.

- [ ] **Step 5: Style, verify and commit**

Use existing tokens only. Add responsive classes `.market-connection`,
`.market-connection__status`, `.market-connection__metrics`, `.market-tick-strip`, and
`.market-provider-badge`; safety states must use existing safety tokens.

Run:

```powershell
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

Expected: all component/page tests, TypeScript and production build pass.

```powershell
git add apps/desktop/src
git commit -m "feat(desktop): 展示实时行情连接状态"
```

## Task 7: Prove the vertical slice and document real-session acceptance

**Files:**

- Create: `tests/integration/test_realtime_market_round_trip.py`
- Create: `tools/qmt_probe.py`
- Create: `docs/operations/realtime-market-data.md`
- Create: `docs/research/qmt-feasibility-report.md`
- Modify: `README.md`
- Modify: `docs/roadmap/product-roadmap.md`
- Modify: `tools/repository_policy.py`
- Modify: `tests/repository/test_repository_policy.py`

- [ ] **Step 1: Write the simulated round-trip acceptance test**

Start the real FastAPI app state with `SimulatedMarketDataProvider(interval_seconds=0.01)` and
assert:

```python
with TestClient(create_app(state)) as client:
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    assert client.post("/v1/market/connection/start").status_code == 202
    deadline = time.monotonic() + 2
    ticks: list[dict[str, object]] = []
    while time.monotonic() < deadline and len(ticks) < 2:
        ticks = client.get("/v1/market/ticks", params={"limit": 10}).json()
    health = client.get("/v1/market/connection").json()

assert health["state"] == "STREAMING"
assert health["is_simulated"] is True
assert {item["instrument_id"] for item in ticks} == {"000001.SSE", "399001.SZSE"}
assert all(item["source_id"] == "simulated" for item in ticks)
```

Also assert no response contains keys matching
`account`, `order`, `position`, `trade`, `password`, or `credential`.

- [ ] **Step 2: Create a bounded QMT probe**

`tools/qmt_probe.py` accepts `--seconds` between 5 and 300 and an optional `--output`. It builds
`QmtMarketDataProvider` from `ASTRAQUANT_QMT_PORT` and `ASTRAQUANT_XTQUANT_PATH`, receives events
until the deadline, and writes only aggregate JSON:

```json
{
  "provider_id": "qmt",
  "started_at": "ISO-8601",
  "ended_at": "ISO-8601",
  "event_count": 0,
  "instrument_count": 0,
  "first_event_at": null,
  "last_event_at": null,
  "latency_ms": {
    "minimum": null,
    "median": null,
    "p95": null,
    "maximum": null
  },
  "reconnect_count": 0,
  "dropped_event_count": 0,
  "parse_error_count": 0
}
```

It must not write symbols, prices, Tick payloads or credentials. Exit codes are `0` for at least one
valid event, `2` for configuration/adapter unavailable, and `3` for a completed run with zero
events.

- [ ] **Step 3: Harden repository policy for probe output**

Reject `qmt-probe*.json`, `market-probe*.json`, and any file under
`.astraquant/market/`. Add exact policy tests demonstrating those paths are forbidden while
`docs/research/qmt-feasibility-report.md` remains allowed.

- [ ] **Step 4: Write operations and feasibility documentation**

`docs/operations/realtime-market-data.md` must include:

```powershell
# Development simulation, enabled by default
.\start.ps1

# Real QMT read-only quote mode
$env:ASTRAQUANT_MARKET_PROVIDER = "qmt"
$env:ASTRAQUANT_QMT_PORT = "58610"
$env:ASTRAQUANT_XTQUANT_PATH = "D:\Path\To\QMT\python"
.\start.ps1

# Aggregate-only market-session probe
uv run python -m tools.qmt_probe --seconds 60
```

Explain that the adapter never imports trade modules, never accepts order/account fields, does not
redistribute data, and requires the user's own QMT installation and quote rights.

`docs/research/qmt-feasibility-report.md` contains a checked-in empty measurement table with fixed
rows: test date/session, QMT version, quote level, event count, instrument coverage, update cadence,
median/p95 latency, disconnect/reconnect observation, parse/drop counts, and decision. Use
`NOT_RUN` as the explicit initial state rather than an ambiguous blank.

Update README to describe Phase 3A as `IN_PROGRESS`, simulation as development-only, and QMT
real-session acceptance as not yet proven. Update the roadmap only after simulated integration
passes; do not mark Phase 3A complete until the feasibility report contains a successful real
market-session run.

- [ ] **Step 5: Run the complete local quality gate**

Run:

```powershell
uv run ruff format --check packages tools tests
uv run ruff check packages tools tests
uv run mypy
uv run pytest
uv run python -m tools.repository_policy
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Expected: every command passes. The QMT probe is intentionally not part of CI because CI has no
user QMT installation or market-data entitlement.

- [ ] **Step 6: Commit the acceptance slice**

```powershell
git add tests/integration/test_realtime_market_round_trip.py tools/qmt_probe.py docs/operations/realtime-market-data.md docs/research/qmt-feasibility-report.md README.md docs/roadmap/product-roadmap.md tools/repository_policy.py tests/repository/test_repository_policy.py
git commit -m "docs(market): 验收实时行情纵向切片"
```

## Task 8: Publish Phase 3A safely

**Files:**

- Modify: `docs/superpowers/plans/2026-07-28-phase-3a-realtime-market-foundation.md`

- [ ] **Step 1: Record execution evidence**

After Tasks 0–7, mark completed checkboxes and append exact command results, commit SHAs, and the
QMT feasibility state (`NOT_RUN`, `FAILED`, or `PASSED`) under an `Execution Record` section. Do
not claim QMT acceptance when only simulation ran.

- [ ] **Step 2: Verify the final tree**

Run:

```powershell
git status --short
git log --oneline --decorate -12
git diff origin/feature/phase-1-desktop-platform...HEAD --check
```

Expected: only the plan execution-record edit is uncommitted; diff check is silent.

- [ ] **Step 3: Commit the execution record**

```powershell
git add docs/superpowers/plans/2026-07-28-phase-3a-realtime-market-foundation.md
git commit -m "docs(market): 记录 Phase 3A 实施结果"
```

- [ ] **Step 4: Push the existing feature branch**

```powershell
git push origin feature/phase-1-desktop-platform
gh pr view 4 --json url,headRefOid,statusCheckRollup
```

Expected: PR #4 head SHA matches local `HEAD`. Keep the PR as Draft, wait for Python
Windows/Ubuntu, Frontend and Desktop Rust checks, and fix failures on the same branch. Do not merge
`main` automatically.

## Execution checkpoints

- After Task 0: GitHub Actions baseline must be green before adding realtime behavior.
- After Task 3: demonstrate QMT adapter tests passing without QMT installed and confirm no trade
  module import exists.
- After Task 5: inspect authenticated API JSON for explicit `is_simulated` and source health.
- After Task 6: run the desktop and confirm simulation cannot be mistaken for real market data.
- After Task 7: if a QMT account is available during market hours, run the aggregate-only probe and
  fill the feasibility report; otherwise leave it `NOT_RUN` and proceed without false claims.

## Later plans

- Phase 3B: Tick recording, minute aggregation, gaps and deterministic replay.
- Phase 3C: full-market scanner, market overview, watchlist and instrument intraday workspace.
- Phase 4A: strategy registry, walk-forward validation, backtest and model publication.
- Phase 4B: Evidence Store, constrained intelligence Agent and versioned Skills.
- Phase 5: online features, `SignalFrame`, deterministic advisory risk and Paper simulation.

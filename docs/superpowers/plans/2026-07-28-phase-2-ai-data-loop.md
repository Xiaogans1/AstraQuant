# Phase 2 AI-Ready Data Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, versioned A-share and domestic-futures market-data loop that imports sample data, validates and stores immutable Parquet snapshots, supports point-in-time DuckDB queries and `FeatureFrame` snapshots, and exposes the results in the desktop Data Center.

**Architecture:** Stable market-time contracts live in `astraquant-domain`; storage, providers, quality checks and feature snapshots live in a new `astraquant-data` package; the local API owns the SQLite catalog and worker orchestration; the React desktop consumes read-only catalog endpoints. Batch and future streaming providers share `Bar`/`Tick` semantics but not transport code, and no provider interface contains account or order operations.

**Tech Stack:** Python 3.12, dataclasses, `Decimal`, PyArrow 25, DuckDB 1.5, AKShare 1.18.x behind a lazy optional adapter, SQLAlchemy/Alembic, FastAPI/Pydantic, React 19, TanStack Query, Vitest, pytest, Ruff, mypy.

---

## Scope and delivery slices

This plan intentionally implements Phase 2 as three independently testable slices:

1. **P2A — contracts and immutable local storage:** Tasks 1–5.
2. **P2B — point-in-time features and import orchestration:** Tasks 6–8.
3. **P2C — desktop Data Center and end-to-end acceptance:** Tasks 9–10.

Real brokerage accounts, order APIs, automatic trading, live low-latency feeds, model
training and signal generation are outside this plan. The streaming provider is a contract
plus deterministic replay fixture; production realtime feeds belong to Phase 4.

## File map

| Path | Responsibility |
| --- | --- |
| `packages/domain/src/astraquant_domain/market_data.py` | Dependency-free `Bar`, `Tick`, frequency and adjustment contracts |
| `packages/domain/src/astraquant_domain/features.py` | Dependency-free `FeatureRow` and `FeatureFrame` contracts |
| `packages/data/src/astraquant_data/providers.py` | Read-only batch/stream provider protocols and requests |
| `packages/data/src/astraquant_data/adapters/akshare.py` | Lazy AKShare A-share and futures daily-bar normalization |
| `packages/data/src/astraquant_data/adapters/replay.py` | Deterministic async stream replay for contract tests |
| `packages/data/src/astraquant_data/calendars.py` | Versioned CSV trading-session calendars for A-shares and futures |
| `packages/data/src/astraquant_data/arrow_schema.py` | Canonical Arrow schemas and domain/Table conversion |
| `packages/data/src/astraquant_data/quality.py` | Data quality issues, severity and deterministic reports |
| `packages/data/src/astraquant_data/manifests.py` | Canonical JSON snapshot manifests and content hashes |
| `packages/data/src/astraquant_data/parquet_store.py` | Staged immutable Parquet publication and snapshot loading |
| `packages/data/src/astraquant_data/query.py` | Parameterized DuckDB range and as-of queries |
| `packages/data/src/astraquant_data/features.py` | Rebuildable feature snapshot writer and as-of feature reader |
| `packages/api/migrations/versions/0002_data_catalog.py` | Dataset, snapshot, file and quality-report catalog tables |
| `packages/api/src/astraquant_api/data_repository.py` | SQLite data-catalog repository |
| `packages/api/src/astraquant_api/data_worker.py` | Cancellable import/validate/publish worker |
| `packages/api/src/astraquant_api/data_schemas.py` | Strict API request/response models |
| `packages/api/src/astraquant_api/data_routes.py` | `/v1/data/*` authenticated endpoints |
| `apps/desktop/src/pages/DataPage.tsx` | Dataset list, import form, quality and snapshot details |
| `apps/desktop/src/api/data-contracts.ts` | Data Center API types |
| `tests/fixtures/market_data/*.csv` | Tiny, synthetic, redistributable A-share/futures/calendar fixtures |

## Non-negotiable invariants

- Every timestamp is timezone-aware and persisted in UTC.
- `event_time <= available_time <= source_fetched_at`; estimated availability is explicitly flagged.
- Snapshot files are immutable and addressed by a SHA-256 manifest hash.
- Publication is staged; a failed validation never makes a partial snapshot visible.
- Git contains only tiny synthetic fixtures, never downloaded market data or local catalog files.
- Provider protocols expose only metadata, history and subscription/replay; no account, order,
  cancel, position or balance methods are permitted.
- AKShare is a convenience source, not an authoritative licensed realtime feed. Provider name,
  upstream interface, fetch time, adjustment and availability policy are recorded in every snapshot.

### Task 0: Remove the stale live-environment domain flag

**Files:**
- Modify: `packages/domain/src/astraquant_domain/orders.py`
- Modify: `tests/domain/test_orders.py`
- Modify: `docs/roadmap/product-roadmap.md`

- [ ] **Step 1: Write the permanent-boundary regression test**

```python
# append to tests/domain/test_orders.py
def test_virtual_order_environments_never_include_live_trading() -> None:
    assert {environment.value for environment in Environment} == {"BACKTEST", "PAPER"}
    assert "LIVE" not in Path("packages/domain/src/astraquant_domain/orders.py").read_text(
        encoding="utf-8"
    )
```

Add `from pathlib import Path` to the test module.

- [ ] **Step 2: Run the test and prove the stale flag is present**

Run:

```powershell
uv run pytest tests/domain/test_orders.py::test_virtual_order_environments_never_include_live_trading -v
```

Expected: FAIL because the current `Environment` enum contains `LIVE`.

- [ ] **Step 3: Remove only the unsupported environment**

Change the module docstring to:

```python
"""Virtual order values used only by deterministic backtest and Paper simulation."""
```

Change the enum to:

```python
class Environment(StrEnum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
```

Keep the virtual order state machine because deterministic backtest/Paper fills require it.
Do not add broker identifiers, account fields, gateway states or external submission methods.
Update the Phase 0 roadmap delivery text from account/order contracts to signal and Paper
simulation contracts.

- [ ] **Step 4: Verify the domain boundary**

Run:

```powershell
uv run pytest tests/domain/test_orders.py -v
$null = rg -n '"LIVE"|Gateway|broker|account_id|submit_order' packages/domain
if ($LASTEXITCODE -ne 1) { throw "真实交易边界扫描发现禁用标识或扫描失败" }
```

Expected: order tests pass and `rg` returns no matches.

- [ ] **Step 5: Commit**

```powershell
git add packages/domain/src/astraquant_domain/orders.py tests/domain/test_orders.py docs/roadmap/product-roadmap.md
git commit -m "refactor(domain): 限定订单模型仅用于回测与 Paper"
```

### Task 1: Add the isolated data package and pinned storage dependencies

**Files:**
- Create: `packages/data/pyproject.toml`
- Create: `packages/data/src/astraquant_data/__init__.py`
- Create: `tests/data/test_package.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Write the failing package-boundary test**

```python
# tests/data/test_package.py
from importlib.util import find_spec


def test_data_package_and_native_engines_are_installed() -> None:
    assert find_spec("astraquant_data") is not None
    assert find_spec("duckdb") is not None
    assert find_spec("pyarrow") is not None
```

- [ ] **Step 2: Verify the test fails before the package exists**

Run:

```powershell
uv run pytest tests/data/test_package.py -v
```

Expected: FAIL because `astraquant_data` cannot be imported.

- [ ] **Step 3: Create the package and workspace entries**

```toml
# packages/data/pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "astraquant-data"
version = "0.1.0"
description = "Local market-data storage and point-in-time query services for AstraQuant."
requires-python = ">=3.12,<3.13"
dependencies = [
  "astraquant-domain",
  "duckdb>=1.5,<2",
  "pyarrow>=25,<26",
]

[project.optional-dependencies]
akshare = ["akshare>=1.18.64,<1.19"]

[tool.uv.sources]
astraquant-domain = { workspace = true }

[tool.hatch.build.targets.wheel]
packages = ["src/astraquant_data"]
```

```python
# packages/data/src/astraquant_data/__init__.py
"""Local, immutable and point-in-time-safe data services."""

__version__ = "0.1.0"
```

Modify the root `pyproject.toml` so:

```toml
dependencies = ["astraquant-api", "astraquant-data[akshare]", "astraquant-domain"]

[tool.uv.sources]
astraquant-domain = { workspace = true }
astraquant-data = { workspace = true }
astraquant-api = { workspace = true }

[tool.uv.workspace]
members = ["packages/domain", "packages/data", "packages/api"]
```

Add `packages/data/src` and `astraquant_data` to the existing Ruff/isort configuration,
and add `packages/data/src` to mypy `files`.

- [ ] **Step 4: Lock and verify**

Run:

```powershell
uv lock
uv sync --all-packages
uv run pytest tests/data/test_package.py -v
uv run ruff check packages/data tests/data/test_package.py
```

Expected: one passing test and no Ruff findings.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml uv.lock packages/data tests/data/test_package.py
git commit -m "build(data): 增加本地数据包与列式存储依赖"
```

### Task 2: Define timezone-safe market-data domain contracts

**Files:**
- Create: `packages/domain/src/astraquant_domain/market_data.py`
- Create: `tests/domain/test_market_data.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`

- [ ] **Step 1: Write invariant tests**

```python
# tests/domain/test_market_data.py
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId


def make_bar(**changes: object) -> Bar:
    values: dict[str, object] = {
        "instrument_id": InstrumentId.parse("600000.SSE"),
        "frequency": BarFrequency.DAY,
        "event_time": datetime(2026, 7, 24, 7, 0, tzinfo=UTC),
        "available_time": datetime(2026, 7, 24, 7, 1, tzinfo=UTC),
        "open": Decimal("10.00"),
        "high": Decimal("10.80"),
        "low": Decimal("9.90"),
        "close": Decimal("10.50"),
        "volume": Decimal("120000"),
        "turnover": Decimal("1250000"),
        "open_interest": None,
        "settlement": None,
        "adjustment": Adjustment.NONE,
        "availability_estimated": True,
    }
    values.update(changes)
    return Bar(**values)  # type: ignore[arg-type]


def test_bar_accepts_valid_ohlc_and_point_in_time_order() -> None:
    assert make_bar().close == Decimal("10.50")


@pytest.mark.parametrize(
    ("field", "value"),
    [("high", Decimal("9.99")), ("low", Decimal("10.01"))],
)
def test_bar_rejects_impossible_ohlc(field: str, value: Decimal) -> None:
    with pytest.raises(ValueError, match="OHLC"):
        make_bar(**{field: value})


def test_bar_rejects_information_available_before_market_event() -> None:
    with pytest.raises(ValueError, match="available_time"):
        make_bar(available_time=datetime(2026, 7, 24, 6, 59, tzinfo=UTC))
```

- [ ] **Step 2: Run the focused test and observe the missing contracts**

Run:

```powershell
uv run pytest tests/domain/test_market_data.py -v
```

Expected: collection FAIL because `Adjustment`, `Bar` and `BarFrequency` do not exist.

- [ ] **Step 3: Implement the dependency-free contracts**

```python
# packages/domain/src/astraquant_domain/market_data.py
"""Canonical market-data records shared by batch and streaming providers."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from astraquant_domain.identifiers import InstrumentId


class BarFrequency(StrEnum):
    TICK = "tick"
    MINUTE = "1m"
    DAY = "1d"


class Adjustment(StrEnum):
    NONE = "none"
    FORWARD = "qfq"
    BACKWARD = "hfq"


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Bar:
    instrument_id: InstrumentId
    frequency: BarFrequency
    event_time: datetime
    available_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None
    settlement: Decimal | None
    adjustment: Adjustment
    availability_estimated: bool

    def __post_init__(self) -> None:
        _require_aware("event_time", self.event_time)
        _require_aware("available_time", self.available_time)
        if self.available_time < self.event_time:
            raise ValueError("available_time must not precede event_time")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC values are inconsistent")
        if self.low > self.high:
            raise ValueError("OHLC low must not exceed high")


@dataclass(frozen=True, slots=True)
class Tick:
    instrument_id: InstrumentId
    event_time: datetime
    available_time: datetime
    last_price: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None

    def __post_init__(self) -> None:
        _require_aware("event_time", self.event_time)
        _require_aware("available_time", self.available_time)
        if self.available_time < self.event_time:
            raise ValueError("available_time must not precede event_time")
        if self.last_price <= 0 or self.volume < 0:
            raise ValueError("tick price must be positive and volume non-negative")
```

Export the four new public names from `astraquant_domain.__init__`.

- [ ] **Step 4: Verify domain behavior and static types**

Run:

```powershell
uv run pytest tests/domain/test_market_data.py tests/domain -v
uv run mypy packages/domain/src tests/domain
```

Expected: all domain tests pass and mypy reports success.

- [ ] **Step 5: Commit**

```powershell
git add packages/domain/src/astraquant_domain tests/domain/test_market_data.py
git commit -m "feat(domain): 定义市场数据及时态契约"
```

### Task 3: Add read-only provider contracts and normalized AKShare adapters

**Files:**
- Create: `packages/data/src/astraquant_data/providers.py`
- Create: `packages/data/src/astraquant_data/adapters/__init__.py`
- Create: `packages/data/src/astraquant_data/adapters/akshare.py`
- Create: `packages/data/src/astraquant_data/adapters/replay.py`
- Create: `packages/data/src/astraquant_data/calendars.py`
- Create: `tests/data/test_providers.py`
- Create: `tests/data/test_akshare_adapter.py`
- Create: `tests/data/test_calendars.py`
- Create: `tests/fixtures/market_data/cn_equity_sessions.csv`
- Create: `tests/fixtures/market_data/cn_futures_sessions.csv`

- [ ] **Step 1: Write provider boundary and normalization tests**

```python
# tests/data/test_providers.py
import inspect

from astraquant_data.providers import HistoricalDataProvider, StreamingDataProvider


def test_provider_contracts_have_no_trading_operations() -> None:
    methods = {
        name
        for protocol in (HistoricalDataProvider, StreamingDataProvider)
        for name, value in inspect.getmembers(protocol, inspect.isfunction)
    }
    forbidden = {"order", "submit_order", "cancel_order", "account", "position", "balance"}
    assert methods.isdisjoint(forbidden)
    assert {"provider_id", "fetch_bars"}.issubset(methods)
    assert {"provider_id", "subscribe"}.issubset(methods)
```

```python
# tests/data/test_akshare_adapter.py
from datetime import date

import pandas as pd

from astraquant_data.adapters.akshare import AkShareDailyBarProvider
from astraquant_data.providers import HistoryRequest
from astraquant_domain import Adjustment, BarFrequency, InstrumentId


class FakeAkShare:
    def stock_zh_a_hist(self, **_: object) -> pd.DataFrame:
        return pd.DataFrame(
            [{"日期": "2026-07-24", "开盘": 10, "最高": 11, "最低": 9, "收盘": 10.5,
              "成交量": 100, "成交额": 105000}]
        )


def test_stock_daily_data_is_normalized_with_estimated_availability() -> None:
    provider = AkShareDailyBarProvider(client=FakeAkShare())
    bars = provider.fetch_bars(
        HistoryRequest(
            instrument_id=InstrumentId.parse("600000.SSE"),
            frequency=BarFrequency.DAY,
            start=date(2026, 7, 24),
            end=date(2026, 7, 24),
            adjustment=Adjustment.NONE,
        )
    )
    assert len(bars) == 1
    assert str(bars[0].instrument_id) == "600000.SSE"
    assert bars[0].available_time > bars[0].event_time
    assert bars[0].availability_estimated is True
```

- [ ] **Step 2: Run tests and confirm missing provider modules**

Run:

```powershell
uv run pytest tests/data/test_providers.py tests/data/test_akshare_adapter.py -v
```

Expected: collection FAIL for missing `astraquant_data.providers`.

- [ ] **Step 3: Implement the read-only protocols**

```python
# packages/data/src/astraquant_data/providers.py
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId, Tick


@dataclass(frozen=True, slots=True)
class HistoryRequest:
    instrument_id: InstrumentId
    frequency: BarFrequency
    start: date
    end: date
    adjustment: Adjustment = Adjustment.NONE

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("end must not precede start")


class HistoricalDataProvider(Protocol):
    def provider_id(self) -> str: ...

    def fetch_bars(self, request: HistoryRequest) -> Sequence[Bar]: ...


class StreamingDataProvider(Protocol):
    def provider_id(self) -> str: ...

    def subscribe(self, instruments: Sequence[InstrumentId]) -> AsyncIterator[Tick | Bar]: ...
```

Implement `ReplayStreamingProvider` as an async iterator over a tuple of `Tick | Bar`,
filtering by requested instruments and yielding in `(event_time, available_time)` order.

- [ ] **Step 4: Implement versioned, imported trading calendars**

`CsvTradingCalendar.load(path, expected_venue, source_version)` accepts:

```csv
venue,trading_date,session_open,session_close
SSE,2026-07-24,2026-07-24T01:30:00Z,2026-07-24T07:00:00Z
SHFE,2026-07-24,2026-07-23T13:00:00Z,2026-07-24T07:00:00Z
```

It rejects duplicate `(venue, trading_date)` rows, naive timestamps, close-before-open and
mixed venues. It exposes `is_session(date)`, `session(date)` and a SHA-256 `calendar_version`
computed from normalized CSV bytes plus `source_version`. The synthetic fixtures contain at
least one A-share weekday and one futures night session, proving that futures trading date is
not derived from the natural date. Production exchange calendars are imported and versioned
data; the code must never guess future holidays from weekdays.

- [ ] **Step 5: Implement the AKShare normalizer**

`AkShareDailyBarProvider` must:

- lazily import `akshare` only when no client is injected;
- call `stock_zh_a_hist` for SSE/SZSE/BSE instruments;
- call `futures_zh_daily_sina` for CFFEX/SHFE/DCE/CZCE/INE/GFEX instruments;
- map Chinese and English column names explicitly and fail with
  `ProviderSchemaError(provider_id, missing_columns)` when required columns disappear;
- convert daily session close from `Asia/Shanghai` to UTC;
- set estimated availability to session close plus one minute;
- preserve `adjustment`, with futures restricted to `Adjustment.NONE`;
- expose upstream interface name and library version through `provider_metadata()`.
- record `series_kind="continuous"` and `roll_policy="upstream_provider"` for symbols ending
  in `0`; concrete futures symbols use `series_kind="contract"`. Continuous data is a research
  view and its provider roll policy must never be presented as a user-tradable contract rule.

Use the following dispatch without dynamic attribute names:

```python
if venue in {Venue.SSE, Venue.SZSE, Venue.BSE}:
    frame = self._client.stock_zh_a_hist(
        symbol=request.instrument_id.symbol,
        period="daily",
        start_date=request.start.strftime("%Y%m%d"),
        end_date=request.end.strftime("%Y%m%d"),
        adjust="" if request.adjustment is Adjustment.NONE else request.adjustment.value,
        timeout=15,
    )
else:
    if request.adjustment is not Adjustment.NONE:
        raise ValueError("futures daily bars do not accept stock adjustment modes")
    frame = self._client.futures_zh_daily_sina(symbol=request.instrument_id.symbol)
```

Add a futures fake test for `RB0.SHFE` that asserts normalized `settlement`,
`open_interest`, continuous-series metadata and filtering to the requested date range.

- [ ] **Step 6: Verify without network access**

Run:

```powershell
uv run pytest tests/data/test_providers.py tests/data/test_akshare_adapter.py tests/data/test_calendars.py -v
uv run ruff check packages/data tests/data
uv run mypy packages/data/src tests/data
```

Expected: tests pass using only injected fakes; no live request occurs.

- [ ] **Step 7: Commit**

```powershell
git add packages/data/src/astraquant_data/providers.py packages/data/src/astraquant_data/adapters packages/data/src/astraquant_data/calendars.py tests/data tests/fixtures/market_data
git commit -m "feat(data): 增加只读行情 Provider 与 AKShare 适配"
```

### Task 4: Create canonical Arrow conversion and deterministic quality reports

**Files:**
- Create: `packages/data/src/astraquant_data/arrow_schema.py`
- Create: `packages/data/src/astraquant_data/quality.py`
- Create: `tests/data/test_arrow_schema.py`
- Create: `tests/data/test_quality.py`

- [ ] **Step 1: Write round-trip and quality tests**

```python
# tests/data/test_quality.py
from astraquant_data.quality import QualityCode, QualitySeverity, evaluate_bars

from .factories import make_bar


def test_duplicate_and_gap_issues_are_stable_and_machine_readable() -> None:
    first = make_bar(symbol="600000.SSE", day=24, availability_estimated=False)
    report = evaluate_bars(
        [
            first,
            first,
            make_bar(symbol="600000.SSE", day=28, availability_estimated=False),
        ],
        expected_trading_dates={first.event_time.date()},
    )
    assert [(issue.code, issue.severity) for issue in report.issues] == [
        (QualityCode.DUPLICATE_KEY, QualitySeverity.ERROR),
        (QualityCode.UNEXPECTED_TRADING_DATE, QualitySeverity.WARNING),
    ]
    assert report.publishable is False
```

Move the shared valid bar constructor to `tests/data/factories.py`. Add a round-trip test
asserting that `bars_to_table()` uses:

```text
instrument_id string
venue dictionary<string>
frequency dictionary<string>
event_time timestamp[us, tz=UTC]
available_time timestamp[us, tz=UTC]
open/high/low/close decimal128(24, 8)
volume/turnover/open_interest/settlement decimal128(30, 8)
adjustment dictionary<string>
availability_estimated bool
```

and `table_to_bars(bars_to_table(input)) == input`.

- [ ] **Step 2: Run tests and observe missing modules**

Run:

```powershell
uv run pytest tests/data/test_arrow_schema.py tests/data/test_quality.py -v
```

Expected: collection FAIL for missing modules.

- [ ] **Step 3: Implement canonical conversion**

Define one exported `BAR_SCHEMA: pyarrow.Schema`. `bars_to_table()` must sort by
`(instrument_id, event_time, available_time)`, quantize prices to eight decimal places,
and reject a table whose schema differs. `table_to_bars()` must parse every enum and
`InstrumentId`; do not return raw dictionaries.

- [ ] **Step 4: Implement deterministic quality evaluation**

```python
# packages/data/src/astraquant_data/quality.py
from dataclasses import dataclass
from enum import StrEnum


class QualitySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class QualityCode(StrEnum):
    EMPTY_DATASET = "EMPTY_DATASET"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    NON_MONOTONIC_TIME = "NON_MONOTONIC_TIME"
    UNEXPECTED_TRADING_DATE = "UNEXPECTED_TRADING_DATE"
    ESTIMATED_AVAILABILITY = "ESTIMATED_AVAILABILITY"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: QualityCode
    severity: QualitySeverity
    count: int
    sample_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityReport:
    row_count: int
    issues: tuple[QualityIssue, ...]

    @property
    def publishable(self) -> bool:
        return all(issue.severity is not QualitySeverity.ERROR for issue in self.issues)
```

`evaluate_bars()` must emit issues in `QualityCode` declaration order, cap samples at five,
and treat empty input, duplicate `(instrument_id, frequency, event_time)` keys and
non-monotonic availability as errors. Estimated availability and dates outside an injected
calendar are warnings. It receives `source_fetched_at` and rejects rows with
`available_time > source_fetched_at`. Calendar input is explicit; do not hard-code future
exchange holidays.

- [ ] **Step 5: Verify**

Run:

```powershell
uv run pytest tests/data/test_arrow_schema.py tests/data/test_quality.py -v
uv run ruff check packages/data tests/data
uv run mypy packages/data/src tests/data
```

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

```powershell
git add packages/data/src/astraquant_data tests/data
git commit -m "feat(data): 规范 Arrow Schema 与数据质量报告"
```

### Task 5: Publish immutable Parquet snapshots and catalogue them in SQLite

**Files:**
- Create: `packages/data/src/astraquant_data/manifests.py`
- Create: `packages/data/src/astraquant_data/parquet_store.py`
- Create: `packages/api/migrations/versions/0002_data_catalog.py`
- Create: `packages/api/src/astraquant_api/data_repository.py`
- Create: `tests/data/test_parquet_store.py`
- Create: `tests/api/test_data_repository.py`
- Modify: `packages/api/src/astraquant_api/database.py`

- [ ] **Step 1: Write atomic-publication tests**

```python
# tests/data/test_parquet_store.py
from datetime import UTC, datetime
import json

import pytest

from astraquant_data.parquet_store import ParquetSnapshotStore, SnapshotRejected
from astraquant_domain import FixedClock

from .factories import make_bar


def test_publish_is_immutable_and_manifest_hash_is_reproducible(tmp_path) -> None:
    clock = FixedClock(datetime(2026, 7, 28, tzinfo=UTC))
    store = ParquetSnapshotStore(tmp_path, clock=clock)
    first = store.publish_bars(
        dataset_id="cn-equity-daily",
        bars=[make_bar(symbol="600000.SSE", day=24)],
        provider={"id": "fixture", "interface": "csv", "version": "1"},
    )
    second = store.publish_bars(
        dataset_id="cn-equity-daily",
        bars=[make_bar(symbol="600000.SSE", day=24)],
        provider={"id": "fixture", "interface": "csv", "version": "1"},
    )
    assert second.snapshot_id == first.snapshot_id
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["snapshot_id"] == first.snapshot_id
    assert not any((tmp_path / ".staging").iterdir())


def test_rejected_snapshot_leaves_no_visible_manifest(tmp_path) -> None:
    store = ParquetSnapshotStore(tmp_path)
    duplicate = make_bar(symbol="RB2610.SHFE", day=24)
    with pytest.raises(SnapshotRejected):
        store.publish_bars(
            dataset_id="cn-futures-daily",
            bars=[duplicate, duplicate],
            provider={"id": "fixture", "interface": "csv", "version": "1"},
        )
    assert list(tmp_path.rglob("manifest.json")) == []
```

- [ ] **Step 2: Verify failure**

Run:

```powershell
uv run pytest tests/data/test_parquet_store.py tests/api/test_data_repository.py -v
```

Expected: collection FAIL for missing store and repository.

- [ ] **Step 3: Implement canonical manifests and staged publication**

The manifest JSON must contain exactly:

```json
{
  "schema_version": 1,
  "snapshot_id": "<sha256 of canonical body without snapshot_id>",
  "dataset_id": "cn-equity-daily",
  "kind": "bars",
  "created_at": "2026-07-28T00:00:00+00:00",
  "source_fetched_at": "2026-07-28T00:00:00+00:00",
  "provider": {"id": "akshare", "interface": "stock_zh_a_hist", "version": "1.18.64"},
  "adjustment": "none",
  "calendar_version": "<sha256>",
  "series_kind": "instrument",
  "roll_policy": null,
  "availability_policy": "estimated_session_close_plus_1m",
  "row_count": 1,
  "min_event_time": "2026-07-24T07:00:00+00:00",
  "max_event_time": "2026-07-24T07:00:00+00:00",
  "files": [{
    "path": "market=cn/asset_class=equity/frequency=1d/trading_date=2026-07-24/part-0.parquet",
    "sha256": "<file hash>",
    "rows": 1
  }],
  "quality": {"publishable": true, "issues": []}
}
```

Write Hive-style partitions below the staging snapshot using
`market / asset_class / frequency / trading_date`; partition values are derived from canonical
domain metadata, never from arbitrary user path text. Write to `<data_root>/.staging/<uuid>/`,
fsync files, compute hashes, then atomically rename
to `<data_root>/datasets/<dataset_id>/snapshots/<snapshot_id>/`. If the target already
exists, compare manifests and return it. Only after rename may callers index the snapshot.
Use `pyarrow.dataset.write_dataset` with Hive partitioning and Parquet options equivalent to
`compression="zstd"` and format version `2.6`.

- [ ] **Step 4: Add the catalog migration and repository**

Migration `0002_data_catalog` creates:

- `data_datasets(dataset_id PK, name, asset_class, frequency, created_at)`
- `data_snapshots(snapshot_id PK, dataset_id FK, status, row_count, min_event_time,
  max_event_time, provider_id, manifest_path, created_at)`
- `data_quality_issues(snapshot_id FK, code, severity, count, samples_json)`

Use a uniqueness constraint on `(dataset_id, snapshot_id)`, indexes on
`data_snapshots(dataset_id, created_at)` and a check restricting status to
`STAGED`/`PUBLISHED`/`REJECTED`. `DataCatalogRepository.stage_snapshot()` inserts dataset,
snapshot and issues in one transaction; `mark_published()` changes only `STAGED` to
`PUBLISHED` and is idempotent on `snapshot_id`. Normal list APIs exclude `STAGED`.
Startup reconciliation verifies a staged manifest and either completes publication or marks
it rejected, so a process interruption cannot silently expose a partial dataset.

- [ ] **Step 5: Verify storage, migration and repository**

Run:

```powershell
uv run pytest tests/data/test_parquet_store.py tests/api/test_data_repository.py -v
uv run alembic -c packages/api/alembic.ini upgrade head
uv run ruff check packages/data packages/api tests/data tests/api
uv run mypy packages/data/src packages/api/src tests/data tests/api
```

Expected: tests pass, migration reaches `0002_data_catalog`, static checks pass.

- [ ] **Step 6: Commit**

```powershell
git add packages/data packages/api/migrations packages/api/src/astraquant_api/data_repository.py tests/data tests/api
git commit -m "feat(data): 发布不可变 Parquet 快照与数据目录"
```

### Task 6: Add safe DuckDB range and point-in-time queries

**Files:**
- Create: `packages/data/src/astraquant_data/query.py`
- Create: `tests/data/test_query.py`

- [ ] **Step 1: Write an as-of leakage regression test**

```python
# tests/data/test_query.py
from datetime import UTC, datetime, timedelta

from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_data.query import MarketDataQuery

from .factories import make_bar


def test_as_of_query_excludes_rows_not_yet_available(tmp_path) -> None:
    cutoff = datetime(2026, 7, 24, 7, 1, tzinfo=UTC)
    visible = make_bar(symbol="600000.SSE", day=24, available_time=cutoff)
    revised = make_bar(
        symbol="600000.SSE",
        day=24,
        close="10.80",
        available_time=cutoff + timedelta(days=1),
    )
    snapshot = ParquetSnapshotStore(tmp_path).publish_bars(
        dataset_id="revision-fixture",
        bars=[visible, revised],
        provider={"id": "fixture", "interface": "memory", "version": "1"},
    )
    query = MarketDataQuery.from_manifest(
        data_root=tmp_path,
        manifest_path=snapshot.manifest_path,
    )
    result = query.bars_as_of(
        instrument_ids=["600000.SSE"],
        decision_time=cutoff,
    )
    assert len(result) == 1
    assert str(result[0].close) == "10.50000000"
```

- [ ] **Step 2: Verify the test fails**

Run:

```powershell
uv run pytest tests/data/test_query.py -v
```

Expected: collection FAIL for missing `MarketDataQuery`.

- [ ] **Step 3: Implement parameterized queries**

`MarketDataQuery` owns a private `duckdb.connect(":memory:")` connection and never accepts
raw SQL from callers. Implement:

```python
@classmethod
def from_manifest(
    cls,
    *,
    data_root: Path,
    manifest_path: Path,
) -> MarketDataQuery: ...

def bars_between(
    self,
    *,
    instrument_ids: Sequence[str],
    start: datetime,
    end: datetime,
) -> list[Bar]: ...

def bars_as_of(
    self,
    *,
    instrument_ids: Sequence[str],
    decision_time: datetime,
) -> list[Bar]: ...
```

Register the explicit list of manifest-approved Parquet paths as an Arrow table or a
parameterized DuckDB relation. The as-of query must filter
`available_time <= decision_time`, then use:

```sql
QUALIFY row_number() OVER (
  PARTITION BY instrument_id, frequency, event_time
  ORDER BY available_time DESC
) = 1
```

Reject naive datetimes, empty instrument lists and any path outside the configured data root.

- [ ] **Step 4: Verify point-in-time behavior**

Run:

```powershell
uv run pytest tests/data/test_query.py -v
uv run ruff check packages/data/src/astraquant_data/query.py tests/data/test_query.py
uv run mypy packages/data/src/astraquant_data/query.py tests/data/test_query.py
```

Expected: all tests pass; the later revision is absent at the earlier cutoff.

- [ ] **Step 5: Commit**

```powershell
git add packages/data/src/astraquant_data/query.py tests/data/test_query.py
git commit -m "feat(data): 增加 DuckDB 时点安全查询"
```

### Task 7: Build reproducible FeatureFrame snapshots

**Files:**
- Create: `packages/domain/src/astraquant_domain/features.py`
- Create: `packages/data/src/astraquant_data/features.py`
- Create: `tests/domain/test_features.py`
- Create: `tests/data/test_feature_snapshots.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`

- [ ] **Step 1: Write feature-time and reproducibility tests**

```python
# tests/domain/test_features.py
from datetime import UTC, datetime, timedelta

import pytest

from astraquant_domain import FeatureFrame, FeatureRow, InstrumentId


def test_feature_row_rejects_a_value_available_after_decision_time() -> None:
    decision = datetime(2026, 7, 24, 7, 1, tzinfo=UTC)
    row = FeatureRow(
        instrument_id=InstrumentId.parse("600000.SSE"),
        event_time=decision,
        available_time=decision + timedelta(seconds=1),
        values={"return_1d": 0.01},
    )
    with pytest.raises(ValueError, match="decision_time"):
        FeatureFrame(
            decision_time=decision,
            definition_version="baseline-v1",
            rows=(row,),
        )


def test_feature_frame_requires_one_stable_feature_schema() -> None:
    now = datetime(2026, 7, 24, 7, 1, tzinfo=UTC)
    first = FeatureRow(InstrumentId.parse("600000.SSE"), now, now, {"return_1d": 0.01})
    second = FeatureRow(InstrumentId.parse("000001.SZSE"), now, now, {"volume_z": 1.2})
    with pytest.raises(ValueError, match="feature schema"):
        FeatureFrame(decision_time=now, definition_version="baseline-v1", rows=(first, second))
```

In `tests/data/test_feature_snapshots.py`, build the same frame twice and assert identical
`snapshot_id`; change one value and assert a different ID. Load it with an earlier cutoff
and assert no row with a later `available_time` is returned.

- [ ] **Step 2: Run tests and observe missing contracts**

Run:

```powershell
uv run pytest tests/domain/test_features.py tests/data/test_feature_snapshots.py -v
```

Expected: collection FAIL for missing feature contracts.

- [ ] **Step 3: Implement domain feature contracts**

```python
# packages/domain/src/astraquant_domain/features.py
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from astraquant_domain.identifiers import InstrumentId


@dataclass(frozen=True, slots=True)
class FeatureRow:
    instrument_id: InstrumentId
    event_time: datetime
    available_time: datetime
    values: Mapping[str, float | None]

    def __post_init__(self) -> None:
        for value in (self.event_time, self.available_time):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("feature timestamps must be timezone-aware")
        if self.available_time < self.event_time:
            raise ValueError("available_time must not precede event_time")
        if not self.values or any(not name.isidentifier() for name in self.values):
            raise ValueError("feature names must be non-empty identifiers")
        object.__setattr__(self, "values", MappingProxyType(dict(sorted(self.values.items()))))


@dataclass(frozen=True, slots=True)
class FeatureFrame:
    decision_time: datetime
    definition_version: str
    rows: tuple[FeatureRow, ...]

    def __post_init__(self) -> None:
        if self.decision_time.tzinfo is None or self.decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        schemas = {tuple(row.values) for row in self.rows}
        if len(schemas) > 1:
            raise ValueError("all rows must share one feature schema")
        if any(row.available_time > self.decision_time for row in self.rows):
            raise ValueError("feature available_time exceeds decision_time")
```

- [ ] **Step 4: Implement feature snapshot storage**

`FeatureSnapshotStore.publish(frame, input_snapshot_ids, code_revision, parameters)` writes
one immutable Parquet file with fixed identity/time columns plus sorted `float64` feature
columns. Its canonical manifest includes `definition_version`, feature names, decision time,
input snapshot IDs, code revision and sorted JSON parameters. Refuse a dirty or empty
`code_revision` string supplied by the caller; do not invoke Git from library code.

- [ ] **Step 5: Verify reproducibility and no-leakage behavior**

Run:

```powershell
uv run pytest tests/domain/test_features.py tests/data/test_feature_snapshots.py -v
uv run mypy packages/domain/src packages/data/src
uv run ruff check packages/domain packages/data tests/domain tests/data
```

Expected: tests and static checks pass.

- [ ] **Step 6: Commit**

```powershell
git add packages/domain/src/astraquant_domain packages/data/src/astraquant_data/features.py tests/domain/test_features.py tests/data/test_feature_snapshots.py
git commit -m "feat(data): 增加可重建 FeatureFrame 快照"
```

### Task 8: Orchestrate cancellable imports and expose the local data API

**Files:**
- Create: `packages/api/src/astraquant_api/data_worker.py`
- Create: `packages/api/src/astraquant_api/data_schemas.py`
- Create: `packages/api/src/astraquant_api/data_routes.py`
- Create: `tests/api/test_data_worker.py`
- Create: `tests/api/test_data_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Modify: `packages/api/src/astraquant_api/config.py`
- Modify: `packages/api/src/astraquant_api/supervisor.py`
- Modify: `packages/api/src/astraquant_api/task_model.py`
- Modify: `packages/api/pyproject.toml`

- [ ] **Step 1: Write API acceptance tests**

```python
# tests/api/test_data_routes.py
def test_create_import_is_authenticated_idempotent_and_never_accepts_trade_fields(
    client,
    auth_headers,
) -> None:
    body = {
        "provider": "fixture",
        "instrument_id": "600000.SSE",
        "frequency": "1d",
        "start": "2026-07-20",
        "end": "2026-07-24",
        "adjustment": "none",
    }
    headers = {**auth_headers, "Idempotency-Key": "data-import-600000-20260724"}
    first = client.post("/v1/data/imports", json=body, headers=headers)
    second = client.post("/v1/data/imports", json=body, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["task_id"] == second.json()["task_id"]

    rejected = client.post(
        "/v1/data/imports",
        json={**body, "account_id": "forbidden"},
        headers={**auth_headers, "Idempotency-Key": "data-import-reject-0001"},
    )
    assert rejected.status_code == 422
```

Add tests for:

- `GET /v1/data/datasets`;
- `GET /v1/data/datasets/{dataset_id}/snapshots`;
- `GET /v1/data/snapshots/{snapshot_id}`;
- `GET /v1/data/snapshots/{snapshot_id}/bars?limit=10`;
- 404 for unknown IDs;
- imports restricted to a configured allow-list of fixture instruments in tests;
- cancellation before staging leaves no catalog row or manifest;
- interruption after catalog staging is hidden from list APIs and resolved by startup recovery.

- [ ] **Step 2: Run tests and verify missing routes**

Run:

```powershell
uv run pytest tests/api/test_data_worker.py tests/api/test_data_routes.py -v
```

Expected: route tests return 404 and worker imports fail.

- [ ] **Step 3: Add strict request/response schemas**

```python
# packages/api/src/astraquant_api/data_schemas.py
from datetime import date
from typing import Literal

from pydantic import Field

from astraquant_api.schemas import StrictModel


class DataImportRequest(StrictModel):
    provider: Literal["fixture", "akshare"]
    instrument_id: str = Field(pattern=r"^[A-Z0-9-]+\.[A-Z]+$")
    frequency: Literal["1d"]
    start: date
    end: date
    adjustment: Literal["none", "qfq", "hfq"] = "none"


class DatasetSummary(StrictModel):
    dataset_id: str
    name: str
    asset_class: Literal["equity", "futures"]
    frequency: str
    snapshot_count: int = Field(ge=0)
    latest_snapshot_id: str | None


class SnapshotSummary(StrictModel):
    snapshot_id: str
    dataset_id: str
    status: Literal["PUBLISHED", "REJECTED"]
    row_count: int = Field(ge=0)
    provider_id: str
    created_at: str
    quality_issues: list[dict[str, object]]


class BarPreview(StrictModel):
    instrument_id: str
    event_time: str
    available_time: str
    open: str
    high: str
    low: str
    close: str
    volume: str
```

Pydantic's `extra="forbid"` inherited from `StrictModel` is the explicit defense against
account/order fields.

- [ ] **Step 4: Generalize the supervisor safely**

Change `Task.task_type` in TypeScript and Python from demo-only assumptions to:

```text
demo.self_check
data.import
```

Add `TaskSupervisor.start(task, worker_target, worker_args)` while preserving
`start_demo()` as a thin compatibility wrapper. `run_data_import_worker()` receives only
serializable request values and `state_dir`; it creates its provider inside the spawned
process and reports steps `fetch`, `normalize`, `validate`, `stage_files`, `stage_catalog`,
`publish_files`, `publish_catalog`. It checks the cancel event before filesystem staging and
before catalog staging. After the catalog enters `STAGED`, interruption is recovered by the
startup reconciler from Task 5; clients never list a staged snapshot.

Do not pass AKShare/Pandas objects through multiprocessing queues. Successful payload:

```json
{
  "dataset_id": "cn-equity-600000-sse-1d-none",
  "snapshot_id": "<sha256>",
  "row_count": 5,
  "quality": "PUBLISHED"
}
```

- [ ] **Step 5: Mount authenticated data routes**

Create `build_data_router(state, authenticated)` and include it from `create_app()`.
All `/v1/data/*` routes use the existing bearer session dependency. The `akshare` provider is
disabled by default in tests and enabled only by local configuration
`ASTRAQUANT_ENABLE_AKSHARE=1`; fixture provider remains offline and deterministic.
The bar-preview endpoint resolves paths only through a published manifest and delegates to
`MarketDataQuery`; it caps `limit` at 100 and never accepts SQL, glob or filesystem paths.

- [ ] **Step 6: Verify API, worker recovery and full Python suite**

Run:

```powershell
uv run pytest tests/api/test_data_worker.py tests/api/test_data_routes.py tests/integration -v
uv run pytest -q
uv run ruff check .
uv run mypy
```

Expected: all tests pass; no type or lint errors.

- [ ] **Step 7: Commit**

```powershell
git add packages/api packages/data tests/api tests/integration pyproject.toml uv.lock
git commit -m "feat(api): 接入数据导入任务与目录查询"
```

### Task 9: Enable the desktop Data Center

**Files:**
- Create: `apps/desktop/src/api/data-contracts.ts`
- Create: `apps/desktop/src/pages/DataPage.tsx`
- Create: `apps/desktop/src/pages/DataPage.test.tsx`
- Create: `apps/desktop/src/components/QualityBadge.tsx`
- Modify: `apps/desktop/src/api/client.ts`
- Modify: `apps/desktop/src/api/queries.ts`
- Modify: `apps/desktop/src/api/contracts.ts`
- Modify: `apps/desktop/src/components/Sidebar.tsx`
- Modify: `apps/desktop/src/App.tsx`
- Modify: `apps/desktop/src/styles/app.css`

- [ ] **Step 1: Write the user-flow test**

```tsx
// apps/desktop/src/pages/DataPage.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import { DataPage } from "./DataPage";

test("imports a sample and exposes quality before snapshot details", async () => {
  const onImport = vi.fn();
  render(
    <DataPage
      datasets={[]}
      selectedDataset={null}
      importing={false}
      onImport={onImport}
      onSelectDataset={vi.fn()}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "导入示例数据" }));
  expect(onImport).toHaveBeenCalledWith(
    expect.objectContaining({ instrument_id: "600000.SSE", provider: "fixture" }),
  );
  expect(screen.getByText("数据只保存在本机")).toBeInTheDocument();
  expect(screen.getByText("不包含账户或下单连接")).toBeInTheDocument();
});
```

Add a second test with one warning and one error to verify that quality severity is conveyed
by both text/icon and color, and that rejected snapshots cannot be selected as feature input.

- [ ] **Step 2: Run the frontend test and observe failure**

Run:

```powershell
pnpm --filter @astraquant/desktop test -- DataPage.test.tsx
```

Expected: FAIL because `DataPage` does not exist.

- [ ] **Step 3: Add typed API calls and queries**

Define:

```ts
export interface DataImportRequest {
  provider: "fixture" | "akshare";
  instrument_id: string;
  frequency: "1d";
  start: string;
  end: string;
  adjustment: "none" | "qfq" | "hfq";
}

export interface DatasetSummary {
  dataset_id: string;
  name: string;
  asset_class: "equity" | "futures";
  frequency: string;
  snapshot_count: number;
  latest_snapshot_id: string | null;
}
```

Add client methods `listDatasets`, `listSnapshots`, `getSnapshot`, `createDataImport`.
Add query keys under `["data", ...]`; poll task state through the existing task query and
invalidate datasets/snapshots after a successful import.

- [ ] **Step 4: Implement the Data Center page**

Enable `data` in `WorkspaceView` and `Sidebar`. The page contains:

- a local-only notice and permanent no-trading-connection notice;
- dataset cards with asset class, frequency, last update and snapshot count;
- a sample import form defaulting to `600000.SSE`, plus selectable `RB0.SHFE`;
- explicit date range and adjustment controls;
- import progress linked to Task Center;
- latest snapshot row count, time coverage, provider and availability policy;
- quality issue list with counts and samples;
- empty, loading, stale, rejected and offline states.

Use existing panels and design tokens. Do not add charts in Phase 2; a compact preview table of
the newest ten bars is sufficient and keeps the page fast.

- [ ] **Step 5: Verify frontend behavior**

Run:

```powershell
pnpm --filter @astraquant/desktop test
pnpm --filter @astraquant/desktop check
pnpm --filter @astraquant/desktop build
```

Expected: all Vitest tests pass, TypeScript check succeeds and Vite build completes.

- [ ] **Step 6: Commit**

```powershell
git add apps/desktop
git commit -m "feat(desktop): 启用本地数据中心工作区"
```

### Task 10: Prove the Phase 2 vertical slice and document operations

**Files:**
- Create: `tests/integration/test_data_round_trip.py`
- Create: `docs/operations/local-data.md`
- Modify: `README.md`
- Modify: `docs/roadmap/product-roadmap.md`
- Modify: `tools/repository_policy.py`
- Modify: `.github/workflows/ci.yml` if native dependency caching requires adjustment

- [ ] **Step 1: Write the end-to-end acceptance test**

```python
# tests/integration/test_data_round_trip.py
def test_fixture_import_catalog_query_and_feature_snapshot_round_trip(runtime_client) -> None:
    response = runtime_client.post(
        "/v1/data/imports",
        headers={"Idempotency-Key": "phase2-e2e-equity-0001"},
        json={
            "provider": "fixture",
            "instrument_id": "600000.SSE",
            "frequency": "1d",
            "start": "2026-07-20",
            "end": "2026-07-24",
            "adjustment": "none",
        },
    )
    assert response.status_code == 201
    task = wait_for_terminal_task(runtime_client, response.json()["task_id"])
    assert task["status"] == "SUCCEEDED"

    snapshots = runtime_client.get(
        f"/v1/data/datasets/{task['result']['dataset_id']}/snapshots"
    ).json()
    assert snapshots[0]["snapshot_id"] == task["result"]["snapshot_id"]
    assert snapshots[0]["status"] == "PUBLISHED"
    assert snapshots[0]["row_count"] > 0
```

Extend the test through the service/query boundary to build a two-feature baseline frame
(`return_1d`, `volume_change_1d`) at a fixed decision time and assert repeated builds have the
same feature snapshot ID.

- [ ] **Step 2: Verify the acceptance test fails before final wiring**

Run:

```powershell
uv run pytest tests/integration/test_data_round_trip.py -v
```

Expected: FAIL at the first unwired catalog/query/feature boundary.

- [ ] **Step 3: Complete only the wiring exposed by the failing test**

Wire the fixture provider, manifest-approved query paths and baseline feature builder through
the existing runtime factory. Do not introduce a generic plugin system or arbitrary Python
feature execution. The baseline builder is a named, versioned function:

```python
BASELINE_FEATURE_VERSION = "returns-volume-v1"


def build_baseline_features(bars: Sequence[Bar], decision_time: datetime) -> FeatureFrame:
    """Build return_1d and volume_change_1d using only rows available at decision_time."""
```

It sorts by instrument/event time, excludes rows whose `available_time` is after the decision
time, and emits a row only when the current and previous bar are both available.

- [ ] **Step 4: Document local-data operation and privacy**

`docs/operations/local-data.md` must include exact commands for:

```powershell
uv sync --all-packages
$env:ASTRAQUANT_STATE_DIR = "D:\AstraQuant-local"
uv run astraquant-api
pnpm --filter @astraquant/desktop dev
```

Explain the local directory tree, fixture import, optional AKShare enable flag, snapshot
immutability, how to remove a user-selected snapshot through a future retention workflow
(manual deletion is not supported in this phase), backup/restore, and the permanent absence of
brokerage credentials and order submission.

Update repository policy tests so committed `.parquet`, `.duckdb`, `.sqlite*`, downloaded CSV,
model weights and state directories fail policy checks; explicitly allow only
`tests/fixtures/market_data/*.csv` below the fixture size limit.

- [ ] **Step 5: Run the complete release gate**

Run:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python -m tools.repository_policy
pnpm --filter @astraquant/desktop test
pnpm --filter @astraquant/desktop check
pnpm --filter @astraquant/desktop build
git diff --check
```

Expected: all commands exit zero. Record test counts and tool versions in the PR description.

- [ ] **Step 6: Update roadmap status only after the release gate passes**

Mark Phase 2 complete in `docs/roadmap/product-roadmap.md` only when:

- both synthetic A-share and futures imports pass;
- immutable manifests and catalog rows agree;
- as-of leakage regression passes;
- repeat feature builds produce identical snapshot IDs;
- Data Center tests and build pass;
- repository policy proves no downloaded data entered Git.

- [ ] **Step 7: Commit**

```powershell
git add tests/integration docs/operations README.md docs/roadmap tools .github
git commit -m "docs(data): 完成 Phase 2 数据闭环验收"
```

## Execution checkpoints

- After Task 5, demonstrate an offline fixture import and inspect one manifest before continuing.
- After Task 8, review API schemas and confirm no account/order fields or methods exist.
- After Task 9, visually inspect Data Center at desktop widths 1280×800 and 1920×1080.
- After Task 10, push the feature branch and update the existing Draft PR; do not merge without
  the complete release gate.

## Source notes

- DuckDB 1.5 supports direct Parquet queries, filter/projection pushdown and Hive-style
  partitioning: <https://duckdb.org/docs/stable/data/parquet/overview>
- PyArrow `write_table`/`read_table` provide the canonical Parquet boundary used here:
  <https://arrow.apache.org/docs/python/parquet.html>
- AKShare documents `stock_zh_a_hist` for A-share daily history and
  `futures_zh_daily_sina` for domestic futures daily history:
  <https://akshare.akfamily.xyz/data/stock/stock.html>
  and <https://akshare.akfamily.xyz/data/futures/futures.html>
- AKShare's upstream web interfaces may change without notice. All adapter tests therefore use
  injected fakes, and live-source smoke tests are opt-in rather than CI requirements.

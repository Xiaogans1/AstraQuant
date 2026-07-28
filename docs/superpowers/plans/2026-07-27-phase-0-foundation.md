# AstraQuant Phase 0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible Python 3.12 workspace with the first versioned trading-domain contracts, deterministic tests, repository data guards, and cross-platform CI.

**Architecture:** Phase 0 creates a small `astraquant-domain` package with no framework dependencies. Domain values, order state, clocks, and event envelopes remain independent from Tauri, HTTP, databases, vn.py, and Qlib so later adapters can translate at the boundary. The root workspace uses uv for Python/tool management and GitHub Actions runs the same checks on Windows and Linux.

**Tech Stack:** Python 3.12, uv, standard-library dataclasses and enums, pytest, Ruff, mypy, PowerShell/Git, GitHub Actions

---

## Scope and file map

This plan intentionally covers only the independently testable Phase 0 foundation. Desktop UI, local API, market-data storage, backtesting, Paper Trading, and real-time advisory signals each receive a separate implementation plan after this foundation is merged. Real brokerage or CTP order integration is outside the product boundary.

| Path | Responsibility |
| --- | --- |
| `.python-version` | Pin the supported Python minor version |
| `.editorconfig` | Cross-editor text defaults |
| `.gitattributes` | Stable line endings across Windows and Linux |
| `pyproject.toml` | Root uv workspace and shared test/lint/type-check configuration |
| `uv.lock` | Reproducible Python dependency graph |
| `packages/domain/pyproject.toml` | `astraquant-domain` package metadata |
| `packages/domain/src/astraquant_domain/identifiers.py` | Venue and instrument identifiers |
| `packages/domain/src/astraquant_domain/orders.py` | Order values, validation, and state transitions |
| `packages/domain/src/astraquant_domain/clocks.py` | Production and deterministic clock contracts |
| `packages/domain/src/astraquant_domain/events.py` | Versioned event envelope |
| `tools/repository_policy.py` | Prevent private data and runtime artifacts from being tracked |
| `tests/domain/` | Domain unit and invariant tests |
| `tests/repository/` | Repository policy tests |
| `.github/workflows/ci.yml` | Windows/Linux verification |
| `.github/dependabot.yml` | Dependency update configuration |
| `docs/architecture/adr/0001-foundation-boundaries.md` | Phase 0 architecture decision record |

### Task 1: Bootstrap the uv workspace

**Files:**
- Create: `.python-version`
- Create: `.editorconfig`
- Create: `.gitattributes`
- Create: `pyproject.toml`
- Create: `packages/domain/pyproject.toml`
- Create: `packages/domain/src/astraquant_domain/__init__.py`
- Create: `uv.lock`

- [x] **Step 1: Install uv and Python 3.12**

Run:

```powershell
winget install --id astral-sh.uv --exact --source winget --accept-package-agreements --accept-source-agreements --silent
uv python install 3.12
```

Expected: `uv --version` succeeds and `uv python find 3.12` prints a managed Python 3.12 executable.

- [x] **Step 2: Add cross-platform text configuration**

Create `.python-version`:

```text
3.12
```

Create `.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
indent_style = space
indent_size = 4
trim_trailing_whitespace = true

[*.{md,yml,yaml,json}]
indent_size = 2

[*.md]
trim_trailing_whitespace = false
```

Create `.gitattributes`:

```gitattributes
* text=auto
*.py text eol=lf
*.toml text eol=lf
*.yml text eol=lf
*.yaml text eol=lf
*.md text eol=lf
*.ps1 text eol=crlf
```

- [x] **Step 3: Create the root workspace configuration**

Create `pyproject.toml`:

```toml
[project]
name = "astraquant-workspace"
version = "0.0.0"
requires-python = ">=3.12,<3.13"
dependencies = ["astraquant-domain"]

[dependency-groups]
dev = [
  "mypy>=1.17,<2",
  "pytest>=8.4,<10",
  "ruff>=0.12,<1",
]

[tool.uv]
package = false

[tool.uv.sources]
astraquant-domain = { workspace = true }

[tool.uv.workspace]
members = ["packages/domain"]

[tool.pytest.ini_options]
addopts = "-ra --strict-config --strict-markers"
pythonpath = ["."]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.ruff.lint.isort]
known-first-party = ["astraquant_domain", "tools"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["packages/domain/src", "tools", "tests"]
```

- [x] **Step 4: Create the dependency-free domain package**

Create `packages/domain/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "astraquant-domain"
version = "0.1.0"
description = "Stable domain contracts for AstraQuant."
requires-python = ">=3.12,<3.13"
dependencies = []

[tool.hatch.build.targets.wheel]
packages = ["src/astraquant_domain"]
```

Create `packages/domain/src/astraquant_domain/__init__.py`:

```python
"""Stable domain contracts shared by AstraQuant runtimes."""
```

- [x] **Step 5: Lock and synchronize dependencies**

Run:

```powershell
uv lock
uv sync --all-packages
uv run python -c "import astraquant_domain; print(astraquant_domain.__doc__)"
```

Expected: the import prints `Stable domain contracts shared by AstraQuant runtimes.`

- [x] **Step 6: Commit the workspace**

```powershell
git add .python-version .editorconfig .gitattributes pyproject.toml uv.lock packages/domain
git commit -m "build: 初始化 Python 工作区"
```

### Task 2: Implement instrument identifiers

**Files:**
- Create: `tests/domain/test_identifiers.py`
- Create: `packages/domain/src/astraquant_domain/identifiers.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`

- [x] **Step 1: Write failing identifier tests**

Create `tests/domain/test_identifiers.py`:

```python
import pytest

from astraquant_domain.identifiers import InstrumentId, Venue


def test_parse_equity_identifier() -> None:
    instrument = InstrumentId.parse("600000.SSE")

    assert instrument.symbol == "600000"
    assert instrument.venue is Venue.SSE
    assert str(instrument) == "600000.SSE"


def test_normalize_futures_symbol_to_uppercase() -> None:
    instrument = InstrumentId.parse("rb2610.SHFE")

    assert str(instrument) == "RB2610.SHFE"


@pytest.mark.parametrize("value", ["", "600000", ".SSE", "600000.UNKNOWN", "600000.SSE.EXTRA"])
def test_reject_invalid_identifier(value: str) -> None:
    with pytest.raises(ValueError):
        InstrumentId.parse(value)
```

- [x] **Step 2: Run the tests and observe the missing module**

Run:

```powershell
uv run pytest tests/domain/test_identifiers.py -v
```

Expected: FAIL during collection with `ModuleNotFoundError: astraquant_domain.identifiers`.

- [x] **Step 3: Implement identifiers**

Create `packages/domain/src/astraquant_domain/identifiers.py`:

```python
"""Canonical identifiers for supported Chinese exchanges."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]*$")


class Venue(StrEnum):
    """Trading venue code used in canonical instrument identifiers."""

    SSE = "SSE"
    SZSE = "SZSE"
    BSE = "BSE"
    CFFEX = "CFFEX"
    SHFE = "SHFE"
    DCE = "DCE"
    CZCE = "CZCE"
    INE = "INE"
    GFEX = "GFEX"


@dataclass(frozen=True, slots=True, order=True)
class InstrumentId:
    """A canonical instrument key such as ``600000.SSE`` or ``RB2610.SHFE``."""

    symbol: str
    venue: Venue

    def __post_init__(self) -> None:
        normalized = self.symbol.strip().upper()
        if not _SYMBOL_PATTERN.fullmatch(normalized):
            raise ValueError(f"Invalid instrument symbol: {self.symbol!r}")
        object.__setattr__(self, "symbol", normalized)

    @classmethod
    def parse(cls, value: str) -> Self:
        parts = value.strip().split(".")
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"Invalid instrument identifier: {value!r}")
        symbol, venue = parts
        try:
            return cls(symbol=symbol, venue=Venue(venue.upper()))
        except ValueError as error:
            raise ValueError(f"Invalid instrument identifier: {value!r}") from error

    def __str__(self) -> str:
        return f"{self.symbol}.{self.venue.value}"
```

Update `packages/domain/src/astraquant_domain/__init__.py`:

```python
"""Stable domain contracts shared by AstraQuant runtimes."""

from astraquant_domain.identifiers import InstrumentId, Venue

__all__ = ["InstrumentId", "Venue"]
```

- [x] **Step 4: Run identifier tests**

Run:

```powershell
uv run pytest tests/domain/test_identifiers.py -v
```

Expected: 7 tests pass.

- [x] **Step 5: Commit identifiers**

```powershell
git add packages/domain/src/astraquant_domain tests/domain/test_identifiers.py
git commit -m "feat(domain): 增加交易标的标识"
```

### Task 3: Define validated order requests

**Files:**
- Create: `tests/domain/test_orders.py`
- Create: `packages/domain/src/astraquant_domain/orders.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`

- [x] **Step 1: Write failing order validation tests**

Create `tests/domain/test_orders.py`:

```python
from decimal import Decimal
from uuid import UUID

import pytest

from astraquant_domain.identifiers import InstrumentId
from astraquant_domain.orders import (
    Environment,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
INSTRUMENT = InstrumentId.parse("RB2610.SHFE")


def test_create_limit_order() -> None:
    request = OrderRequest(
        client_order_id=ORDER_ID,
        instrument_id=INSTRUMENT,
        environment=Environment.PAPER,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        time_in_force=TimeInForce.DAY,
        limit_price=Decimal("3500.5"),
    )

    assert request.quantity == Decimal("2")
    assert request.limit_price == Decimal("3500.5")


def test_limit_order_requires_price() -> None:
    with pytest.raises(ValueError, match="limit_price is required"):
        OrderRequest(
            client_order_id=ORDER_ID,
            instrument_id=INSTRUMENT,
            environment=Environment.PAPER,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            time_in_force=TimeInForce.DAY,
        )


def test_market_order_rejects_limit_price() -> None:
    with pytest.raises(ValueError, match="limit_price must be omitted"):
        OrderRequest(
            client_order_id=ORDER_ID,
            instrument_id=INSTRUMENT,
            environment=Environment.PAPER,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            time_in_force=TimeInForce.IOC,
            limit_price=Decimal("3500"),
        )


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1")])
def test_order_quantity_must_be_positive(quantity: Decimal) -> None:
    with pytest.raises(ValueError, match="quantity must be positive"):
        OrderRequest(
            client_order_id=ORDER_ID,
            instrument_id=INSTRUMENT,
            environment=Environment.PAPER,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
            time_in_force=TimeInForce.IOC,
        )
```

- [x] **Step 2: Run the tests and observe the missing order module**

Run:

```powershell
uv run pytest tests/domain/test_orders.py -v
```

Expected: FAIL during collection with `ModuleNotFoundError: astraquant_domain.orders`.

- [x] **Step 3: Implement order values and validation**

Create `packages/domain/src/astraquant_domain/orders.py`:

```python
"""Order values shared by backtest, Paper, and Live environments."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from astraquant_domain.identifiers import InstrumentId


class Environment(StrEnum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


@dataclass(frozen=True, slots=True)
class OrderRequest:
    client_order_id: UUID
    instrument_id: InstrumentId
    environment: Environment
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    time_in_force: TimeInForce
    limit_price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for LIMIT orders")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price must be omitted for MARKET orders")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("limit_price must be positive")
```

Export the new types from `packages/domain/src/astraquant_domain/__init__.py`:

```python
"""Stable domain contracts shared by AstraQuant runtimes."""

from astraquant_domain.identifiers import InstrumentId, Venue
from astraquant_domain.orders import (
    Environment,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)

__all__ = [
    "Environment",
    "InstrumentId",
    "OrderRequest",
    "OrderSide",
    "OrderType",
    "TimeInForce",
    "Venue",
]
```

- [x] **Step 4: Run order validation tests**

Run:

```powershell
uv run pytest tests/domain/test_orders.py -v
```

Expected: 5 tests pass.

- [x] **Step 5: Commit order values**

```powershell
git add packages/domain/src/astraquant_domain tests/domain/test_orders.py
git commit -m "feat(domain): 定义订单请求契约"
```

### Task 4: Add the order state machine

**Files:**
- Modify: `tests/domain/test_orders.py`
- Modify: `packages/domain/src/astraquant_domain/orders.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`

- [x] **Step 1: Add failing transition tests**

Extend the existing import from `astraquant_domain.orders` so it reads:

```python
from astraquant_domain.orders import (
    Environment,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    transition_order,
)
```

Then append these tests to `tests/domain/test_orders.py`:

```python
@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderStatus.PENDING_SUBMIT, OrderStatus.SUBMITTED),
        (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED),
        (OrderStatus.SUBMITTED, OrderStatus.CANCEL_PENDING),
        (OrderStatus.CANCEL_PENDING, OrderStatus.CANCELED),
    ],
)
def test_allow_valid_order_transition(current: OrderStatus, target: OrderStatus) -> None:
    assert transition_order(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderStatus.FILLED, OrderStatus.CANCELED),
        (OrderStatus.CANCELED, OrderStatus.SUBMITTED),
        (OrderStatus.REJECTED, OrderStatus.SUBMITTED),
        (OrderStatus.PENDING_SUBMIT, OrderStatus.FILLED),
    ],
)
def test_reject_invalid_order_transition(current: OrderStatus, target: OrderStatus) -> None:
    with pytest.raises(ValueError, match="Invalid order transition"):
        transition_order(current, target)
```

- [x] **Step 2: Run transition tests and observe missing symbols**

Run:

```powershell
uv run pytest tests/domain/test_orders.py -v
```

Expected: FAIL during collection because `OrderStatus` and `transition_order` do not exist.

- [x] **Step 3: Implement explicit transitions**

Append to `packages/domain/src/astraquant_domain/orders.py`:

```python
class OrderStatus(StrEnum):
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


_ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING_SUBMIT: frozenset({OrderStatus.SUBMITTED, OrderStatus.REJECTED}),
    OrderStatus.SUBMITTED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.CANCEL_PENDING,
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.CANCEL_PENDING: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
        }
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}


def transition_order(current: OrderStatus, target: OrderStatus) -> OrderStatus:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Invalid order transition: {current.value} -> {target.value}")
    return target
```

Replace `packages/domain/src/astraquant_domain/__init__.py` with:

```python
"""Stable domain contracts shared by AstraQuant runtimes."""

from astraquant_domain.identifiers import InstrumentId, Venue
from astraquant_domain.orders import (
    Environment,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    transition_order,
)

__all__ = [
    "Environment",
    "InstrumentId",
    "OrderRequest",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "TimeInForce",
    "Venue",
    "transition_order",
]
```

- [x] **Step 4: Run all order tests**

Run:

```powershell
uv run pytest tests/domain/test_orders.py -v
```

Expected: 14 tests pass.

- [x] **Step 5: Commit the state machine**

```powershell
git add packages/domain/src/astraquant_domain tests/domain/test_orders.py
git commit -m "feat(domain): 增加订单状态机"
```

### Task 5: Add deterministic clocks and versioned events

**Files:**
- Create: `tests/domain/test_events.py`
- Create: `packages/domain/src/astraquant_domain/clocks.py`
- Create: `packages/domain/src/astraquant_domain/events.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`

- [x] **Step 1: Write failing event tests**

Create `tests/domain/test_events.py`:

```python
from datetime import UTC, datetime
from uuid import UUID

import pytest

from astraquant_domain.clocks import FixedClock
from astraquant_domain.events import EventEnvelope

EVENT_ID = UUID("00000000-0000-0000-0000-000000000010")
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000020")
NOW = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)


def test_create_deterministic_event() -> None:
    event = EventEnvelope.create(
        event_type="order.submitted",
        payload={"client_order_id": "order-1"},
        clock=FixedClock(NOW),
        event_id=EVENT_ID,
        correlation_id=CORRELATION_ID,
    )

    assert event.event_id == EVENT_ID
    assert event.correlation_id == CORRELATION_ID
    assert event.occurred_at == NOW
    assert event.schema_version == 1


def test_reject_naive_event_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EventEnvelope(
            event_id=EVENT_ID,
            correlation_id=CORRELATION_ID,
            occurred_at=datetime(2026, 7, 27, 8, 0),
            event_type="order.submitted",
            schema_version=1,
            payload={},
        )


@pytest.mark.parametrize("event_type", ["", " ", ".invalid", "invalid."])
def test_reject_invalid_event_type(event_type: str) -> None:
    with pytest.raises(ValueError, match="event_type"):
        EventEnvelope(
            event_id=EVENT_ID,
            correlation_id=CORRELATION_ID,
            occurred_at=NOW,
            event_type=event_type,
            schema_version=1,
            payload={},
        )
```

- [x] **Step 2: Run event tests and observe missing modules**

Run:

```powershell
uv run pytest tests/domain/test_events.py -v
```

Expected: FAIL during collection for missing `astraquant_domain.clocks`.

- [x] **Step 3: Implement clock contracts**

Create `packages/domain/src/astraquant_domain/clocks.py`:

```python
"""Clock contracts for production time and deterministic tests."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class FixedClock:
    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise ValueError("FixedClock value must be timezone-aware")

    def now(self) -> datetime:
        return self.value
```

- [x] **Step 4: Implement the event envelope**

Create `packages/domain/src/astraquant_domain/events.py`:

```python
"""Versioned events shared across process boundaries."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self
from uuid import UUID, uuid4

from astraquant_domain.clocks import Clock

_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: UUID
    correlation_id: UUID
    occurred_at: datetime
    event_type: str
    schema_version: int
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not _EVENT_TYPE_PATTERN.fullmatch(self.event_type):
            raise ValueError(f"Invalid event_type: {self.event_type!r}")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        clock: Clock,
        event_id: UUID | None = None,
        correlation_id: UUID | None = None,
        schema_version: int = 1,
    ) -> Self:
        return cls(
            event_id=event_id or uuid4(),
            correlation_id=correlation_id or uuid4(),
            occurred_at=clock.now(),
            event_type=event_type,
            schema_version=schema_version,
            payload=payload,
        )
```

Replace `packages/domain/src/astraquant_domain/__init__.py` with:

```python
"""Stable domain contracts shared by AstraQuant runtimes."""

from astraquant_domain.clocks import Clock, FixedClock, SystemClock
from astraquant_domain.events import EventEnvelope
from astraquant_domain.identifiers import InstrumentId, Venue
from astraquant_domain.orders import (
    Environment,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    transition_order,
)

__all__ = [
    "Clock",
    "Environment",
    "EventEnvelope",
    "FixedClock",
    "InstrumentId",
    "OrderRequest",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "SystemClock",
    "TimeInForce",
    "Venue",
    "transition_order",
]
```

- [x] **Step 5: Run event and domain tests**

Run:

```powershell
uv run pytest tests/domain -v
```

Expected: all domain tests pass.

- [x] **Step 6: Commit events and clocks**

```powershell
git add packages/domain/src/astraquant_domain tests/domain/test_events.py
git commit -m "feat(domain): 增加版本化领域事件"
```

### Task 6: Enforce the repository data boundary

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/repository_policy.py`
- Create: `tests/repository/test_repository_policy.py`

- [x] **Step 1: Write failing policy tests**

Create `tools/__init__.py`:

```python
"""Repository maintenance tools."""
```

Create `tests/repository/test_repository_policy.py`:

```python
from tools.repository_policy import find_forbidden_paths


def test_allow_source_and_small_fixture_files() -> None:
    paths = [
        "packages/domain/src/astraquant_domain/orders.py",
        "tests/fixtures/orders/sample_order.json",
        ".env.example",
    ]

    assert find_forbidden_paths(paths) == []


def test_reject_private_data_and_runtime_files() -> None:
    paths = [
        ".env",
        "data/sse/2026-07-27.parquet",
        "runtime/astraquant.sqlite3",
        "models/alpha.ckpt",
        "credentials-prod.json",
    ]

    assert find_forbidden_paths(paths) == paths
```

- [x] **Step 2: Run policy tests and observe the missing module**

Run:

```powershell
uv run pytest tests/repository/test_repository_policy.py -v
```

Expected: FAIL because `tools.repository_policy` does not exist.

- [x] **Step 3: Implement the policy checker**

Create `tools/repository_policy.py`:

```python
"""Reject private data and runtime artifacts from the Git index."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import PurePosixPath

FORBIDDEN_NAMES = {
    ".env",
    "credentials.json",
    "secrets.json",
}
FORBIDDEN_PREFIXES = (
    "credentials-",
    "secrets-",
)
FORBIDDEN_SUFFIXES = {
    ".arrow",
    ".ckpt",
    ".db",
    ".duckdb",
    ".feather",
    ".parquet",
    ".pem",
    ".pfx",
    ".p12",
    ".sqlite",
    ".sqlite3",
}
FORBIDDEN_DIRECTORIES = {
    ".astraquant",
    "artifacts",
    "checkpoints",
    "data",
    "datasets",
    "logs",
    "models",
    "reports",
}


def find_forbidden_paths(paths: Iterable[str]) -> list[str]:
    forbidden: list[str] = []
    for raw_path in paths:
        path = PurePosixPath(raw_path)
        lowered_name = path.name.lower()
        directory_parts = {part.lower() for part in path.parts[:-1]}
        is_forbidden = (
            lowered_name in FORBIDDEN_NAMES
            or lowered_name.startswith(FORBIDDEN_PREFIXES)
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
            or bool(directory_parts & FORBIDDEN_DIRECTORIES)
        )
        if is_forbidden:
            forbidden.append(raw_path)
    return forbidden


def tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line for line in completed.stdout.splitlines() if line]


def main() -> int:
    forbidden = find_forbidden_paths(tracked_files())
    if not forbidden:
        print("Repository policy passed.")
        return 0
    print("Forbidden tracked files:")
    for path in forbidden:
        print(f"- {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Run policy tests and the live index check**

Run:

```powershell
uv run pytest tests/repository/test_repository_policy.py -v
uv run python -m tools.repository_policy
```

Expected: 2 tests pass and the command prints `Repository policy passed.`

- [x] **Step 5: Commit the repository guard**

```powershell
git add tools tests/repository
git commit -m "build: 增加仓库数据边界检查"
```

### Task 7: Add CI and architecture documentation

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/dependabot.yml`
- Create: `docs/architecture/adr/0001-foundation-boundaries.md`
- Modify: `README.md`

- [x] **Step 1: Create cross-platform CI**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  python:
    name: Python (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, ubuntu-latest]
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v9.0.0
        with:
          enable-cache: true
          python-version: "3.12"
      - run: uv sync --locked --all-packages
      - run: uv run ruff format --check .
      - run: uv run ruff check .
      - run: uv run mypy
      - run: uv run pytest
      - run: uv run python -m tools.repository_policy
```

- [x] **Step 2: Configure dependency updates**

Create `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: uv
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
```

- [x] **Step 3: Record the foundation decision**

Create `docs/architecture/adr/0001-foundation-boundaries.md`:

```markdown
# ADR-0001：Phase 0 工程与领域边界

状态：已接受
日期：2026-07-27

## 决策

AstraQuant 使用 Python 3.12 和 uv 建立 Monorepo。首个可执行包
`astraquant-domain` 不依赖 UI、HTTP、数据库或第三方量化框架。

领域包只包含标的标识、订单契约、订单状态、时钟和版本化事件。
vn.py、Qlib、Tauri、FastAPI、DuckDB 和 SQLite 均在后续适配层使用。

## 原因

- Python 3.12 兼容量化与数据生态，避免以本机 Python 3.14 作为隐式基线。
- 无框架领域包可以被回测、Paper、Live 和测试共同复用。
- Windows/Linux CI 尽早发现路径、编码和行尾差异。
- 仓库策略检查防止私人行情、密钥和运行数据库进入 Git。

## 结果

后续模块必须依赖公开领域契约，不能把第三方项目对象直接暴露给 UI
或跨进程接口。领域契约发生不兼容变化时必须显式升级版本。
```

- [x] **Step 4: Add developer quick start to README**

Append:

````markdown
## 开发环境

Phase 0 使用 Python 3.12 和 uv：

```powershell
uv python install 3.12
uv sync --locked --all-packages
uv run pytest
uv run ruff check .
uv run mypy
```

本机安装的其他 Python 版本不会成为项目运行基线。
````

- [x] **Step 5: Run all local quality gates**

Run:

```powershell
uv run ruff format .
uv run ruff check .
uv run mypy
uv run pytest
uv run python -m tools.repository_policy
git diff --check
```

Expected: Ruff reports no errors, mypy reports success, all tests pass, repository policy passes, and `git diff --check` is silent.

- [x] **Step 6: Commit CI and documentation**

```powershell
git add .github README.md docs/architecture
git commit -m "ci: 建立跨平台质量门禁"
```

### Task 8: Verify and publish Phase 0

**Files:**
- Modify: `docs/superpowers/plans/2026-07-27-phase-0-foundation.md`

- [x] **Step 1: Mark completed checkboxes in this plan**

Change each executed `- [ ]` marker to `- [x]` without altering the prescribed commands or expected outcomes.

- [x] **Step 2: Run the complete verification suite from a clean shell**

Run:

```powershell
uv sync --locked --all-packages
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -v
uv run python -m tools.repository_policy
git diff --check
git status -sb
```

Expected: every command exits zero; `git status` only shows the plan checkbox update.

- [x] **Step 3: Commit plan execution state**

```powershell
git add docs/superpowers/plans/2026-07-27-phase-0-foundation.md
git commit -m "docs: 记录 Phase 0 实施结果"
```

- [x] **Step 4: Push the feature branch and open a Draft PR**

Run:

```powershell
git push -u origin feature/phase-0-foundation
gh pr create --draft --base main --head feature/phase-0-foundation --title "feat: 建立 Phase 0 工程基础" --body "建立 Python 3.12/uv 工程基础、领域契约、仓库数据边界与 Windows/Linux CI。验证命令：uv run ruff format --check .；uv run ruff check .；uv run mypy；uv run pytest -v；uv run python -m tools.repository_policy。"
```

The PR body must list the domain contracts, repository policy, CI platforms, exact verification commands, and any environmental limitation encountered during implementation.

- [x] **Step 5: Verify the remote branch and checks**

Run:

```powershell
gh pr view --json url,isDraft,headRefName,baseRefName,statusCheckRollup
```

Expected: the PR targets `main`, remains Draft, and the CI jobs are visible. If checks are still running, report that state without claiming they passed.

# Phase 3A Eastmoney Realtime Market Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every production homepage market placeholder with authenticated Eastmoney `gm` data, six built-in core indices, a bounded real watchlist, explicit unavailable states, and readable high-DPI typography.

**Architecture:** The AstraQuant API keeps running in its managed workspace environment and supervises a separate Eastmoney bridge process launched with the user's SDK Python. The bridge exposes a narrow NDJSON request/response protocol over stdin/stdout and calls `set_token`, `current`, `history_n`, reference-data and calendar APIs; the main service owns subscription budgeting, polling, health, cache and authenticated loopback routes. React Query consumes one canonical market-home contract and never imports development snapshots or substitutes fake numbers.

**Tech Stack:** Python 3.12, Eastmoney `gm 3.0.186` in an external virtual environment, asyncio, subprocess NDJSON, FastAPI/Pydantic, SQLAlchemy settings storage, Windows Credential Manager through `keyring`, React 19, TypeScript, TanStack Query, Vitest, CSS, Tauri 2, uv.

---

## Scope and fixed decisions

This plan implements only Phase 3A from
`docs/superpowers/specs/2026-08-05-eastmoney-realtime-and-global-radar-design.md`.

In scope:

- improve Windows/WebView2 typography before adding more dense market information;
- launch and supervise the verified external Eastmoney Python SDK without installing `gm` into the AstraQuant workspace;
- store the Eastmoney token in the operating-system credential store and never return it to the UI;
- poll Eastmoney `current()` at the provider's approximately three-second stock/index cadence;
- query real 60-second intraday bars with `history_n()`;
- always include six real core indices;
- enforce the free-tier limit of 50 active instruments;
- persist only non-secret watchlist/configuration data;
- expose authenticated local API routes for connection, home, search, watchlist and intraday data;
- delete the production development snapshot and render loading, stale, closed, unavailable and error states honestly;
- leave market breadth, AI intelligence and quant candidates explicitly unavailable until their real upstream systems exist;
- perform a real-session acceptance run without writing raw quotes or credentials into the repository.

Out of scope:

- Alpaca and US extended-hours data (separate Phase 3B plan);
- global thematic baskets and cross-market AI mapping;
- full-A breadth or scanning without full-market rights;
- real brokerage orders or account access;
- Paper matching, signal generation and DeepSeek integration;
- Tick persistence beyond the latest in-memory snapshot and existing local activity logging.

The implementation uses snapshot polling rather than `gm.run(MODE_LIVE)` for this vertical slice.
Official `set_token` documentation permits direct data-function access, and `current` returns the
current Tick snapshot. This avoids requiring a strategy ID and keeps the bridge read-only. A later
performance phase may replace polling with `subscribe` after the real-session slice is proven.

## Current baseline and defects to remove

- `apps/desktop/src/features/market/developmentMarket.ts` hard-codes index, stock, ETF, future, breadth, sector and candidate values.
- `OverviewPage` imports that file directly, so the local API is bypassed entirely.
- the fake catalog includes continuous futures such as `RB0.SHFE` and `IF0.CFFEX` even though Eastmoney realtime mode requires concrete month contracts.
- the homepage claims “全 A 股” breadth and “全市场扫描” without a full-market source.
- the market CSS contains many `8px`, `9px` and `10px` readable labels; Chinese labels inherit `Cascadia Mono`, and the root forces `text-rendering: geometricPrecision`.
- the AstraQuant API environment does not contain `gm`; the verified SDK interpreter is currently
  `D:\AstraQuantData\Eastmoney\PythonSDK\Scripts\python.exe` and must remain external to Git.

## File map

| Path | Responsibility |
| --- | --- |
| `apps/desktop/src/theme/tokens.css` | Readable Chinese/UI/data font tokens |
| `apps/desktop/src/styles/app.css` | High-DPI market typography and state styling |
| `apps/desktop/src/styles/marketTypography.test.ts` | Guard against unreadable market CSS |
| `packages/domain/src/astraquant_domain/live_market.py` | Canonical live quote, depth and quality records |
| `packages/domain/src/astraquant_domain/__init__.py` | Export live-market contracts |
| `packages/data/src/astraquant_data/eastmoney_protocol.py` | Typed NDJSON commands/responses and gm mapping |
| `packages/data/src/astraquant_data/eastmoney_client.py` | External SDK subprocess lifecycle |
| `packages/data/src/astraquant_data/live_providers.py` | Provider health/capability protocol |
| `packages/data/src/astraquant_data/adapters/eastmoney.py` | Polling provider and intraday/reference queries |
| `packages/data/src/astraquant_data/subscriptions.py` | Six reserved indices and 50-slot budget |
| `packages/data/src/astraquant_data/adapters/__init__.py` | Export Eastmoney adapter |
| `tools/eastmoney_bridge.py` | Self-contained gm worker run by SDK Python |
| `tests/fixtures/eastmoney/fake_bridge.py` | Deterministic subprocess fixture without gm |
| `packages/api/src/astraquant_api/secret_store.py` | Windows Credential Manager abstraction |
| `packages/api/src/astraquant_api/market_config.py` | Non-secret Eastmoney settings and discovery |
| `packages/api/src/astraquant_api/market_service.py` | Polling lifecycle, cache, state and watchlist |
| `packages/api/src/astraquant_api/market_schemas.py` | Strict public market response models |
| `packages/api/src/astraquant_api/market_routes.py` | Authenticated market endpoints |
| `packages/api/src/astraquant_api/app.py` | Attach market service/router and shutdown |
| `packages/api/src/astraquant_api/cli.py` | Construct credential store and market service |
| `packages/api/pyproject.toml` | Add keyring dependency |
| `apps/desktop/src/api/market-contracts.ts` | TypeScript API contracts |
| `apps/desktop/src/api/client.ts` | Market API methods |
| `apps/desktop/src/api/queries.ts` | Polling queries and mutations |
| `apps/desktop/src/components/MarketConnectionPanel.tsx` | SDK/token/health controls |
| `apps/desktop/src/pages/OverviewPage.tsx` | Real market home and honest unavailable states |
| `apps/desktop/src/pages/OverviewPage.test.tsx` | Real-state UI tests |
| `apps/desktop/src/App.tsx` | Pass API client into market home |
| `apps/desktop/src/App.test.tsx` | Mock market endpoints |
| `apps/desktop/src/features/market/developmentMarket.ts` | Delete production fake snapshot |
| `apps/desktop/src/features/market/developmentMarket.test.ts` | Delete obsolete simulation tests |
| `docs/operations/eastmoney-market-data.md` | Setup, token, data status and troubleshooting |
| `docs/research/eastmoney-realtime-acceptance.md` | Aggregate-only real-session acceptance record |
| `tools/eastmoney_probe.py` | Safe aggregate validation without quote persistence |
| `tools/repository_policy.py` | Reject market dumps, bridge captures and secrets |

### Task 0: Establish readable high-DPI typography

**Files:**

- Create: `apps/desktop/src/styles/marketTypography.test.ts`
- Modify: `apps/desktop/src/theme/tokens.css`
- Modify: `apps/desktop/src/styles/app.css`
- Test: `apps/desktop/src/styles/marketTypography.test.ts`

- [ ] **Step 1: Write the failing typography guard**

Create a Node-environment Vitest test that isolates the market section and fails on the current
`8px`–`10px` rules:

```ts
// @vitest-environment node
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const tokens = readFileSync(new URL("../theme/tokens.css", import.meta.url), "utf8");
const css = readFileSync(new URL("./app.css", import.meta.url), "utf8");
const marketCss = css.slice(css.indexOf(".market-terminal"));

describe("market typography", () => {
  it("does not force geometric precision in WebView2", () => {
    expect(tokens).not.toContain("text-rendering: geometricPrecision");
  });

  it("keeps readable market content at twelve pixels or larger", () => {
    expect(marketCss).not.toMatch(/font-size:\s*(8|9|10|11)px/);
  });

  it("keeps Chinese UI and numeric fonts separate", () => {
    expect(tokens).toContain('--font-ui: "Microsoft YaHei UI"');
    expect(tokens).toContain('--font-numeric: "Cascadia Mono"');
  });
});
```

- [ ] **Step 2: Run the guard and verify the root cause**

Run:

```powershell
npm --prefix apps/desktop test -- marketTypography.test.ts
```

Expected: FAIL for `geometricPrecision` and market `8px`–`11px` declarations.

- [ ] **Step 3: Define explicit UI and numeric font tokens**

Replace the root font section with:

```css
:root {
  color-scheme: dark;
  font-family: "Microsoft YaHei UI", "Segoe UI Variable Text", "Segoe UI", sans-serif;
  font-synthesis: none;

  --font-ui: "Microsoft YaHei UI", "Segoe UI Variable Text", "Segoe UI", sans-serif;
  --font-display: "Microsoft YaHei UI", "Segoe UI Variable Display", "Segoe UI", sans-serif;
  --font-numeric: "Cascadia Mono", "SFMono-Regular", Consolas, "Microsoft YaHei UI", monospace;
  --font-body: var(--font-ui);
  --font-data: var(--font-numeric);
  --text-xs: 12px;
  --text-sm: 13px;
  --text-md: 14px;
  --text-lg: 16px;
}
```

Do not add `-webkit-font-smoothing` or another forced rasterization mode.

- [ ] **Step 4: Raise every readable market selector**

Within the section beginning at `.market-terminal`, replace every literal `8px`–`11px` font size:

- decorative kickers, timestamps and axis labels use `var(--text-xs)`;
- table cells, badges, controls and descriptions use `var(--text-sm)`;
- watchlist instrument names and panel headings remain `16px` or larger;
- prices remain `15px` or larger;
- key Chinese text uses `var(--font-ui)`;
- `var(--font-data)` is limited to codes, timestamps and numeric cells.

Add:

```css
.market-terminal {
  font-family: var(--font-ui);
}

.numeric-cell,
.market-change,
.index-quote strong,
.market-clock time,
.instrument-quote strong,
.candidate-rank {
  font-family: var(--font-numeric);
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 5: Verify typography and responsive layout**

Run:

```powershell
npm --prefix apps/desktop test -- marketTypography.test.ts OverviewPage.test.tsx
npm --prefix apps/desktop run check
npm --prefix apps/desktop run build
```

Expected: all commands pass. Manually inspect at 1440×900 and 2048×1152; no readable text is
smaller than 12px, and the market grids do not overflow.

- [ ] **Step 6: Commit the typography baseline**

```powershell
git add apps/desktop/src/theme/tokens.css apps/desktop/src/styles/app.css apps/desktop/src/styles/marketTypography.test.ts
git commit -m "fix(desktop): 提升高分屏行情字体清晰度"
```

### Task 1: Define canonical realtime quote contracts

**Files:**

- Create: `packages/domain/src/astraquant_domain/live_market.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`
- Create: `tests/domain/test_live_market.py`

- [ ] **Step 1: Write failing contract tests**

Create tests covering timezone awareness, source metadata, previous close, depth and quality:

```python
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from astraquant_domain import LiveQuote, MarketEventQuality, QuoteLevel
from astraquant_domain.identifiers import InstrumentId


def test_live_quote_preserves_real_source_and_previous_close() -> None:
    now = datetime(2026, 8, 5, 2, 30, tzinfo=UTC)
    quote = LiveQuote(
        instrument_id=InstrumentId.parse("000001.SSE"),
        trading_date=date(2026, 8, 5),
        event_time=now,
        received_time=now,
        last_price=Decimal("3560.12"),
        previous_close=Decimal("3540.00"),
        open=Decimal("3544.20"),
        high=Decimal("3565.10"),
        low=Decimal("3538.40"),
        cumulative_volume=Decimal("1200"),
        cumulative_turnover=Decimal("4300000"),
        open_interest=None,
        bid=(),
        ask=(),
        source_id="eastmoney",
        quality=frozenset({MarketEventQuality.NORMAL}),
    )
    assert quote.change_percent == Decimal("0.5681")
    assert quote.source_id == "eastmoney"


def test_quote_rejects_naive_source_times() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        LiveQuote.minimum(
            InstrumentId.parse("000001.SSE"),
            event_time=datetime(2026, 8, 5, 10, 30),
            last_price=Decimal("3560"),
            previous_close=Decimal("3540"),
        )


def test_depth_rejects_invalid_price_and_volume() -> None:
    with pytest.raises(ValueError, match="price"):
        QuoteLevel(price=Decimal("0"), volume=Decimal("1"))
    with pytest.raises(ValueError, match="volume"):
        QuoteLevel(price=Decimal("1"), volume=Decimal("-1"))
```

- [ ] **Step 2: Verify the missing contracts**

Run:

```powershell
uv run pytest tests/domain/test_live_market.py -v
```

Expected: collection fails because `LiveQuote`, `MarketEventQuality` and `QuoteLevel` do not exist.

- [ ] **Step 3: Implement immutable contracts**

Create:

```python
class MarketEventQuality(StrEnum):
    NORMAL = "NORMAL"
    DELAYED = "DELAYED"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    CLOCK_SKEW = "CLOCK_SKEW"


@dataclass(frozen=True, slots=True)
class QuoteLevel:
    price: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class LiveQuote:
    instrument_id: InstrumentId
    trading_date: date
    event_time: datetime
    received_time: datetime
    last_price: Decimal
    previous_close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    cumulative_volume: Decimal
    cumulative_turnover: Decimal | None
    open_interest: Decimal | None
    bid: tuple[QuoteLevel, ...]
    ask: tuple[QuoteLevel, ...]
    source_id: str
    quality: frozenset[MarketEventQuality]

    @property
    def change(self) -> Decimal:
        return self.last_price - self.previous_close

    @property
    def change_percent(self) -> Decimal:
        if self.previous_close == 0:
            return Decimal("0")
        return (self.change / self.previous_close * 100).quantize(Decimal("0.0001"))
```

Add complete `__post_init__` validation for aware times, positive prices, non-negative volumes,
non-empty source and at most ten bid/ask levels. Add a `minimum` classmethod used by tests. Export
the contracts through `astraquant_domain.__init__`.

- [ ] **Step 4: Verify domain compatibility**

Run:

```powershell
uv run pytest tests/domain/test_live_market.py tests/domain/test_market_data.py -v
uv run mypy packages/domain/src tests/domain
uv run ruff check packages/domain tests/domain
```

Expected: all commands pass.

- [ ] **Step 5: Commit the domain contracts**

```powershell
git add packages/domain/src/astraquant_domain tests/domain/test_live_market.py
git commit -m "feat(domain): 定义真实行情快照契约"
```

### Task 2: Build and test the external Eastmoney SDK bridge

**Files:**

- Create: `packages/data/src/astraquant_data/eastmoney_protocol.py`
- Create: `packages/data/src/astraquant_data/eastmoney_client.py`
- Create: `tools/eastmoney_bridge.py`
- Create: `tests/fixtures/eastmoney/fake_bridge.py`
- Create: `tests/data/test_eastmoney_protocol.py`
- Create: `tests/data/test_eastmoney_client.py`

- [ ] **Step 1: Write failing symbol and payload mapping tests**

Test exact venue conversion and a representative Eastmoney Tick:

```python
from astraquant_data.eastmoney_protocol import (
    from_eastmoney_symbol,
    map_current_quote,
    to_eastmoney_symbol,
)
from astraquant_domain import InstrumentId


def test_maps_exchange_codes_without_guessing() -> None:
    assert to_eastmoney_symbol(InstrumentId.parse("000001.SSE")) == "SHSE.000001"
    assert to_eastmoney_symbol(InstrumentId.parse("399001.SZSE")) == "SZSE.399001"
    assert from_eastmoney_symbol("CFFEX.IF2608") == InstrumentId.parse("IF2608.CFFEX")


def test_maps_current_snapshot_to_a_real_source_quote() -> None:
    quote = map_current_quote(
        {
            "symbol": "SHSE.000001",
            "price": 3560.12,
            "pre_close": 3540.0,
            "open": 3544.2,
            "high": 3565.1,
            "low": 3538.4,
            "cum_volume": 1200,
            "cum_amount": 4300000.0,
            "cum_position": 0,
            "created_at": "2026-08-05T10:30:03+08:00",
            "quotes": [],
        }
    )
    assert str(quote.instrument_id) == "000001.SSE"
    assert quote.source_id == "eastmoney"
```

- [ ] **Step 2: Write the failing subprocess lifecycle test**

The fake bridge reads NDJSON commands and returns deterministic responses without importing `gm`:

```python
def test_bridge_client_never_places_token_on_the_command_line(
    tmp_path: Path,
) -> None:
    client = EastmoneyBridgeClient(
        python_executable=Path(sys.executable),
        bridge_script=Path("tests/fixtures/eastmoney/fake_bridge.py"),
        timeout_seconds=2,
    )
    client.start()
    try:
        client.configure(token="secret-token")
        quotes = client.current(["SHSE.000001"])
        assert quotes[0]["symbol"] == "SHSE.000001"
        assert "secret-token" not in " ".join(client.command)
    finally:
        client.stop()
```

Also test timeout, child exit, malformed JSON and id mismatch.

- [ ] **Step 3: Verify both test modules fail**

Run:

```powershell
uv run pytest tests/data/test_eastmoney_protocol.py tests/data/test_eastmoney_client.py -v
```

Expected: collection fails for the missing protocol/client modules.

- [ ] **Step 4: Implement the self-contained bridge protocol**

`tools/eastmoney_bridge.py` must import only the standard library and `gm.api`. It accepts these
commands:

```json
{"id":"1","method":"configure","params":{"token":"..."}}
{"id":"2","method":"current","params":{"symbols":["SHSE.000001"]}}
{"id":"3","method":"history_n","params":{"symbol":"SHSE.000001","frequency":"60s","count":240}}
{"id":"4","method":"symbol_infos","params":{"symbols":["SHSE.000001"]}}
{"id":"5","method":"trading_dates","params":{"exchange":"SHSE","start_date":"2026-08-05","end_date":"2026-08-05"}}
{"id":"6","method":"shutdown","params":{}}
```

Use `contextlib.redirect_stdout(sys.stderr)` around `gm` import and calls, write protocol responses
only to `sys.__stdout__`, recursively convert datetimes/Decimals/dataframes to JSON-safe values,
and return:

```json
{"id":"2","ok":true,"result":[]}
{"id":"2","ok":false,"error":{"code":"gm_call_failed","message":"sanitized message"}}
```

Never include the token, account data, local environment or traceback in a response.

- [ ] **Step 5: Implement the supervised client**

`EastmoneyBridgeClient` launches:

```python
[
    str(python_executable),
    "-I",
    "-u",
    str(bridge_script),
]
```

It sends the token only in the first stdin request, assigns monotonically increasing request IDs,
uses a dedicated stderr log with token redaction, enforces one in-flight request with a lock, and
terminates the child after a graceful `shutdown` timeout.

- [ ] **Step 6: Verify bridge tests and import isolation**

Run:

```powershell
uv run pytest tests/data/test_eastmoney_protocol.py tests/data/test_eastmoney_client.py -v
uv run ruff check packages/data tools/eastmoney_bridge.py tests/data
uv run mypy packages/data/src tests/data
uv run python -c "import sys; assert 'gm' not in sys.modules; import astraquant_data.eastmoney_client; assert 'gm' not in sys.modules"
```

Expected: all commands pass; importing AstraQuant data code does not import `gm`.

- [ ] **Step 7: Commit the bridge**

```powershell
git add packages/data/src/astraquant_data tools/eastmoney_bridge.py tests/data tests/fixtures/eastmoney
git commit -m "feat(data): 建立东财 SDK 隔离桥接"
```

### Task 3: Add secure configuration and credential storage

**Files:**

- Modify: `packages/api/pyproject.toml`
- Modify: `uv.lock`
- Create: `packages/api/src/astraquant_api/secret_store.py`
- Create: `packages/api/src/astraquant_api/market_config.py`
- Create: `tests/api/test_secret_store.py`
- Create: `tests/api/test_market_config.py`

- [ ] **Step 1: Add the credential-store dependency**

Add:

```toml
"keyring>=25.7,<26",
```

to `astraquant-api` dependencies, then run:

```powershell
uv lock
uv sync --locked --all-packages
```

Expected: `uv.lock` records `keyring` and its Windows support dependencies.

- [ ] **Step 2: Write failing secret-store tests**

Define a protocol with exact Eastmoney methods:

```python
class SecretStore(Protocol):
    def get_eastmoney_token(self) -> str | None: ...
    def set_eastmoney_token(self, token: str) -> None: ...
    def delete_eastmoney_token(self) -> None: ...
```

Tests must prove blank/short values are rejected, reads do not expose service metadata, and a fake
backend can round-trip a token.

- [ ] **Step 3: Implement Windows Credential Manager storage**

Use service `com.xiaogans1.astraquant/eastmoney` and account `market-data-token` through `keyring`.
Import `keyring` lazily inside the concrete class so tests and unsupported platforms can use
`MemorySecretStore`. Convert backend failures to `SecretStoreUnavailable` without including the
secret value.

- [ ] **Step 4: Write and implement market configuration tests**

`EastmoneyRuntimeConfig` contains:

```python
@dataclass(frozen=True, slots=True)
class EastmoneyRuntimeConfig:
    sdk_python: Path | None
    poll_interval_seconds: float = 3.0
    stale_after_seconds: float = 10.0
    request_timeout_seconds: float = 8.0
    maximum_instruments: int = 50
```

Resolution order for `sdk_python` is:

1. `ASTRAQUANT_EASTMONEY_PYTHON` when it points to a file;
2. the non-secret path stored under repository setting `market.eastmoney`;
3. `None`.

Reject poll intervals below 1 second, stale thresholds not greater than the poll interval, and any
maximum other than 50 for the current free provider.

- [ ] **Step 5: Verify and commit secure configuration**

Run:

```powershell
uv run pytest tests/api/test_secret_store.py tests/api/test_market_config.py -v
uv run ruff check packages/api tests/api
uv run mypy packages/api/src tests/api
```

Expected: all commands pass.

```powershell
git add packages/api/pyproject.toml packages/api/src/astraquant_api tests/api uv.lock
git commit -m "feat(api): 安全保存东财行情配置"
```

### Task 4: Implement the 50-slot Eastmoney provider and market service

**Files:**

- Create: `packages/data/src/astraquant_data/live_providers.py`
- Create: `packages/data/src/astraquant_data/subscriptions.py`
- Create: `packages/data/src/astraquant_data/adapters/eastmoney.py`
- Modify: `packages/data/src/astraquant_data/adapters/__init__.py`
- Create: `packages/api/src/astraquant_api/market_service.py`
- Create: `tests/data/test_subscriptions.py`
- Create: `tests/data/test_eastmoney_provider.py`
- Create: `tests/api/test_market_service.py`

- [ ] **Step 1: Write the fixed-core and budget tests**

Define the six immutable core indices:

```python
CORE_INDICES = (
    InstrumentDefinition("000001.SSE", "上证指数", "index", "core"),
    InstrumentDefinition("399001.SZSE", "深证成指", "index", "core"),
    InstrumentDefinition("399006.SZSE", "创业板指", "index", "core"),
    InstrumentDefinition("000688.SSE", "科创50", "index", "core"),
    InstrumentDefinition("000300.SSE", "沪深300", "index", "core"),
    InstrumentDefinition("399852.SZSE", "中证1000", "index", "core"),
)
```

Tests must assert:

- all six are always included;
- at most 34 persistent watchlist instruments and 10 temporary instruments are accepted;
- temporary least-recently-used entries are evicted first;
- duplicate instruments consume one slot;
- core entries cannot be removed;
- a full persistent budget raises `SubscriptionLimitReached` instead of silently dropping data.

- [ ] **Step 2: Write provider polling tests with a fake client**

Use a fake bridge client and a fixed clock to prove:

- `connect(token)` configures the bridge once;
- `poll(symbols)` requests one batch of at most 50 symbols;
- the provider maps quotes and ignores an invalid row while incrementing `parse_error_count`;
- `history_n` requests `60s` bars with `count <= 33000`;
- a child failure moves health to `ERROR`;
- no provider method imports or exposes trade/account functions.

- [ ] **Step 3: Implement provider health and capabilities**

Use exact public states:

```python
class ConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    LIVE = "LIVE"
    STALE = "STALE"
    CLOSED = "CLOSED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"
```

`ProviderHealth` includes provider ID, state, connected/last-event timestamps, sanitized error code,
instrument count, parse error count and reconnect count. It contains no credentials or local
account fields.

- [ ] **Step 4: Write the market-service lifecycle tests**

Test this scenario:

```python
async def scenario() -> None:
    service = MarketDataService(
        provider=fake_provider,
        budget=SubscriptionBudget(),
        secret_store=MemorySecretStore("token-value"),
        poll_interval_seconds=0.01,
        stale_after_seconds=0.05,
    )
    await service.start()
    await service.wait_for_quotes(6, timeout_seconds=1)
    home = service.home_snapshot()
    assert [item.instrument_id for item in home.core_indices] == [
        "000001.SSE",
        "399001.SZSE",
        "399006.SZSE",
        "000688.SSE",
        "000300.SSE",
        "399852.SZSE",
    ]
    await service.stop()
```

Also test idempotent start/stop, missing token, missing SDK, stale transition, closed-session
classification using `get_trading_dates`, reconnection backoff capped at 30 seconds, watchlist
updates taking effect on the next poll, and no unbounded quote/history cache.

- [ ] **Step 5: Implement MarketDataService**

The service owns one polling task and:

- asks `SubscriptionBudget` for the next ordered symbol batch;
- calls `provider.poll` through `asyncio.to_thread`;
- stores only the latest quote per instrument;
- caches a maximum of 240 one-minute bars per selected instrument;
- queries the trading calendar once per local date;
- classifies `LIVE` only when a current trading-day event arrives within the stale threshold;
- classifies `CLOSED` outside the returned trading session while retaining the last real snapshot;
- pauses new quant/AI outputs whenever state is not `LIVE`;
- records sanitized activity without price payloads or tokens.

- [ ] **Step 6: Verify provider/service behavior**

Run:

```powershell
uv run pytest tests/data/test_subscriptions.py tests/data/test_eastmoney_provider.py tests/api/test_market_service.py -v
uv run ruff check packages/data packages/api tests/data tests/api
uv run mypy packages/data/src packages/api/src tests/data tests/api
```

Expected: all commands pass and no test starts the real Eastmoney SDK.

- [ ] **Step 7: Commit provider and service**

```powershell
git add packages/data/src/astraquant_data packages/api/src/astraquant_api/market_service.py tests/data tests/api/test_market_service.py
git commit -m "feat(market): 管理东财实时行情与订阅配额"
```

### Task 5: Publish authenticated market APIs

**Files:**

- Create: `packages/api/src/astraquant_api/market_schemas.py`
- Create: `packages/api/src/astraquant_api/market_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Modify: `packages/api/src/astraquant_api/cli.py`
- Create: `tests/api/test_market_routes.py`
- Modify: `tests/api/test_app.py`
- Modify: `tests/api/test_cli.py`

- [ ] **Step 1: Write failing route tests**

Test authenticated access to:

```text
GET    /v1/market/connection
PUT    /v1/market/eastmoney/config
POST   /v1/market/connection/start
POST   /v1/market/connection/stop
GET    /v1/market/home
GET    /v1/market/instruments/search?q=510300
GET    /v1/market/instruments/{instrument_id}/intraday?count=240
POST   /v1/market/watchlist
DELETE /v1/market/watchlist/{instrument_id}
```

Representative assertions:

```python
response = client.get("/v1/market/home", headers=auth)
assert response.status_code == 200
body = response.json()
assert len(body["core_indices"]) == 6
assert body["breadth"] == {
    "status": "UNAVAILABLE",
    "reason": "当前东财免费行情不提供全市场宽度",
}
assert body["intelligence"]["status"] == "UNAVAILABLE"
assert body["candidates"] == []
assert "token" not in json.dumps(body).lower()
```

Test all routes return `401` without the local bearer token. Test the config response contains
`token_configured: true` but never the token. Test invalid instrument IDs, continuous futures,
count above 240 and the 51st subscription return stable 4xx problems.

- [ ] **Step 2: Define strict response schemas**

`MarketHomeResponse` contains:

```python
class MarketHomeResponse(BaseModel):
    connection: MarketConnectionResponse
    core_indices: list[QuoteCardResponse]
    watchlist: list[QuoteCardResponse]
    selected_instrument: InstrumentDetailResponse | None
    breadth: UnavailableFeatureResponse
    intelligence: UnavailableFeatureResponse
    candidates: list[QuantCandidateResponse]
    as_of: datetime | None
```

`QuoteCardResponse` uses decimal strings for all prices and percentages and includes
`instrument_id`, `name`, `kind`, `state`, `event_time`, `last_price`,
`change`, `change_percent`, `turnover` and `source_id`. Missing real values are JSON `null`,
never zero.

- [ ] **Step 3: Implement configuration without secret leakage**

`PUT /v1/market/eastmoney/config` accepts:

```json
{
  "sdk_python_path": "D:\\AstraQuantData\\Eastmoney\\PythonSDK\\Scripts\\python.exe",
  "token": "user-entered-token"
}
```

Validate the path by running `python -I -c "import gm"` with an eight-second timeout before saving
the non-secret path. Save the token through `SecretStore`. Redact the request body from structured
activity and error logs.

- [ ] **Step 4: Wire service lifecycle into the local runtime**

Add `market_service: MarketDataService` to `AppState`. Build the service in `cli.py` and stop it
before database disposal. The API starts in `UNAVAILABLE` when configuration is absent; runtime
startup must still succeed so the user can open Settings and configure Eastmoney.

Do not auto-start the provider until a valid SDK path and stored token both exist.

- [ ] **Step 5: Verify route and runtime regressions**

Run:

```powershell
uv run pytest tests/api/test_market_routes.py tests/api/test_app.py tests/api/test_cli.py -v
uv run pytest tests/integration/test_runtime_round_trip.py -v
uv run ruff check packages/api tests/api
uv run mypy packages/api/src tests/api
```

Expected: all commands pass; runtime starts even when Eastmoney is not configured.

- [ ] **Step 6: Commit local market APIs**

```powershell
git add packages/api/src/astraquant_api tests/api
git commit -m "feat(api): 发布真实行情本地接口"
```

### Task 6: Replace the production fake homepage

**Files:**

- Create: `apps/desktop/src/api/market-contracts.ts`
- Modify: `apps/desktop/src/api/client.ts`
- Modify: `apps/desktop/src/api/client.test.ts`
- Modify: `apps/desktop/src/api/queries.ts`
- Create: `apps/desktop/src/components/MarketConnectionPanel.tsx`
- Create: `apps/desktop/src/components/MarketConnectionPanel.test.tsx`
- Modify: `apps/desktop/src/pages/OverviewPage.tsx`
- Modify: `apps/desktop/src/pages/OverviewPage.test.tsx`
- Modify: `apps/desktop/src/App.tsx`
- Modify: `apps/desktop/src/App.test.tsx`
- Delete: `apps/desktop/src/features/market/developmentMarket.ts`
- Delete: `apps/desktop/src/features/market/developmentMarket.test.ts`
- Modify: `apps/desktop/src/features/market/types.ts`
- Modify: `apps/desktop/src/styles/app.css`

- [ ] **Step 1: Write API-client and connection-panel tests**

Add exact client methods:

```ts
getMarketConnection(): Promise<MarketConnection>
configureEastmoney(request: EastmoneyConfigRequest): Promise<EastmoneyConfigStatus>
startMarketConnection(): Promise<MarketConnection>
stopMarketConnection(): Promise<MarketConnection>
getMarketHome(): Promise<MarketHome>
searchMarketInstruments(query: string): Promise<InstrumentSearchResult[]>
getMarketIntraday(instrumentId: string, count?: number): Promise<IntradayBar[]>
addWatchlistInstrument(instrumentId: string): Promise<MarketHome>
removeWatchlistInstrument(instrumentId: string): Promise<MarketHome>
```

The panel tests must cover SDK missing, token missing, connecting, live, stale, closed and error
states. Assert that token inputs use `type="password"` and returned status never renders a token.

- [ ] **Step 2: Write the new OverviewPage tests before changing implementation**

Render explicit fixtures rather than module-level fake data:

```tsx
it("renders six real core indices from the local API", () => {
  renderMarketHome({ home: liveHomeFixture });
  expect(screen.getAllByTestId("core-index")).toHaveLength(6);
  expect(screen.getByText("东财掘金实时行情")).toBeVisible();
  expect(screen.queryByText(/模拟行情|模拟盘口|全市场扫描/)).not.toBeInTheDocument();
});

it("never invents numbers when Eastmoney is unavailable", () => {
  renderMarketHome({ home: unavailableHomeFixture });
  expect(screen.getByText("尚未连接东财行情")).toBeVisible();
  expect(screen.queryByText("3,421.68")).not.toBeInTheDocument();
  expect(screen.getByText("当前数据源不支持全市场宽度")).toBeVisible();
});

it("marks cached real data as stale instead of realtime", () => {
  renderMarketHome({ home: staleHomeFixture });
  expect(screen.getByText("行情已延迟")).toBeVisible();
  expect(screen.getByText("最后真实快照")).toBeVisible();
});
```

Also test closed-market copy, loading skeletons without numeric text, API errors, real intraday bars,
backend search, watchlist add/remove and continuous-future rejection.

- [ ] **Step 3: Verify the current homepage fails the new contract**

Run:

```powershell
npm --prefix apps/desktop test -- OverviewPage.test.tsx MarketConnectionPanel.test.tsx client.test.ts
```

Expected: tests fail because market API contracts and connection panel do not exist and the page
still renders hard-coded simulation.

- [ ] **Step 4: Implement React Query market state**

Add query keys:

```ts
marketConnection: ["market", "connection"] as const,
marketHome: ["market", "home"] as const,
marketIntraday: (instrumentId: string) => ["market", "intraday", instrumentId] as const,
marketSearch: (query: string) => ["market", "search", query] as const,
```

Poll connection/home every three seconds only while state is `LIVE`, `CONNECTING` or `STALE`;
poll every 30 seconds while `CLOSED`; do not poll while `UNAVAILABLE` or `ERROR` until the user
retries. Debounce search by 300ms and require at least two characters.

- [ ] **Step 5: Rebuild OverviewPage from API state**

Change `OverviewPage` to accept `client: ApiClient` and use the market queries. Render:

- all six core index slots in the fixed order;
- real values only when supplied;
- “暂无真实数据” for `null` values;
- watchlist from the API, not local component state;
- real 60-second bars for the selected instrument;
- real depth only when Eastmoney supplies it, otherwise “当前快照无盘口数据”;
- breadth as unavailable;
- AI intelligence as unavailable;
- quant candidates as an empty-state explanation;
- source name, state and exact last event time.

Delete `developmentMarket.ts` and its test. Retain only presentation types that match the API
contract; do not keep hidden fake values for visual fallback.

- [ ] **Step 6: Add Eastmoney configuration UI**

Place `MarketConnectionPanel` at the top of “数据与连接” and in a compact homepage state banner.
The form collects SDK Python path and token, explains that the token is saved to Windows Credential
Manager, submits once, clears the token field after success and never stores it in React Query
cache.

- [ ] **Step 7: Verify frontend behavior**

Run:

```powershell
npm --prefix apps/desktop test
npm --prefix apps/desktop run check
npm --prefix apps/desktop run build
rg -n "developmentMarket|开发模拟行情|模拟盘口|全市场扫描 · 模拟|3,421.68" apps/desktop/src
```

Expected: tests/check/build pass; `rg` returns no matches.

- [ ] **Step 8: Commit the real homepage**

```powershell
git add apps/desktop/src
git commit -m "feat(desktop): 用东财真实行情重建首页"
```

### Task 7: Harden repository safety and create the real-session probe

**Files:**

- Create: `tools/eastmoney_probe.py`
- Modify: `tools/repository_policy.py`
- Modify: `tests/repository/test_repository_policy.py`
- Create: `tests/repository/test_eastmoney_probe.py`
- Create: `docs/operations/eastmoney-market-data.md`
- Create: `docs/research/eastmoney-realtime-acceptance.md`
- Modify: `README.md`
- Modify: `docs/roadmap/product-roadmap.md`

- [ ] **Step 1: Add failing repository-policy tests**

Reject:

```text
eastmoney-token.txt
eastmoney-quotes.json
eastmoney-ticks.jsonl
gm-current-dump.json
.astraquant/market/
data/eastmoney/
```

Allow source code, aggregate acceptance Markdown and tiny sanitized fixtures. Add content scanning
for `ASTRAQUANT_EASTMONEY_TOKEN=` and common token JSON keys outside `.env.example`.

- [ ] **Step 2: Implement an aggregate-only probe**

The probe reads SDK path from non-secret config and token from `SecretStore`. It accepts
`--seconds` from 15 to 300 and requests only the six core indices. It prints and optionally writes:

```json
{
  "provider_id": "eastmoney",
  "started_at": "ISO-8601",
  "ended_at": "ISO-8601",
  "requested_instrument_count": 6,
  "received_instrument_count": 0,
  "poll_count": 0,
  "successful_poll_count": 0,
  "first_event_at": null,
  "last_event_at": null,
  "median_age_ms": null,
  "maximum_age_ms": null,
  "parse_error_count": 0,
  "reconnect_count": 0,
  "result": "NO_DATA"
}
```

It must not write symbols, prices, raw quote payloads, token values or local account identifiers.
Exit codes: `0` valid real events, `2` configuration unavailable, `3` completed without current
events, `4` provider/protocol failure.

- [ ] **Step 3: Write operations documentation**

Document:

1. start Eastmoney terminal and log into the simulation environment;
2. find the Token under terminal system settings/key management;
3. open AstraQuant “数据与连接”;
4. enter the verified SDK Python path and Token;
5. connect and check six core indices;
6. understand `LIVE`, `STALE`, `CLOSED` and `UNAVAILABLE`;
7. run the aggregate probe;
8. troubleshoot terminal-not-running, invalid token, missing `gm` and after-hours no-push cases.

Do not include the user's actual token, test account, password or screenshots containing them.

- [ ] **Step 4: Create the acceptance record**

Use `NOT_RUN` as the initial result and fixed rows for test date/session, terminal version, SDK
version, six-index coverage, update cadence, median/maximum event age, 30-minute stability,
disconnect detection, reconnect recovery, parse errors and repository secret scan.

- [ ] **Step 5: Verify safety and docs**

Run:

```powershell
uv run pytest tests/repository/test_repository_policy.py tests/repository/test_eastmoney_probe.py -v
uv run python -m tools.repository_policy
git diff --check
```

Expected: all commands pass and the acceptance record remains `NOT_RUN` until a real session.

- [ ] **Step 6: Commit safety and operations**

```powershell
git add tools tests/repository docs/operations docs/research README.md docs/roadmap/product-roadmap.md
git commit -m "docs(market): 建立东财实时行情验收流程"
```

### Task 8: Run complete verification and publish Phase 3A

**Files:**

- Modify: `docs/superpowers/plans/2026-08-05-phase-3a-eastmoney-realtime-market.md`
- Modify after real session: `docs/research/eastmoney-realtime-acceptance.md`

- [ ] **Step 1: Run the full automated quality gate**

```powershell
uv run ruff format --check packages tools tests
uv run ruff check packages tools tests
uv run mypy
uv run pytest
uv run python -m tools.repository_policy
npm --prefix apps/desktop test
npm --prefix apps/desktop run check
npm --prefix apps/desktop run build
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Expected: every command passes.

- [ ] **Step 2: Run the after-hours truthfulness check**

Start Eastmoney and AstraQuant after market close:

```powershell
.\start.ps1
```

Expected: the app shows a last real snapshot marked `CLOSED` when available, or “暂无真实数据”;
it never displays the old hard-coded values or claims `LIVE`.

- [ ] **Step 3: Run the real-session acceptance**

During an A-share trading session:

```powershell
uv run python -m tools.eastmoney_probe --seconds 60
```

Then run AstraQuant for at least 30 minutes, compare all six core index values/timestamps against
the Eastmoney terminal, disconnect the terminal once, reconnect it, and record aggregate results.

Expected: six-index coverage, approximately three-second quote cadence, timely `STALE` transition,
successful recovery, zero secret leakage and no fake fallback.

- [ ] **Step 4: Record exact evidence**

Mark completed plan checkboxes, append command outcomes and commit SHAs, and update the acceptance
record from `NOT_RUN` to `PASSED` only when the real-session criteria pass. If the market is closed
or the terminal returns no events, keep `NOT_RUN` or record `FAILED` with a sanitized reason.

- [ ] **Step 5: Commit the execution record**

```powershell
git add docs/superpowers/plans/2026-08-05-phase-3a-eastmoney-realtime-market.md docs/research/eastmoney-realtime-acceptance.md
git commit -m "docs(market): 记录东财实时行情实施结果"
```

- [ ] **Step 6: Push the existing branch and keep the PR draft**

```powershell
git push origin feature/phase-1-desktop-platform
gh pr view 4 --json url,headRefOid,statusCheckRollup
```

Expected: PR #4 head matches local `HEAD`. Do not merge automatically.

## Execution checkpoints

- After Task 0: user confirms text is visibly clearer at the current Windows scaling.
- After Task 2: the external bridge passes without importing `gm` into the AstraQuant process.
- After Task 3: the Token round-trips through the credential abstraction and never appears in logs.
- After Task 5: inspect every market JSON response for explicit source/state and absent secrets.
- After Task 6: repository search proves production fake market values and simulation labels are gone.
- After Task 7: the probe can run without persisting raw quotes.
- After Task 8: Phase 3A remains incomplete until the real-session acceptance record passes.

## Later independent plans

- Phase 3B: Alpaca US premarket/regular/after-hours provider and global-night workspace.
- Phase 3C: versioned global industry/theme baskets and contribution analysis.
- Phase 3D: DeepSeek evidence synthesis and overseas-to-A-share observation plans.

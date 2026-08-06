# Professional Market Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary intraday SVG with a broker-style, full-width KLineChart workspace backed by correct Eastmoney reference prices and real multi-period bars.

**Architecture:** Keep Eastmoney SDK access isolated behind the existing NDJSON bridge. Extend the provider and API with a strict period-aware bar contract and deterministic daily-bar aggregation, then wrap `klinecharts@10.0.2` behind focused React components. Missing reference data remains null; chart signals are independent overlays and are never synthesized.

**Tech Stack:** Python 3.12, Eastmoney `gm`, FastAPI/Pydantic, React 19, TypeScript 7, TanStack Query, KLineChart 10.0.2, Vitest, Tauri 2, uv, pnpm.

## Execution status

Completed on 2026-08-06:

- Truthful nullable previous-close and change semantics, enriched from the latest completed real daily bar.
- Strict real multi-period data contract for intraday, 1/5/15/30/60 minute, day, week, month and year.
- Authenticated period-aware API with bounded cache and the legacy intraday compatibility route.
- KLineChart 10.0.2 integration, AstraQuant chart theme, volume/technical indicators and future signal-overlay boundary.
- Full-width broker-style workspace with quote summary, hierarchical period controls, full-screen mode and fixed A-share session landmarks.
- Old narrow hand-written SVG chart removed from the homepage.

Verification evidence:

```text
Python:   246 passed
Ruff:     All checks passed
Mypy:     Success: no issues found in 52 source files
Frontend: 49 passed
TypeScript: no errors
Vite:     production build succeeded
Rust:     cargo check succeeded
```

---

## File map

| Path | Responsibility |
| --- | --- |
| `packages/domain/src/astraquant_domain/live_market.py` | Nullable reference price and truthful change calculations |
| `packages/data/src/astraquant_data/eastmoney_protocol.py` | Map snapshots without inventing previous close |
| `packages/data/src/astraquant_data/live_providers.py` | Period-aware bar provider protocol |
| `packages/data/src/astraquant_data/adapters/eastmoney.py` | Eastmoney period mapping and daily reference cache |
| `packages/data/src/astraquant_data/market_bars.py` | Strict bar normalization and weekly/monthly/yearly aggregation |
| `packages/api/src/astraquant_api/market_service.py` | Bounded period-bar service cache |
| `packages/api/src/astraquant_api/market_schemas.py` | Public bar and period schemas |
| `packages/api/src/astraquant_api/market_routes.py` | Authenticated `/bars` endpoint and intraday compatibility route |
| `apps/desktop/package.json` | Pin KLineChart 10.0.2 |
| `apps/desktop/src/api/market-contracts.ts` | Market period and strict bar contracts |
| `apps/desktop/src/api/client.ts` | Period bar request |
| `apps/desktop/src/api/queries.ts` | Period-aware query key and refresh policy |
| `apps/desktop/src/features/market/marketChartData.ts` | Sort, deduplicate and convert bars for KLineChart |
| `apps/desktop/src/features/market/marketChartTheme.ts` | AstraQuant KLineChart styles |
| `apps/desktop/src/features/market/marketSignalOverlay.ts` | Empty-by-default future quant signal contract |
| `apps/desktop/src/components/MarketChartToolbar.tsx` | Primary periods, minute menu, indicators and fullscreen |
| `apps/desktop/src/components/ProfessionalMarketChart.tsx` | KLineChart lifecycle, data and indicators |
| `apps/desktop/src/components/MarketWorkspace.tsx` | Quote summary and large chart composition |
| `apps/desktop/src/pages/OverviewPage.tsx` | Full-width homepage information architecture |
| `apps/desktop/src/styles/app.css` | Large chart, toolbar, menu and responsive layout |

### Task 1: Make previous close and change values truthful

**Files:**

- Modify: `packages/domain/src/astraquant_domain/live_market.py`
- Modify: `packages/data/src/astraquant_data/eastmoney_protocol.py`
- Modify: `packages/data/src/astraquant_data/adapters/eastmoney.py`
- Test: `tests/domain/test_live_market.py`
- Test: `tests/data/test_eastmoney_protocol.py`
- Test: `tests/data/test_eastmoney_provider.py`

- [ ] **Step 1: Write failing nullable-change tests**

Add tests asserting:

```python
quote = LiveQuote.minimum(
    InstrumentId.parse("159516.SZSE"),
    event_time=aware_now,
    last_price=Decimal("0.712"),
    previous_close=None,
)
assert quote.change is None
assert quote.change_percent is None
```

Add a protocol test showing a real-shaped `current()` payload without `pre_close` maps to `None`,
not zero.

- [ ] **Step 2: Run the focused tests and observe RED**

Run:

```powershell
uv run pytest tests/domain/test_live_market.py tests/data/test_eastmoney_protocol.py -v
```

Expected: FAIL because `previous_close` currently requires `Decimal` and change returns zero.

- [ ] **Step 3: Implement nullable reference semantics**

Change:

```python
previous_close: Decimal | None

@property
def change(self) -> Decimal | None:
    if self.previous_close is None:
        return None
    return self.last_price - self.previous_close

@property
def change_percent(self) -> Decimal | None:
    change = self.change
    if self.previous_close in (None, Decimal("0")) or change is None:
        return None
    return (change / self.previous_close * 100).quantize(Decimal("0.0001"))
```

Map missing/blank/zero `pre_close` to `None`.

- [ ] **Step 4: Add a provider reference-close cache test**

Use a fake client where `current()` omits `pre_close` and `history_n(frequency="1d", count=1)`
returns `close=0.701`. Assert the first poll yields `previous_close=0.701`, the percentage is
correct, and a second poll on the same trading date does not call daily history again.

- [ ] **Step 5: Implement bounded daily-reference enrichment**

Maintain an in-memory cache keyed by `(symbol, trading_date)`. For a missing reference, request one
completed daily bar and `dataclasses.replace` the snapshot. If the request fails, preserve `None`.
Clear stale date entries when a new trading date arrives. Never persist raw rows.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
uv run pytest tests/domain/test_live_market.py tests/data/test_eastmoney_protocol.py tests/data/test_eastmoney_provider.py -v
uv run ruff check packages/domain packages/data tests/domain tests/data
uv run mypy packages/domain/src packages/data/src
```

Expected: all pass.

Commit:

```powershell
git add packages/domain packages/data tests/domain tests/data
git commit -m "fix(market): 使用真实昨收计算行情涨幅"
```

### Task 2: Add strict multi-period market bars

**Files:**

- Create: `packages/data/src/astraquant_data/market_bars.py`
- Modify: `packages/data/src/astraquant_data/live_providers.py`
- Modify: `packages/data/src/astraquant_data/adapters/eastmoney.py`
- Test: `tests/data/test_market_bars.py`
- Test: `tests/data/test_eastmoney_provider.py`

- [ ] **Step 1: Write failing period and aggregation tests**

Define supported values:

```python
MarketPeriod.INTRADAY
MarketPeriod.MINUTE_1
MarketPeriod.MINUTE_5
MarketPeriod.MINUTE_15
MarketPeriod.MINUTE_30
MarketPeriod.MINUTE_60
MarketPeriod.DAY
MarketPeriod.WEEK
MarketPeriod.MONTH
MarketPeriod.YEAR
```

Test the exact Eastmoney mapping and weekly/monthly/yearly OHLCV aggregation. Include bars crossing
month and year boundaries, and assert open-first/high-max/low-min/close-last/volume-sum/turnover-sum.

- [ ] **Step 2: Run tests and observe RED**

```powershell
uv run pytest tests/data/test_market_bars.py tests/data/test_eastmoney_provider.py -v
```

Expected: collection fails because `MarketPeriod` and aggregation do not exist.

- [ ] **Step 3: Implement normalization and aggregation**

Create immutable `MarketBar` and `MarketPeriod` contracts. Normalize aware timestamps, numeric
OHLC, non-negative volume/turnover, sort ascending and remove duplicate timestamps. Implement:

```python
def aggregate_daily_bars(
    bars: Sequence[MarketBar],
    period: Literal[MarketPeriod.WEEK, MarketPeriod.MONTH, MarketPeriod.YEAR],
) -> list[MarketBar]:
    ...
```

Use ISO year/week, `(year, month)` and `year` grouping keys.

- [ ] **Step 4: Extend the provider**

Replace the single-purpose `history_n` protocol with:

```python
def bars(
    self,
    instrument_id: InstrumentId,
    *,
    period: MarketPeriod,
    count: int,
) -> list[MarketBar]: ...
```

Map minute/day periods directly; request enough daily inputs for aggregate periods and return the
latest requested aggregate count.

- [ ] **Step 5: Verify and commit**

```powershell
uv run pytest tests/data/test_market_bars.py tests/data/test_eastmoney_provider.py -v
uv run ruff check packages/data tests/data
uv run mypy packages/data/src tests/data
```

Commit:

```powershell
git add packages/data tests/data
git commit -m "feat(market): 增加真实多周期行情数据"
```

### Task 3: Publish the period-aware bars API

**Files:**

- Modify: `packages/api/src/astraquant_api/market_service.py`
- Modify: `packages/api/src/astraquant_api/market_schemas.py`
- Modify: `packages/api/src/astraquant_api/market_routes.py`
- Test: `tests/api/test_market_service.py`
- Test: `tests/api/test_market_routes.py`

- [ ] **Step 1: Write failing service and route tests**

Assert:

```text
GET /v1/market/instruments/159516.SZSE/bars?period=5m&count=300
```

returns strict bars, while unknown periods, count `0`, and count above the documented bound return
`422`. Assert `/intraday` returns the same latest-session data as `period=intraday`.

- [ ] **Step 2: Run tests and observe RED**

```powershell
uv run pytest tests/api/test_market_service.py tests/api/test_market_routes.py -v
```

Expected: 404 for `/bars`.

- [ ] **Step 3: Implement bounded cache and API**

Use a cache key `(instrument_id, period)`. Cache at most the selected instrument's current period
plus four recently used combinations. Each response contains only validated `MarketBarResponse`.
Do not cache arbitrary raw provider dictionaries.

- [ ] **Step 4: Verify and commit**

```powershell
uv run pytest tests/api/test_market_service.py tests/api/test_market_routes.py -v
uv run ruff check packages/api tests/api
uv run mypy packages/api/src tests/api
```

Commit:

```powershell
git add packages/api tests/api
git commit -m "feat(api): 发布多周期行情接口"
```

### Task 4: Add frontend bar contracts and normalization

**Files:**

- Modify: `apps/desktop/package.json`
- Modify: `pnpm-lock.yaml`
- Modify: `apps/desktop/src/api/market-contracts.ts`
- Modify: `apps/desktop/src/api/client.ts`
- Modify: `apps/desktop/src/api/queries.ts`
- Create: `apps/desktop/src/features/market/marketChartData.ts`
- Create: `apps/desktop/src/features/market/marketChartData.test.ts`
- Test: `apps/desktop/src/api/client.test.ts`

- [ ] **Step 1: Write failing client and normalization tests**

Test `getMarketBars(instrumentId, period, count)`, period-aware query keys, ISO-to-millisecond
conversion, invalid OHLC rejection, ascending sorting and duplicate timestamp removal.

- [ ] **Step 2: Run tests and observe RED**

```powershell
pnpm --dir apps/desktop test -- marketChartData.test.ts client.test.ts
```

Expected: missing functions and API method.

- [ ] **Step 3: Pin KLineChart and implement contracts**

```powershell
pnpm --dir apps/desktop add klinecharts@10.0.2 --save-exact
```

Define:

```ts
export type MarketPeriod =
  | "intraday" | "1m" | "5m" | "15m" | "30m" | "60m"
  | "1d" | "1w" | "1mo" | "1y";
```

The normalizer returns the exact numeric `KLineData` fields expected by KLineChart.

- [ ] **Step 4: Verify and commit**

```powershell
pnpm --dir apps/desktop test -- marketChartData.test.ts client.test.ts
pnpm --dir apps/desktop check
```

Commit:

```powershell
git add apps/desktop/package.json pnpm-lock.yaml apps/desktop/src/api apps/desktop/src/features/market
git commit -m "feat(desktop): 接入专业行情图表数据契约"
```

### Task 5: Build the chart toolbar and signal boundary

**Files:**

- Create: `apps/desktop/src/components/MarketChartToolbar.tsx`
- Create: `apps/desktop/src/components/MarketChartToolbar.test.tsx`
- Create: `apps/desktop/src/features/market/marketSignalOverlay.ts`
- Create: `apps/desktop/src/features/market/marketSignalOverlay.test.ts`

- [ ] **Step 1: Write failing interaction tests**

Assert the primary row contains only `分时/日K/周K/月K/年K`; minute choices appear only after
opening `周期`; selecting `5分` changes the button label to `周期：5分`; indicator menu exposes
MA/BOLL/MACD/KDJ/RSI; fullscreen calls the supplied handler.

Assert `toSignalOverlays([])` returns no overlays and BUY/SELL mapping preserves source and time.

- [ ] **Step 2: Run tests and observe RED**

```powershell
pnpm --dir apps/desktop test -- MarketChartToolbar.test.tsx marketSignalOverlay.test.ts
```

- [ ] **Step 3: Implement accessible controls**

Use buttons with `aria-pressed`, `aria-expanded`, keyboard-dismissable menus and stable labels.
Menus close after selection and on Escape. Do not add a charting-library dependency to the toolbar.

- [ ] **Step 4: Verify and commit**

```powershell
pnpm --dir apps/desktop test -- MarketChartToolbar.test.tsx marketSignalOverlay.test.ts
pnpm --dir apps/desktop check
```

Commit:

```powershell
git add apps/desktop/src/components apps/desktop/src/features/market
git commit -m "feat(desktop): 增加分层周期与指标控制"
```

### Task 6: Integrate KLineChart and the full-width market workspace

**Files:**

- Create: `apps/desktop/src/features/market/marketChartTheme.ts`
- Create: `apps/desktop/src/components/ProfessionalMarketChart.tsx`
- Create: `apps/desktop/src/components/ProfessionalMarketChart.test.tsx`
- Create: `apps/desktop/src/components/MarketWorkspace.tsx`
- Create: `apps/desktop/src/components/MarketWorkspace.test.tsx`
- Modify: `apps/desktop/src/pages/OverviewPage.tsx`
- Modify: `apps/desktop/src/pages/OverviewPage.test.tsx`
- Modify: `apps/desktop/src/styles/app.css`

- [ ] **Step 1: Write failing lifecycle and layout tests**

Mock `klinecharts.init/dispose`. Assert initialization, symbol/period setup, data loader callback,
VOL creation, MA creation for K periods, area style for intraday, candle style for K periods,
ResizeObserver resize, and disposal on unmount/symbol switch.

Assert the chart workspace appears after the watchlist, has a real quote summary, renders `—` for
missing change, and no longer uses `.market-primary-grid` for side-by-side chart placement.

- [ ] **Step 2: Run tests and observe RED**

```powershell
pnpm --dir apps/desktop test -- ProfessionalMarketChart.test.tsx MarketWorkspace.test.tsx OverviewPage.test.tsx
```

- [ ] **Step 3: Implement the chart wrapper**

Initialize KLineChart in one `useEffect`, set timezone to `Asia/Shanghai`, load normalized bars,
create VOL and the selected indicator, and dispose cleanly. Use `area` candle style in intraday mode
and `candle_solid` elsewhere. Apply red-up/green-down AstraQuant theme tokens.

- [ ] **Step 4: Implement the workspace layout**

Move the chart below the watchlist. Render current price, change, percentage, open/high/low,
previous close, volume, turnover and event time. Normal height is `clamp(430px, 52vh, 620px)`.
Fullscreen uses a fixed inset inside the Tauri content area and a visible close control.

- [ ] **Step 5: Implement truthful session labels**

For A-share/ETF/index intraday, display fixed `09:30`, `11:30/13:00`, `15:00` session landmarks
outside the Canvas and let data stop at its real latest time. Do not stretch a custom SVG line.

- [ ] **Step 6: Verify and commit**

```powershell
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

Commit:

```powershell
git add apps/desktop/src
git commit -m "feat(desktop): 构建全宽专业行情主图"
```

### Task 7: Real-data, visual and repository acceptance

**Files:**

- Modify: `README.md`
- Modify: `docs/roadmap/product-roadmap.md`
- Modify: `docs/research/eastmoney-realtime-acceptance.md`
- Modify: `docs/superpowers/plans/2026-08-06-professional-market-chart.md`

- [ ] **Step 1: Run the complete automated gate**

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
git diff --check
```

- [ ] **Step 2: Perform live Eastmoney comparison**

During the A-share session compare the selected ETF and six core indices with the Eastmoney
terminal. Record only aggregate outcomes:

- current price and previous close match;
- change percentage differs by no more than display rounding;
- event age remains within the existing acceptance threshold;
- each direct period returns real bars;
- weekly/monthly/yearly aggregates match their daily inputs.

- [ ] **Step 3: Perform desktop visual acceptance**

Inspect at 1440×900, 1920×1080 and maximized window:

- chart is below the watchlist and at least 430px high;
- primary periods and minute menu do not overflow;
- current intraday point does not occupy the 15:00 endpoint before close;
- crosshair and tooltips are readable;
- fullscreen enters and exits;
- no fake Level-2 or signal marker appears.

- [ ] **Step 4: Update documentation and commit**

Document KLineChart attribution/license, period behavior and truthful missing-data rules.

```powershell
git add README.md docs
git commit -m "docs(market): 记录专业行情主图验收"
git push origin feature/phase-1-desktop-platform
```

Do not mark the feature complete until both the fresh automated gate and real visual acceptance
have passed.

# Adjusted Bars and Chart Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep historical charts continuous across ETF splits while reducing Eastmoney history calls and preserving the last successful chart through transient failures.

**Architecture:** Historical chart requests use Eastmoney forward adjustment (`ADJUST_PREV`) so the latest price remains aligned with the live snapshot. The bridge and provider expose the adjustment explicitly, while the service caches each instrument/period result with a short TTL and returns cached data on transient provider errors. React Query refreshes bars at a slower period-aware cadence and renders stale cached bars with a warning instead of replacing the chart with an error.

**Tech Stack:** Python 3.12, Eastmoney `gm`, FastAPI, React 19, TypeScript, TanStack Query, Vitest, pytest.

---

### Task 1: Add an explicit forward-adjusted history contract

**Files:**

- Modify: `tools/eastmoney_bridge.py`
- Modify: `packages/data/src/astraquant_data/eastmoney_client.py`
- Modify: `packages/data/src/astraquant_data/adapters/eastmoney.py`
- Test: `tests/data/test_eastmoney_client.py`
- Test: `tests/data/test_eastmoney_provider.py`

- [ ] **Step 1: Write failing tests**

Assert that chart-bar calls pass `adjust=1` through the parent client and isolated bridge, while the protocol still permits `adjust=0` for future raw/audit requests.

- [ ] **Step 2: Verify RED**

Run:

```powershell
uv run pytest tests/data/test_eastmoney_client.py tests/data/test_eastmoney_provider.py -q
```

Expected: failure because `history_n` currently has no adjustment argument.

- [ ] **Step 3: Implement the minimal contract**

Add `adjust: int = 1` to the bridge client protocol and send it in the NDJSON request. Pass the validated integer to `gm.history_n`. Use forward adjustment for all chart periods; this anchors historical prices to the latest date and leaves the current price unchanged.

- [ ] **Step 4: Verify GREEN and commit**

Run the focused tests, Ruff and Mypy, then commit the adjustment contract.

### Task 2: Cache bars and degrade to the last successful result

**Files:**

- Modify: `packages/api/src/astraquant_api/market_service.py`
- Test: `tests/api/test_market_service.py`

- [ ] **Step 1: Write failing cache tests**

Using the mutable test clock, assert two intraday calls within eight seconds produce one provider request. Assert K-line calls within sixty seconds are cached. After cache expiry, make the provider fail and assert the previous successful result is returned.

- [ ] **Step 2: Verify RED**

Run:

```powershell
uv run pytest tests/api/test_market_service.py -q
```

Expected: repeated provider calls and raised transient error.

- [ ] **Step 3: Implement bounded TTL and fallback**

Track fetch time beside the existing five-entry LRU. Use an 8-second TTL for intraday/1-minute data and a 60-second TTL for other periods. On provider failure, return the cached result when present; only propagate the error when no successful result exists.

- [ ] **Step 4: Verify GREEN and commit**

Run focused tests and static checks, then commit the service resilience change.

### Task 3: Keep the chart visible during background refresh failures

**Files:**

- Modify: `apps/desktop/src/api/queries.ts`
- Modify: `apps/desktop/src/components/MarketWorkspace.tsx`
- Modify: `apps/desktop/src/components/MarketWorkspace.test.tsx`
- Modify: `apps/desktop/src/styles/app.css`

- [ ] **Step 1: Write failing UI tests**

Assert cached `MarketBar[]` remain rendered when a background refetch fails and that a compact “行情更新暂时失败，继续显示上次成功数据” warning appears. Assert first-load failures still show the full error state.

- [ ] **Step 2: Verify RED**

Run:

```powershell
pnpm --dir apps/desktop test -- MarketWorkspace.test.tsx --run
```

Expected: current component hides the chart whenever `isError` is true.

- [ ] **Step 3: Implement stale-while-revalidate behavior**

Prefer non-empty `data` over `isError`, add the compact warning, set bar refresh to 10 seconds for intraday and 60 seconds for K periods, and retry transient bar requests twice without clearing successful data.

- [ ] **Step 4: Verify the complete change**

Run:

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy packages
pnpm --dir apps/desktop test -- --run
pnpm --dir apps/desktop exec tsc --noEmit
pnpm --dir apps/desktop build
```

Then restart AstraQuant, visually verify the split no longer creates a discontinuity, and push the branch.

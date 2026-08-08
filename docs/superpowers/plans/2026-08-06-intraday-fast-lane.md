# Intraday Fast Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the selected instrument's intraday price line update from one-second lightweight quotes while retaining ten-second historical-bar reconciliation.

**Architecture:** Keep Eastmoney `history_n` as a slow authoritative source and use the existing batched `current` snapshots as a one-second fast lane. Cache the trading-day lookup by China-local date, expose fresh quotes through the existing market-home endpoint, and project only the latest valid quote into the current intraday minute on the frontend.

**Tech Stack:** Python 3.12, FastAPI, pytest, React 19, TanStack Query, TypeScript, Vitest, KLineChart, Tauri 2.

---

### Task 1: Version and accelerate quote polling

**Files:**
- Modify: `packages/api/src/astraquant_api/market_config.py`
- Test: `tests/api/test_market_config.py`

- [ ] **Step 1: Write failing configuration tests**

Add tests proving that a fresh configuration and legacy schema use one-second polling, while schema version 2 preserves an explicit supported value:

```python
assert load_eastmoney_runtime_config(store).poll_interval_seconds == 1.0
assert load_eastmoney_runtime_config(legacy_store).poll_interval_seconds == 1.0
assert load_eastmoney_runtime_config(versioned_store).poll_interval_seconds == 2.0
```

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
uv run pytest tests/api/test_market_config.py -q
```

Expected: failures showing the current default and legacy value are `3.0`.

- [ ] **Step 3: Implement versioned configuration**

Set the dataclass default to `1.0`, save `"schema_version": 2`, and load the stored polling value only when `schema_version >= 2`; otherwise use the new default.

- [ ] **Step 4: Verify configuration tests**

Run:

```powershell
uv run pytest tests/api/test_market_config.py -q
uv run ruff check packages/api/src/astraquant_api/market_config.py tests/api/test_market_config.py
```

Expected: all tests and Ruff pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/api/src/astraquant_api/market_config.py tests/api/test_market_config.py
git commit -m "perf(market): 将轻量报价轮询升级为一秒"
```

### Task 2: Cache the daily trading-calendar lookup

**Files:**
- Modify: `packages/api/src/astraquant_api/market_service.py`
- Test: `tests/api/test_market_service.py`

- [ ] **Step 1: Write a failing service test**

Start the service with a short poll interval, wait for at least three quote polls, and assert `FakeProvider.trading_dates` was called once for the same China-local date.

```python
await service.start()
await service.wait_for_quotes(expected_count, timeout_seconds=1)
await asyncio.sleep(0.04)
assert provider.poll_count >= 3
assert provider.trading_date_requests == 1
```

- [ ] **Step 2: Verify the test fails**

Run:

```powershell
uv run pytest tests/api/test_market_service.py -k trading_calendar -q
```

Expected: the trading calendar request count is greater than one.

- [ ] **Step 3: Implement the date cache**

Add `_calendar_date` and `_calendar_is_trading_date` fields. Extract an async `_is_trading_date(local_date)` helper that calls the provider only when the local date changes, and use it inside `_poll_loop`.

- [ ] **Step 4: Verify service behavior**

Run:

```powershell
uv run pytest tests/api/test_market_service.py -q
uv run ruff check packages/api/src/astraquant_api/market_service.py tests/api/test_market_service.py
```

Expected: service tests and Ruff pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/api/src/astraquant_api/market_service.py tests/api/test_market_service.py
git commit -m "perf(market): 按交易日缓存行情日历"
```

### Task 3: Project the latest quote into the intraday minute

**Files:**
- Create: `apps/desktop/src/features/market/liveIntraday.ts`
- Create: `apps/desktop/src/features/market/liveIntraday.test.ts`
- Modify: `apps/desktop/src/components/MarketWorkspace.tsx`
- Modify: `apps/desktop/src/components/MarketWorkspace.test.tsx`

- [ ] **Step 1: Write failing projection tests**

Cover same-minute high/low/close updates, a new minute append, invalid price, out-of-session time, and out-of-order snapshots:

```typescript
expect(mergeLiveQuoteIntoIntradayBars(bars, quoteAt("2026-08-06T10:02:20+08:00", "0.715")))
  .toMatchObject([{ close: 0.715 }]);
expect(mergeLiveQuoteIntoIntradayBars(bars, quoteAt("2026-08-06T10:03:01+08:00", "0.716")))
  .toHaveLength(bars.length + 1);
```

- [ ] **Step 2: Verify the projection tests fail**

Run:

```powershell
pnpm --dir apps/desktop test -- liveIntraday.test.ts --run
```

Expected: module/function missing.

- [ ] **Step 3: Implement the pure projection function**

Parse and validate the quote, convert the event time to a China-local trading minute, never mutate input bars, and update or append only the final minute.

- [ ] **Step 4: Verify the projection tests**

Run:

```powershell
pnpm --dir apps/desktop test -- liveIntraday.test.ts --run
```

Expected: all projection cases pass.

- [ ] **Step 5: Write a failing workspace integration test**

Render `MarketWorkspace` with historical bars and a newer quote, then assert `ProfessionalMarketChart` receives a final bar whose close matches the quote. Also assert non-intraday periods receive the original authoritative bars.

- [ ] **Step 6: Verify the integration test fails**

Run:

```powershell
pnpm --dir apps/desktop test -- MarketWorkspace.test.tsx --run
```

Expected: chart still receives the unprojected historical close.

- [ ] **Step 7: Integrate the projection**

Use `useMemo` in `MarketWorkspace`: for `intraday`, pass `mergeLiveQuoteIntoIntradayBars(barsQuery.data, quote)`; for every other period, pass the original data.

- [ ] **Step 8: Verify frontend behavior**

Run:

```powershell
pnpm --dir apps/desktop test -- liveIntraday.test.ts MarketWorkspace.test.tsx --run
pnpm --dir apps/desktop exec tsc --noEmit
```

Expected: focused tests and TypeScript pass.

- [ ] **Step 9: Commit**

```powershell
git add apps/desktop/src/features/market/liveIntraday.ts apps/desktop/src/features/market/liveIntraday.test.ts apps/desktop/src/components/MarketWorkspace.tsx apps/desktop/src/components/MarketWorkspace.test.tsx
git commit -m "feat(desktop): 实时快照增量更新分时当前点"
```

### Task 4: Refresh the market-home snapshot every second

**Files:**
- Modify: `apps/desktop/src/api/queries.ts`
- Create: `apps/desktop/src/api/queries.test.tsx`

- [ ] **Step 1: Write a failing query interval test**

Render the market-home hook with fake timers and assert two memory-API reads occur approximately one second apart while `LIVE`; assert `CLOSED` does not use the one-second interval.

- [ ] **Step 2: Verify the query test fails**

Run:

```powershell
pnpm --dir apps/desktop test -- queries.test.tsx --run
```

Expected: the second live request does not occur until the current three-second interval.

- [ ] **Step 3: Implement a quote-specific refetch interval**

Add `marketQuoteRefetchInterval`: return `1_000` for `LIVE`, `CONNECTING`, and `STALE`, `30_000` for `CLOSED`, and `false` otherwise. Use it only in `useMarketHomeQuery`.

- [ ] **Step 4: Verify query tests**

Run:

```powershell
pnpm --dir apps/desktop test -- queries.test.tsx --run
pnpm --dir apps/desktop exec tsc --noEmit
```

Expected: tests and TypeScript pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/desktop/src/api/queries.ts apps/desktop/src/api/queries.test.tsx
git commit -m "perf(desktop): 每秒读取选中标的实时快照"
```

### Task 5: Full verification and live Eastmoney check

- [ ] **Step 1: Run full verification**

Run:

```powershell
uv run ruff format --check packages tools tests
uv run ruff check packages tools tests
uv run pytest -q
uv run mypy packages
pnpm --dir apps/desktop test -- --run
pnpm --dir apps/desktop exec tsc --noEmit
pnpm --dir apps/desktop build
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Expected: every command exits zero.

- [ ] **Step 2: Restart and inspect the desktop app**

Restart through `D:\AstraQuant\start.ps1`, confirm the Eastmoney connection becomes `LIVE`, verify the selected quote timestamp advances at about one-second cadence, and verify the intraday chart remains visible during historical reconciliation failure.

- [ ] **Step 3: Push and monitor CI**

```powershell
git push
gh pr checks 4 --watch
```

Expected: Frontend, Windows/Linux Python, and Desktop Rust checks all pass.

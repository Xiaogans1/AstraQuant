# Persistent Watchlist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the ordered AstraQuant watchlist in local SQLite and restore it across desktop restarts without persisting prices or secrets.

**Architecture:** A focused `market_watchlist.py` module serializes validated watchlist entries through the existing `SettingsStore` protocol. `MarketDataService` hydrates its existing `SubscriptionBudget` at construction and saves the ordered list after successful add/remove operations; production injects `TaskRepository`.

**Tech Stack:** Python 3.12, SQLAlchemy/SQLite settings repository, FastAPI market service, pytest, Ruff, Mypy.

---

### Task 1: Define and verify the persistent watchlist format

**Files:**
- Create: `packages/api/src/astraquant_api/market_watchlist.py`
- Create: `tests/api/test_market_watchlist.py`

- [ ] **Step 1: Write failing format tests**

Add tests that require `load_watchlist` to preserve valid order and names, remove duplicates, skip malformed
records, and cap restored entries at `SubscriptionBudget.persistent_capacity`. Add a save test requiring the
exact versioned JSON shape and proving no market price or credential fields are stored.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
uv run pytest tests/api/test_market_watchlist.py -q
```

Expected: collection fails because `astraquant_api.market_watchlist` does not exist.

- [ ] **Step 3: Implement the minimal persistence module**

Create an immutable `WatchlistEntry`, `load_watchlist(settings)` and
`save_watchlist(settings, entries)`. Canonicalize IDs with `InstrumentId.parse`, retain the first duplicate,
validate non-empty optional names, and write only `version`, `instrument_id`, and `name`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```powershell
uv run pytest tests/api/test_market_watchlist.py -q
```

Expected: all tests pass.

### Task 2: Restore and update the watchlist in MarketDataService

**Files:**
- Modify: `packages/api/src/astraquant_api/market_service.py`
- Modify: `tests/api/test_market_service.py`

- [ ] **Step 1: Write the restart regression test**

Create an in-memory settings store. Search and add `600000.SSE` in one service instance, construct a second
instance with the same store, and assert that code, name and order are restored. Remove it, construct a third
instance, and assert that it stays deleted.

- [ ] **Step 2: Run the regression test and verify RED**

Run:

```powershell
uv run pytest tests/api/test_market_service.py -q
```

Expected: the reconstructed service has an empty watchlist.

- [ ] **Step 3: Implement hydration and write-through**

Add optional `watchlist_store: SettingsStore | None` constructor injection. Hydrate valid entries into the
existing budget and name cache. After add/remove changes, serialize the current ordered entries. Keep tests and
callers without a store in memory-only mode.

- [ ] **Step 4: Run service tests and verify GREEN**

Run:

```powershell
uv run pytest tests/api/test_market_service.py -q
```

Expected: all tests pass.

### Task 3: Wire production SQLite and prove route persistence

**Files:**
- Modify: `packages/api/src/astraquant_api/cli.py`
- Modify: `tests/api/test_market_routes.py`

- [ ] **Step 1: Write a route-level persistence assertion**

After adding a watchlist item through `/v1/market/watchlist`, assert that
`market_state.repository.get_setting("market.watchlist")` contains the canonical ID and no quote or secret
fields.

- [ ] **Step 2: Run the route test and verify RED**

Run:

```powershell
uv run pytest tests/api/test_market_routes.py -q
```

Expected: the repository setting is absent.

- [ ] **Step 3: Inject the repository**

Pass `repository` as `watchlist_store` when constructing `MarketDataService` in `cli.py` and in the market API
fixture so route mutations use the same SQLite store as production.

- [ ] **Step 4: Run route tests and verify GREEN**

Run:

```powershell
uv run pytest tests/api/test_market_routes.py -q
```

Expected: all tests pass.

### Task 4: Full verification and delivery

**Files:**
- Modify: `packages/api/src/astraquant_api/app.py`
- Modify: `tests/api/test_market_routes.py`
- Modify: `README.md`
- Modify: `docs/roadmap/product-roadmap.md`

- [ ] **Step 1: Verify startup auto-connect with a failing lifespan test**

Use `TestClient` as a context manager and assert that a configured market service transitions away from
`DISCONNECTED` without calling `/connection/start`. Add a service test proving an unavailable terminal produces
`provider_connect_failed` without blocking a later manual retry.

- [ ] **Step 2: Start and stop the market service with the API lifespan**

Add a FastAPI lifespan handler that starts the configured market service before accepting requests and stops it
on shutdown. Catch provider connection failures in `MarketDataService.start`, retain an actionable error state,
and leave the service retryable.

- [ ] **Step 3: Update capability documentation**

State that user watchlists are local, ordered, persistent across restarts, and contain no market prices or
credentials.

- [ ] **Step 4: Run all quality gates**

Run:

```powershell
uv run ruff format --check packages tools tests
uv run ruff check packages tools tests
uv run mypy
uv run pytest
pnpm --dir apps/desktop check
pnpm --dir apps/desktop test
pnpm --dir apps/desktop build
```

Expected: every command exits with code 0.

- [ ] **Step 5: Commit and push**

Commit the spec separately, then commit the implementation with Chinese messages and push the existing feature
branch. Do not merge the Draft PR automatically.

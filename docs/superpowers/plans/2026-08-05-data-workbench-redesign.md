# Data Workbench Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Phase 2 fixture import controls from the production desktop and replace them with an honest real-data warehouse and quality workspace.

**Architecture:** Extend dataset summaries with latest published snapshot provenance, filter development fixtures at the presentation boundary, and keep immutable snapshot inspection intact. Translate local transport failures into actionable restart guidance without weakening authentication or CORS.

**Tech Stack:** React 19, TypeScript, TanStack Query, FastAPI, Pydantic, SQLAlchemy, Vitest, pytest.

---

### Task 1: Prove the stale-runtime and dataset-provenance contracts

**Files:**
- Modify: `tests/api/test_data_routes.py`
- Modify: `apps/desktop/src/api/client.test.ts`
- Modify: `apps/desktop/src/pages/DataPage.test.tsx`

- [ ] **Step 1: Add a failing API test** asserting dataset summaries include latest Provider, row count and coverage timestamps.
- [ ] **Step 2: Add failing frontend tests** asserting `fixture` datasets and sample-import controls are absent while real snapshots remain inspectable.
- [ ] **Step 3: Add a failing error-copy test** asserting a rejected fetch is rendered as restart guidance, never raw `Failed to fetch`.
- [ ] **Step 4: Run focused pytest and Vitest commands** and confirm failures are caused by the missing contract and old page.

### Task 2: Extend the real dataset summary

**Files:**
- Modify: `packages/api/src/astraquant_api/data_schemas.py`
- Modify: `packages/api/src/astraquant_api/data_routes.py`
- Modify: `apps/desktop/src/api/data-contracts.ts`

- [ ] **Step 1: Add nullable latest-snapshot provenance fields** to Python and TypeScript contracts.
- [ ] **Step 2: Populate fields only from the latest visible snapshot** in the authenticated datasets route.
- [ ] **Step 3: Run API tests, Ruff and mypy** and confirm the contract is strict and backwards-safe for empty datasets.
- [ ] **Step 4: Commit** with `feat(data): 发布真实数据集来源摘要`.

### Task 3: Rebuild the production data workspace

**Files:**
- Modify: `apps/desktop/src/pages/DataPage.tsx`
- Modify: `apps/desktop/src/pages/DataPage.test.tsx`
- Modify: `apps/desktop/src/App.tsx`
- Modify: `apps/desktop/src/styles/app.css`

- [ ] **Step 1: Remove import props and fixture form** from `DataPage` and remove the unused import mutation wiring from `App`.
- [ ] **Step 2: Filter non-real datasets** using `latest_provider_id`, including all counts and automatic selection.
- [ ] **Step 3: Build the data-pipeline rail and real warehouse empty state** without a disabled fake action.
- [ ] **Step 4: Preserve snapshot quality and bar preview** for real datasets, with localized Provider and status labels.
- [ ] **Step 5: Run focused tests and TypeScript check** until green.
- [ ] **Step 6: Commit** with `feat(desktop): 重构正式数据工作台`.

### Task 4: Make local transport failures actionable

**Files:**
- Modify: `apps/desktop/src/api/client.ts`
- Modify: `apps/desktop/src/api/client.test.ts`
- Modify: `apps/desktop/src/components/MarketConnectionPanel.tsx`
- Modify: `apps/desktop/src/components/MarketConnectionPanel.test.tsx`
- Modify: `docs/operations/eastmoney-market-data.md`

- [ ] **Step 1: Normalize fetch transport errors** to a typed Chinese local-service error without echoing secrets.
- [ ] **Step 2: Render restart guidance** in the connection panel and keep the Token field masked.
- [ ] **Step 3: Document that Python backend changes require a desktop restart** in development.
- [ ] **Step 4: Restart the current Tauri process** so frontend and backend use the same source revision.
- [ ] **Step 5: Re-run the CORS preflight and configuration flow**; confirm the request reaches SDK/Token validation rather than failing transport.
- [ ] **Step 6: Commit** with `fix(desktop): 提示并恢复本地行情连接`.

### Task 5: Verify, record and publish

**Files:**
- Modify: `docs/superpowers/plans/2026-08-05-data-workbench-redesign.md`

- [ ] **Step 1: Run** `uv run ruff format --check packages tools tests`, `uv run ruff check packages tools tests`, `uv run mypy`, and `uv run pytest`.
- [ ] **Step 2: Run** `npm --prefix apps/desktop test`, `npm --prefix apps/desktop run check`, and `npm --prefix apps/desktop run build`.
- [ ] **Step 3: Scan production source** for `导入本地样例|导入示例数据|provider: "fixture"|Failed to fetch` and require no matches.
- [ ] **Step 4: Visually inspect** the Windows desktop data workspace at 1440×900 and verify honest empty/real states.
- [ ] **Step 5: Update this execution record, commit and push** the existing branch without merging PR #4.

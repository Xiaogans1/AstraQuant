# Market Terminal Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace the engineering-oriented overview with a functional development-mode market terminal home for Chinese stocks, ETFs, and domestic futures.

**Architecture:** Keep the homepage independent from any specific quote vendor by rendering a typed `MarketSnapshot`. A deterministic development snapshot supplies clearly labeled simulated quotes now; Phase 3A will later bind the same UI boundary to authenticated realtime APIs. Local component state handles watchlist selection and session-only additions without inventing persistence or live entitlement.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, existing AstraQuant CSS tokens

---

## File map

- `apps/desktop/src/features/market/types.ts`: vendor-neutral market-view contracts.
- `apps/desktop/src/features/market/developmentMarket.ts`: deterministic, explicitly simulated development snapshot and searchable catalog.
- `apps/desktop/src/features/market/developmentMarket.test.ts`: fixture and search behavior tests.
- `apps/desktop/src/pages/OverviewPage.tsx`: interactive market-terminal composition.
- `apps/desktop/src/pages/OverviewPage.test.tsx`: user-visible terminal, selection and add-to-watchlist tests.
- `apps/desktop/src/components/Sidebar.tsx`: market-first navigation vocabulary.
- `apps/desktop/src/App.tsx`: remove engineering props from overview and give market home its own heading.
- `apps/desktop/src/App.test.tsx`: shell/navigation regression.
- `apps/desktop/src/styles/app.css`: terminal layout, responsive behavior and state styling.
- `docs/superpowers/specs/2026-08-05-market-terminal-home-design.md`: approved product and visual specification.

### Task 1: Define the market view boundary

**Files:**
- Create: `apps/desktop/src/features/market/types.ts`
- Create: `apps/desktop/src/features/market/developmentMarket.ts`
- Test: `apps/desktop/src/features/market/developmentMarket.test.ts`

- [x] **Step 1: Write failing tests for source labeling and catalog search**

Test that the development snapshot has `sourceMode: "simulation"`, contains stock/ETF/future instruments, and `searchMarketCatalog("510300")` returns 沪深300ETF while a blank query returns no results.

- [x] **Step 2: Run the focused test and confirm RED**

Run: `pnpm --dir apps/desktop test -- developmentMarket.test.ts`

Expected: FAIL because `developmentMarket` does not exist.

- [x] **Step 3: Add minimal typed contracts and deterministic data**

Define `InstrumentKind`, `MarketInstrument`, `IndexQuote`, `MarketBreadth`, `SectorMove`, `IntelligenceBrief`, `QuantCandidate`, and `MarketSnapshot`. Export `developmentMarketSnapshot`, `marketCatalog`, and a case-insensitive search by code/name limited to six matches.

- [x] **Step 4: Run the focused test and confirm GREEN**

Run: `pnpm --dir apps/desktop test -- developmentMarket.test.ts`

Expected: all market fixture tests PASS.

- [x] **Step 5: Commit the boundary**

```powershell
git add apps/desktop/src/features/market
git commit -m "feat(desktop): 定义行情首页视图模型"
```

### Task 2: Build the interactive terminal page

**Files:**
- Replace: `apps/desktop/src/pages/OverviewPage.test.tsx`
- Replace: `apps/desktop/src/pages/OverviewPage.tsx`

- [x] **Step 1: Write failing user-behavior tests**

Cover three behaviors: the page exposes “模拟行情” and “只读观察”; selecting 科创50ETF updates the instrument heading; searching `RB` and clicking “添加螺纹主连” adds it to the watchlist.

- [x] **Step 2: Run the focused test and confirm RED**

Run: `pnpm --dir apps/desktop test -- OverviewPage.test.tsx`

Expected: assertions fail against the old engineering overview.

- [x] **Step 3: Implement the minimum interactive composition**

Render the index strip, segmented watchlist filters, accessible search/add results, selectable quote rows, SVG intraday line, market breadth, sector moves, AI intelligence status, quant candidates, and Paper placeholder action. Keep additions in React state and label the source as development simulation.

- [x] **Step 4: Run the focused test and confirm GREEN**

Run: `pnpm --dir apps/desktop test -- OverviewPage.test.tsx`

Expected: all terminal behaviors PASS.

- [x] **Step 5: Commit the page behavior**

```powershell
git add apps/desktop/src/pages/OverviewPage.tsx apps/desktop/src/pages/OverviewPage.test.tsx
git commit -m "feat(desktop): 构建交互式行情首页"
```

### Task 3: Reframe the application shell around markets

**Files:**
- Modify: `apps/desktop/src/components/Sidebar.tsx`
- Modify: `apps/desktop/src/App.tsx`
- Modify: `apps/desktop/src/App.test.tsx`

- [x] **Step 1: Write failing shell assertions**

Expect the active navigation button to be named “市场首页”, keep “数据与连接” enabled, and confirm “智能选股” and “Paper 模拟” are visible but disabled.

- [x] **Step 2: Run the shell test and confirm RED**

Run: `pnpm --dir apps/desktop test -- App.test.tsx`

Expected: FAIL on the old navigation labels.

- [x] **Step 3: Update navigation and overview composition**

Rename the enabled routes without changing route identity, group future product areas in the sidebar, remove obsolete overview task props, and skip the generic page heading only for `overview` because the terminal owns its own compact header.

- [x] **Step 4: Run the shell test and confirm GREEN**

Run: `pnpm --dir apps/desktop test -- App.test.tsx`

Expected: shell tests PASS and existing data navigation remains functional.

- [x] **Step 5: Commit the shell**

```powershell
git add apps/desktop/src/App.tsx apps/desktop/src/App.test.tsx apps/desktop/src/components/Sidebar.tsx
git commit -m "feat(desktop): 将工作区导航调整为行情优先"
```

### Task 4: Apply the approved visual system

**Files:**
- Modify: `apps/desktop/src/styles/app.css`

- [x] **Step 1: Add the terminal layout styles**

Implement `.market-terminal`, `.market-toolbar`, `.index-strip`, `.watchlist-panel`, `.instrument-panel`, `.market-breadth`, `.intelligence-card`, and `.quant-candidates` using existing theme tokens. Use red for up and green for down, tabular data alignment, visible focus, and a single star-track chart signature.

- [x] **Step 2: Add responsive and reduced-motion rules**

At widths below 1100px stack detail below watchlist; below 720px use a single column and horizontal index scrolling. Preserve source/risk labels and disable quote pulse under reduced motion.

- [x] **Step 3: Run TypeScript and component tests**

Run:

```powershell
pnpm --dir apps/desktop check
pnpm --dir apps/desktop test
```

Expected: typecheck and all Vitest suites PASS.

- [x] **Step 4: Commit the visual layer**

```powershell
git add apps/desktop/src/styles/app.css
git commit -m "style(desktop): 完成行情终端首页视觉"
```

### Task 5: Verify the development slice

**Files:**
- Modify: `docs/superpowers/plans/2026-08-05-market-terminal-home.md`

- [x] **Step 1: Build the production frontend**

Run: `pnpm --dir apps/desktop build`

Expected: TypeScript project build and Vite production bundle succeed.

- [x] **Step 2: Start the workspace and inspect the homepage**

Run: `.\start.ps1 -SkipSync`

Confirm the page identifies simulated data, supports selecting and adding instruments, remains usable at 1440px and 720px, and does not expose an order action.

- [x] **Step 3: Record exact verification evidence in this plan**

Append command results and any known limitations under `Execution Record`; do not claim real QMT connectivity.

- [x] **Step 4: Commit documentation and push the existing feature branch**

```powershell
git add docs/superpowers/specs/2026-08-05-market-terminal-home-design.md docs/superpowers/plans/2026-08-05-market-terminal-home.md
git commit -m "docs(desktop): 固化行情终端首页设计"
git push origin feature/phase-1-desktop-platform
```

## Execution Record

- Status: `COMPLETED`
- Realtime provider: `SIMULATION_ONLY`
- QMT real-session acceptance: `NOT_RUN`
- Commits:
  - `9069815 feat(desktop): 定义行情首页视图模型`
  - `696db0b feat(desktop): 构建交互式行情首页`
  - `91a73b9 feat(desktop): 将工作区导航调整为行情优先`
  - `33c8fc8 style(desktop): 完成行情终端首页视觉`
  - `e8204d0 fix(desktop): 优化行情表格首屏宽度`
  - `6aa86df chore: 清理行情首页文档格式`
  - `4d035ee fix(desktop): 收紧模拟行情与情报边界`
- Verification on 2026-08-05:
  - `pnpm --dir apps/desktop check`: PASS
  - `pnpm --dir apps/desktop test`: PASS, 8 files / 22 tests
  - `pnpm --dir apps/desktop build`: PASS, Vite production bundle generated
  - `scripts/dev.ps1 -SkipSync`: PASS, Tauri opened the `AstraQuant` window
  - Desktop visual QA at 1440px: PASS after reducing watchlist minimum width from 700px to 640px
  - Independent code review: all three Important findings fixed before push (searchable future, explicit AI/order-book simulation boundaries, 720px single-column breakpoint)
- Known limitations:
  - Quotes, index values, breadth, AI brief and quant candidates are deterministic development fixtures.
  - Watchlist additions live only for the current React session.
  - Paper, Evidence Room, K-line, capital-flow and signal actions remain visibly disabled.
  - Responsive CSS is implemented at 1180px, 980px and 680px; only the desktop window received screenshot QA in this execution.

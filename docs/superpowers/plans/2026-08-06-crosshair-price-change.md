# 行情十字光标价格涨幅联动 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在所有行情周期的主图十字光标旁同步展示价格与相对昨收涨跌幅。

**Architecture:** 将纯计算提取到独立的 `crosshairQuote.ts`，由 `ProfessionalMarketChart` 订阅 KLineCharts 的 `onCrosshairChange`，通过坐标转换得到自由光标价格，并渲染受边界约束的 HTML 标签。图表数据仍由 KLineCharts 管理，React 只保存轻量的悬浮信息。

**Tech Stack:** React 19、TypeScript、KLineCharts 10、Vitest、Testing Library

---

### Task 1: 十字光标报价计算

**Files:**
- Create: `apps/desktop/src/features/market/crosshairQuote.ts`
- Create: `apps/desktop/src/features/market/crosshairQuote.test.ts`

- [ ] **Step 1: Write the failing tests**

覆盖高于昨收、低于昨收、无效昨收和价格精度，期望得到结构化的 `priceText`、`changeText` 与 `direction`。

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir apps/desktop test -- crosshairQuote.test.ts`

Expected: FAIL because `crosshairQuote.ts` does not exist.

- [ ] **Step 3: Write minimal implementation**

实现：

```ts
export function buildCrosshairQuote(
  price: number,
  previousClose: number | null,
  precision: number,
): CrosshairQuote
```

拒绝非有限价格；有效昨收时按 `(price / previousClose - 1) * 100` 计算，百分比固定两位。

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --dir apps/desktop test -- crosshairQuote.test.ts`

Expected: PASS.

### Task 2: 图表订阅与标签渲染

**Files:**
- Modify: `apps/desktop/src/components/ProfessionalMarketChart.tsx`
- Modify: `apps/desktop/src/components/ProfessionalMarketChart.test.tsx`
- Modify: `apps/desktop/src/features/market/marketChartTheme.ts`
- Modify: `apps/desktop/src/styles/app.css`

- [ ] **Step 1: Write the failing component tests**

模拟 `subscribeAction("onCrosshairChange")`，触发带 `y`、`paneId`、`kLineData` 的事件，验证：

```text
0.7030
+0.72%
```

被同时渲染；无效昨收时不渲染百分比；卸载时调用 `unsubscribeAction`。

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir apps/desktop test -- ProfessionalMarketChart.test.tsx`

Expected: FAIL because the chart has no crosshair quote label.

- [ ] **Step 3: Write minimal implementation**

- `ProfessionalMarketChart` 保存 `bars` 与精度的 ref，避免每秒实时刷新导致重复订阅。
- 使用 `chart.convertFromPixel([{ y }], { paneId })` 得到主图价格。
- 使用光标数据索引对应的 `MarketBar.previous_close` 计算涨跌幅。
- 在主图右侧渲染 `role="status"` 标签，并通过 CSS 约束位置。
- 将原生 `crosshair.horizontal.text.show` 设置为 `false`，防止重复价格标签。

- [ ] **Step 4: Run focused tests**

Run: `pnpm --dir apps/desktop test -- ProfessionalMarketChart.test.tsx crosshairQuote.test.ts`

Expected: PASS.

### Task 3: 全量验证与提交

**Files:**
- Modify: `docs/superpowers/specs/2026-08-06-crosshair-price-change-design.md`
- Modify: `docs/superpowers/plans/2026-08-06-crosshair-price-change.md`

- [ ] **Step 1: Run frontend verification**

```powershell
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

Expected: all commands exit 0.

- [ ] **Step 2: Inspect the diff**

Run: `git diff --check`

Expected: exit 0 with no whitespace errors.

- [ ] **Step 3: Commit**

```powershell
git add apps/desktop/src docs/superpowers
git commit -m "feat(desktop): 十字光标同步显示价格涨幅"
```


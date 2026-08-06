# 行情指标与量化状态前端收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成券商式主图/副图指标、分时累计均价线和可诊断量化状态，使行情前端在进入真正量化开发前达到稳定冻结条件。

**Architecture:** 使用固定 pane ID 管理 KLineCharts 指标，主图指标叠加到 `candle_pane`，副图指标互斥复用 `astraquant_secondary_pane`，量化覆盖物继续使用独立 group。分时累计均价由纯函数计算并注册为自定义 `AVG` 指标；工作区只负责选择状态和查询状态映射。

**Tech Stack:** React 19、TypeScript、KLineCharts 10、TanStack Query、Vitest、Testing Library

---

### Task 1: 指标类型与工具栏信息架构

**Files:**
- Modify: `apps/desktop/src/components/MarketChartToolbar.tsx`
- Modify: `apps/desktop/src/components/MarketChartToolbar.test.tsx`

- [ ] **Step 1: Write the failing toolbar tests**

验证分时只提供 `均价/无` 主图选项，K 线提供 `MA/BOLL/无`；副图独立提供
`VOL/MACD/KDJ/RSI`；量化图层按钮使用 `aria-pressed`。

```tsx
expect(screen.getByRole("button", { name: "主图：均价" })).toBeVisible();
expect(screen.getByRole("button", { name: "副图：VOL" })).toBeVisible();
expect(screen.getByRole("button", { name: "量化图层" })).toHaveAttribute("aria-pressed", "true");
```

- [ ] **Step 2: Run RED**

Run:

```powershell
pnpm --dir apps/desktop exec vitest run src/components/MarketChartToolbar.test.tsx
```

Expected: FAIL because the toolbar exposes one mixed indicator menu.

- [ ] **Step 3: Implement explicit indicator types**

```ts
export type MainChartIndicator = "AVG" | "MA" | "BOLL" | "NONE";
export type SecondaryChartIndicator = "VOL" | "MACD" | "KDJ" | "RSI";
```

新增 `showQuantSignals`、`onMainIndicatorChange`、`onSecondaryIndicatorChange` 和
`onToggleQuantSignals` props。分时主图菜单渲染 `AVG/NONE`，其他周期渲染
`MA/BOLL/NONE`。

- [ ] **Step 4: Run GREEN**

Run:

```powershell
pnpm --dir apps/desktop exec vitest run src/components/MarketChartToolbar.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/desktop/src/components/MarketChartToolbar.tsx apps/desktop/src/components/MarketChartToolbar.test.tsx
git commit -m "feat(desktop): 拆分行情主图与副图指标"
```

### Task 2: 分时累计均价纯函数与自定义指标

**Files:**
- Create: `apps/desktop/src/features/market/intradayAverage.ts`
- Create: `apps/desktop/src/features/market/intradayAverage.test.ts`

- [ ] **Step 1: Write failing cumulative average tests**

覆盖成交额可用、成交额缺失时典型价降级、零成交量跳过和只使用当前及之前数据：

```ts
expect(calculateIntradayAverage([
  bar({ close: 10, volume: 100, turnover: 1_000 }),
  bar({ close: 12, volume: 100, turnover: 1_200 }),
])).toEqual([{ average: 10 }, { average: 11 }]);
```

- [ ] **Step 2: Run RED**

Run:

```powershell
pnpm --dir apps/desktop exec vitest run src/features/market/intradayAverage.test.ts
```

Expected: FAIL because `intradayAverage.ts` does not exist.

- [ ] **Step 3: Implement the pure calculation**

逐行累计 `turnover` 与 `volume`。当单行 `turnover <= 0` 时使用
`((high + low + close) / 3) * volume`；累计成交量为零时返回空对象：

```ts
export interface IntradayAverageValue {
  average?: number;
}

export function calculateIntradayAverage(
  bars: KLineData[],
): IntradayAverageValue[] {
  let cumulativeTurnover = 0;
  let cumulativeVolume = 0;
  return bars.map((bar) => {
    const volume = finitePositive(bar.volume) ?? 0;
    if (volume > 0) {
      const typicalPrice = (bar.high + bar.low + bar.close) / 3;
      cumulativeTurnover += finitePositive(bar.turnover) ?? typicalPrice * volume;
      cumulativeVolume += volume;
    }
    return cumulativeVolume > 0
      ? { average: cumulativeTurnover / cumulativeVolume }
      : {};
  });
}
```

导出 `intradayAverageIndicator`，名称为 `AVG`、`series: "price"`、单条
`average` 线，颜色使用琥珀色。

- [ ] **Step 4: Run GREEN**

Run:

```powershell
pnpm --dir apps/desktop exec vitest run src/features/market/intradayAverage.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/desktop/src/features/market/intradayAverage.ts apps/desktop/src/features/market/intradayAverage.test.ts
git commit -m "feat(desktop): 增加分时累计均价指标"
```

### Task 3: 固定 pane 指标生命周期

**Files:**
- Modify: `apps/desktop/src/components/ProfessionalMarketChart.tsx`
- Modify: `apps/desktop/src/components/ProfessionalMarketChart.test.tsx`

- [ ] **Step 1: Write failing chart lifecycle tests**

验证：

```ts
expect(chart.createIndicator).toHaveBeenCalledWith(
  { name: "BOLL", paneId: "candle_pane" },
  false,
);
expect(chart.createIndicator).toHaveBeenCalledWith(
  { name: "MACD", paneId: "astraquant_secondary_pane" },
  false,
);
expect(chart.removeIndicator).not.toHaveBeenCalledWith();
```

分时 `AVG` 必须创建在 `candle_pane`；切换指标后量化 `removeOverlay` 不因指标 effect 额外触发。

- [ ] **Step 2: Run RED**

Run:

```powershell
pnpm --dir apps/desktop exec vitest run src/components/ProfessionalMarketChart.test.tsx
```

Expected: FAIL because current code removes all indicators and creates unnamed panes.

- [ ] **Step 3: Implement pane-scoped lifecycle**

在模块级注册 `intradayAverageIndicator`。新增常量：

```ts
const CANDLE_PANE_ID = "candle_pane";
const SECONDARY_PANE_ID = "astraquant_secondary_pane";
```

组件 props 改为 `mainIndicator`、`secondaryIndicator`、`showQuantSignals`。effect 只执行：

```ts
chart.removeIndicator({ paneId: CANDLE_PANE_ID });
chart.removeIndicator({ paneId: SECONDARY_PANE_ID });
if (mainIndicator !== "NONE") {
  chart.createIndicator({ name: mainIndicator, paneId: CANDLE_PANE_ID }, false);
}
chart.createIndicator(
  { name: secondaryIndicator, paneId: SECONDARY_PANE_ID },
  false,
);
```

`showQuantSignals === false` 时仅清除量化 group；恢复为 true 时从 props 重新创建。

- [ ] **Step 4: Run GREEN**

Run:

```powershell
pnpm --dir apps/desktop exec vitest run src/components/ProfessionalMarketChart.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/desktop/src/components/ProfessionalMarketChart.tsx apps/desktop/src/components/ProfessionalMarketChart.test.tsx
git commit -m "fix(desktop): 将行情指标绑定到固定图层"
```

### Task 4: 工作区状态与量化错误可见性

**Files:**
- Modify: `apps/desktop/src/components/MarketWorkspace.tsx`
- Modify: `apps/desktop/src/components/MarketWorkspace.test.tsx`
- Modify: `apps/desktop/src/styles/app.css`

- [ ] **Step 1: Write failing workspace tests**

验证从分时切换日 K 时主图由 AVG 切到上次 K 线选择；副图选择保持；关闭量化图层后
传入 `showQuantSignals={false}`。量化请求失败时显示：

```text
量化服务暂不可用
行情图仍可正常使用
```

并验证 WARMING_UP、SUPPRESSED、HOLD、BUY、SELL 文案互不混淆。

- [ ] **Step 2: Run RED**

Run:

```powershell
pnpm --dir apps/desktop exec vitest run src/components/MarketWorkspace.test.tsx
```

Expected: FAIL because the workspace has one indicator state and hides query errors.

- [ ] **Step 3: Implement workspace state**

使用：

```ts
const [klineMainIndicator, setKlineMainIndicator] =
  useState<MainChartIndicator>("MA");
const [intradayMainIndicator, setIntradayMainIndicator] =
  useState<MainChartIndicator>("AVG");
const [secondaryIndicator, setSecondaryIndicator] =
  useState<SecondaryChartIndicator>("VOL");
const [showQuantSignals, setShowQuantSignals] = useState(true);
```

将 `signalQuery.isError` 和可读错误文本传给 `QuantSignalStatus`。错误状态不得创建信号标记，
但不得遮挡或卸载行情图。

- [ ] **Step 4: Add stable toolbar/status styles**

主副图菜单使用现有细线和冷白主题；量化状态增加 `data-state="ERROR"` 琥珀色语义。
不增加动画，不改变行情安全红绿颜色。

- [ ] **Step 5: Run GREEN**

Run:

```powershell
pnpm --dir apps/desktop exec vitest run src/components/MarketWorkspace.test.tsx src/components/MarketChartToolbar.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add apps/desktop/src/components/MarketWorkspace.tsx apps/desktop/src/components/MarketWorkspace.test.tsx apps/desktop/src/styles/app.css
git commit -m "feat(desktop): 完善量化状态与指标控制"
```

### Task 5: 全量回归、视觉检查和文档

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap/product-roadmap.md`
- Modify: `docs/superpowers/plans/2026-08-06-market-indicator-finalization.md`

- [ ] **Step 1: Run all frontend gates**

```powershell
pnpm --dir apps/desktop test -- --run
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Run visual acceptance**

在开发程序中依次验证：

1. 分时 AVG + VOL；
2. 日 K MA + VOL；
3. 日 K BOLL + MACD；
4. 切换 KDJ 与 RSI；
5. 显示/隐藏量化图层；
6. 全屏、光标、缩放和实时刷新。

不得出现空白窗格、指标菜单与实际图层不一致、量化错误伪装成等待行情。

- [ ] **Step 3: Update project status**

README 与路线图记录：

- 行情指标前端已收尾；
- `baseline-v1` 仍是确定性基础设施基线，不是开源 AI 模型；
- 下一阶段进入 AI/ML 训练、回测和影子模式，不在前端制造历史信号。

- [ ] **Step 4: Final commit and push**

```powershell
git add README.md docs apps/desktop/src
git commit -m "docs(frontend): 完成行情图前端收尾"
git push origin feature/phase-1-desktop-platform
```


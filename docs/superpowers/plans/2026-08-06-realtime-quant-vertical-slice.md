# 实时量化核心第一个纵向切片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用真实一分钟行情完成“完成分钟线 → 在线特征 → 基线策略 → 结构化信号 → 决策记录 → API → 图表买卖点”的首个可回放闭环。

**Architecture:** 新增独立 `astraquant-quant` 包消费 `astraquant-data` 的 `MarketBar` 与 `astraquant-domain` 契约。量化包保持纯函数和确定性，不读取网络、账户或 UI；API 获取真实东财分钟线并调用量化核心；桌面端只展示 API 返回的结构化信号。第一版基线策略用于验证基础设施，不宣称盈利能力，也不能转成真实委托。

**Tech Stack:** Python 3.12、dataclasses、Decimal、FastAPI、Pydantic、React 19、TypeScript、KLineCharts 10、pytest、Vitest

---

### Task 1: SignalFrame 与 DecisionRecord 领域契约

**Files:**
- Create: `packages/domain/src/astraquant_domain/signals.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`
- Create: `tests/domain/test_signals.py`

- [ ] **Step 1: Write failing domain tests**

覆盖：

- 所有时间必须带时区；
- `expires_at` 必须晚于 `decision_time`；
- `ACTIVE` 信号必须有 `BUY`、`SELL` 或 `HOLD` 动作；
- `SUPPRESSED` 和 `WARMING_UP` 只能是 `HOLD`；
- 置信度限制为 `0..1`；
- `DecisionRecord` 的 signal、feature、strategy 引用不能为空。

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/domain/test_signals.py -q`

Expected: FAIL because `astraquant_domain.signals` does not exist.

- [ ] **Step 3: Implement minimal immutable contracts**

定义 `SignalAction`、`SignalState`、`SignalFrame` 和 `DecisionRecord`，价格与置信度使用 `Decimal`，原因码使用不可变 tuple。

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/domain/test_signals.py -q`

Expected: PASS.

### Task 2: 独立量化包与完成分钟特征

**Files:**
- Create: `packages/quant/pyproject.toml`
- Create: `packages/quant/src/astraquant_quant/__init__.py`
- Create: `packages/quant/src/astraquant_quant/features.py`
- Create: `tests/quant/test_realtime_features.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Write failing feature tests**

给定 21 根一分钟线，验证：

- 决策时刻尚未完成的当前分钟被排除；
- 输出只含截止时刻可用数据；
- 特征包含 `return_1m`、`return_5m`、`ma_5_gap`、`ma_20_gap`、`volume_ratio_20`、`realized_volatility_20`；
- 少于 20 根完成分钟线返回 `WARMING_UP` 所需的明确原因；
- 相同输入产生相同 `feature_snapshot_id`。

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/quant/test_realtime_features.py -q`

Expected: FAIL because `astraquant_quant` does not exist.

- [ ] **Step 3: Implement deterministic feature snapshot**

使用 `Decimal` 计算收益、均线距离和量比；哈希内容只包含标的、定义版本、完成分钟线时间与特征值。禁止读取当前未完成分钟线。

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/quant/test_realtime_features.py -q`

Expected: PASS.

### Task 3: 基线策略、风控抑制与决策记录

**Files:**
- Create: `packages/quant/src/astraquant_quant/engine.py`
- Create: `tests/quant/test_realtime_engine.py`

- [ ] **Step 1: Write failing engine tests**

验证：

- 行情状态不是 `LIVE` 时输出 `SUPPRESSED/HOLD`；
- 最新完成分钟线超过 120 秒时输出 `SUPPRESSED/HOLD`；
- 特征不足时输出 `WARMING_UP/HOLD`；
- `return_5m >= 0.003`、`ma_5_gap > 0`、`ma_20_gap > 0`、`volume_ratio_20 >= 1.5` 时输出 `BUY`；
- `return_5m <= -0.003` 且 `ma_5_gap < 0` 时输出 `SELL`；
- 其余情况输出 `ACTIVE/HOLD`；
- 相同输入得到相同 signal ID 和 decision ID。

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/quant/test_realtime_engine.py -q`

Expected: FAIL because the engine does not exist.

- [ ] **Step 3: Implement baseline engine**

策略 ID 固定为 `intraday-momentum-volume`，版本为 `baseline-v1`。输出包含参考价、有效期、置信度、原因码和确定性 `DecisionRecord`。`SELL` 表示离场/回避提示，不表示做空。

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/quant/test_realtime_engine.py -q`

Expected: PASS.

### Task 4: 只读实时信号 API

**Files:**
- Modify: `packages/api/pyproject.toml`
- Modify: `packages/api/src/astraquant_api/market_schemas.py`
- Modify: `packages/api/src/astraquant_api/market_routes.py`
- Modify: `tests/api/test_market_routes.py`

- [ ] **Step 1: Write failing API tests**

新增认证路由：

```text
GET /v1/market/instruments/{instrument_id}/signal
```

验证响应包含 `feature_snapshot_id`、`signal`、`decision_record`，并且非 LIVE 或数据不足时诚实返回抑制状态，不生成 BUY/SELL。

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/api/test_market_routes.py -q`

Expected: FAIL with 404 for the signal route.

- [ ] **Step 3: Implement route and Pydantic schemas**

路由读取最多 60 根真实 `1m` 数据，以服务时钟作为决策时刻，传入当前连接状态。响应不得包含 token、账户字段或真实委托出口。

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/api/test_market_routes.py -q`

Expected: PASS.

### Task 5: 桌面信号状态与买卖点图层

**Files:**
- Modify: `apps/desktop/src/api/market-contracts.ts`
- Modify: `apps/desktop/src/api/client.ts`
- Modify: `apps/desktop/src/api/client.test.ts`
- Modify: `apps/desktop/src/api/queries.ts`
- Modify: `apps/desktop/src/api/queries.test.tsx`
- Modify: `apps/desktop/src/components/MarketWorkspace.tsx`
- Modify: `apps/desktop/src/components/MarketWorkspace.test.tsx`
- Modify: `apps/desktop/src/components/ProfessionalMarketChart.tsx`
- Modify: `apps/desktop/src/components/ProfessionalMarketChart.test.tsx`
- Modify: `apps/desktop/src/styles/app.css`

- [ ] **Step 1: Write failing frontend tests**

验证：

- 只在连接状态可用时每 10 秒读取信号；
- `BUY/SELL` 被转换为已有 `MarketSignalMarker`；
- `HOLD`、`SUPPRESSED`、`WARMING_UP` 不创建虚假买卖点；
- 图表显示真实 B/S 标记和策略原因；
- 工作区显示策略版本、信号状态和有效期。

- [ ] **Step 2: Run RED**

Run: `pnpm --dir apps/desktop test`

Expected: FAIL because signal contracts and query do not exist.

- [ ] **Step 3: Implement API client and chart overlay**

使用 KLineCharts 自定义 overlay 注册 `astraquantSignal`，只消费 API 返回的明确 BUY/SELL。标记不允许根据前端价格走势自行生成。

- [ ] **Step 4: Run GREEN**

Run: `pnpm --dir apps/desktop test`

Expected: PASS.

### Task 6: 全量验证、文档和推送

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap/product-roadmap.md`

- [ ] **Step 1: Run Python verification**

```powershell
uv run pytest
uv run ruff check .
uv run mypy
```

Expected: all exit 0.

- [ ] **Step 2: Run desktop verification**

```powershell
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

Expected: all exit 0.

- [ ] **Step 3: Run repository verification**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only planned files changed.

- [ ] **Step 4: Commit and push**

```powershell
git add pyproject.toml uv.lock packages apps tests README.md docs
git commit -m "feat(quant): 建立实时特征与信号闭环"
git push origin feature/phase-1-desktop-platform
```


# Paper Workspace UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将模拟盘重构为低干预、资金语义清晰且不会发生控件溢出的本地交易工作台。

**Architecture:** 在纯函数账本中增加现金基线调整，再经 PaperService、FastAPI 和 React Query 暴露给桌面端。前端保留现有页面边界，重组账户概览、策略状态和持仓操作坞，并用针对性的组件测试锁定交互。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、React、TypeScript、TanStack Query、Vitest、Testing Library、CSS Grid。

---

### Task 1: 现金基线账本能力

**Files:**
- Modify: `packages/paper/src/astraquant_paper/ledger.py`
- Modify: `tests/paper/test_ledger.py`

- [ ] **Step 1: Write the failing test**

新增 `test_set_cash_balance_treats_the_difference_as_external_capital`，构造包含已标记持仓的账本，把现金从 `100000` 改为 `80000`，断言现金减少、`initial_equity` 同步减少、总盈亏保持不变且生成新快照。

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/paper/test_ledger.py -q`
Expected: FAIL，提示 `PaperLedger` 尚无 `set_cash_balance`。

- [ ] **Step 3: Write minimal implementation**

在 `PaperLedger` 增加 `set_cash_balance(state, cash, now)`；拒绝负数，以 `cash - old_cash` 调整 `initial_equity`，更新账户时间，并用现有 `_snapshot` 生成一致的新权益快照。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/paper/test_ledger.py -q`
Expected: PASS。

### Task 2: 现金 API 与前端数据层

**Files:**
- Modify: `packages/api/src/astraquant_api/paper_schemas.py`
- Modify: `packages/api/src/astraquant_api/paper_service.py`
- Modify: `packages/api/src/astraquant_api/paper_routes.py`
- Modify: `tests/api/test_paper_routes.py`
- Modify: `apps/desktop/src/api/paper-contracts.ts`
- Modify: `apps/desktop/src/api/client.ts`
- Modify: `apps/desktop/src/api/queries.ts`

- [ ] **Step 1: Write the failing API test**

新增路由测试，先录入期初持仓，再 `PATCH /v1/paper/accounts/{id}/cash` 发送 `{ "cash": "50000" }`，断言返回账户现金为 `50000`、权益基线等于现金加持仓成本；再次 GET 后数据仍存在。

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_paper_routes.py -q`
Expected: FAIL with HTTP 405/404。

- [ ] **Step 3: Implement the API path**

增加 `CashBalanceRequest`、`PaperService.set_cash_balance` 和 PATCH 路由；调用账本纯函数后持久化。TypeScript 增加 `PaperCashBalanceRequest`、`ApiClient.updatePaperCash` 和会刷新账户、账户列表、权益曲线的 mutation。

- [ ] **Step 4: Run focused backend tests**

Run: `uv run pytest tests/paper/test_ledger.py tests/api/test_paper_routes.py -q`
Expected: PASS。

### Task 3: 低干预模拟盘界面

**Files:**
- Modify: `apps/desktop/src/pages/PaperPage.tsx`
- Modify: `apps/desktop/src/pages/PaperPage.test.tsx`
- Modify: `apps/desktop/src/styles/paper.css`

- [ ] **Step 1: Write failing UI tests**

测试页面存在“剩余现金（不含持仓）”输入和“保存资金”按钮；保存调用 `updatePaperCash("account-1", { cash: "80000" })`。测试策略主区不再出现“建议数量”“单标的仓位上限”和自动执行复选框，只出现“运行一次检查”。测试期初录入区不再出现手动“买卖”入口。

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --dir apps/desktop test -- --run`
Expected: FAIL，旧表单仍在且无现金编辑入口。

- [ ] **Step 3: Implement the product layout**

将账户栏拆为身份区、安全状态和现金编辑；权益带明确显示资产公式。将策略台改为状态摘要与单一操作按钮，内部继续使用当前标的和固定安全参数。将交易坞改名为“初始化持仓”，删除手动买卖分段按钮，表单改为单列并支持连续添加，统一字段高度、字阶、间距和按钮宽度。

- [ ] **Step 4: Implement responsive constraints**

所有 `.paper-*` 网格子项添加 `min-width: 0`，输入与按钮添加 `width: 100%; box-sizing: border-box`；在 1180px、980px 和 620px 分别调整策略、持仓和权益布局，禁止横向溢出。

- [ ] **Step 5: Run frontend verification**

Run: `pnpm --dir apps/desktop test -- --run && pnpm --dir apps/desktop check && pnpm --dir apps/desktop build`
Expected: 82+ tests pass，TypeScript 与 Vite build 成功。

### Task 4: 融合账户上下文与共享行情图

**Files:**
- Modify: `apps/desktop/src/components/MarketWorkspace.tsx`
- Modify: `apps/desktop/src/components/MarketWorkspace.test.tsx`
- Modify: `apps/desktop/src/features/market/marketSignalOverlay.ts`
- Modify: `apps/desktop/src/pages/PaperPage.tsx`
- Modify: `apps/desktop/src/pages/PaperPage.test.tsx`

- [ ] **Step 1: Write failing integration tests**

测试模拟盘默认选择第一只持仓并渲染共享 `MarketWorkspace`；点击另一持仓后切换图表标的。测试虚拟成交转换为 `PAPER_FILL` 买卖点图层，且首页现有量化信号行为保持不变。

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --dir apps/desktop test -- --run`
Expected: FAIL，模拟盘尚未渲染共享行情图，图层类型只支持量化建议。

- [ ] **Step 3: Generalize chart context and markers**

让 `MarketWorkspace` 接受可选的账户上下文标签与额外买卖点；将 `MarketSignalMarker.source` 扩展为 `QUANT | PAPER_FILL`，合并实时策略点与账户成交点后传给 `ProfessionalMarketChart`。

- [ ] **Step 4: Integrate the paper account**

在 `PaperPage` 维护当前选中持仓，以持仓真实盯市数据构造 `QuoteCard`，复用 `MarketWorkspace`。从本地 fills 过滤当前标的并生成虚拟成交图层；持仓行支持键盘与鼠标选择。

- [ ] **Step 5: Verify shared behavior**

Run: `pnpm --dir apps/desktop test -- --run`
Expected: 模拟盘融合测试、首页行情测试和专业图表测试全部通过。

### Task 5: 全量验证与桌面视觉检查

**Files:**
- Modify: `docs/superpowers/plans/2026-08-06-paper-workspace-ux.md`

- [ ] **Step 1: Run repository verification**

Run: `uv run pytest -q && uv run ruff format --check . && uv run ruff check . && uv run mypy packages`
Expected: 全部通过。

- [ ] **Step 2: Run Rust verification**

Run: `cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check && cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml`
Expected: 全部通过。

- [ ] **Step 3: Launch and visually inspect**

运行根目录 `start.ps1`，打开模拟账户，在常规窗口与全屏状态检查：无控件越界、文字竖排、卡片遮挡；现金编辑、持仓录入和策略状态可以完整操作。

- [ ] **Step 4: Commit and push**

提交中文意图明确的 Git commit，推送 `feature/phase-1-desktop-platform`，等待 GitHub Actions 最终成功。

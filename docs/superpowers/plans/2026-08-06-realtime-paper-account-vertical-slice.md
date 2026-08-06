# 实时模拟账户闭环实施计划

> 状态：已批准产品设计后的第一份代码计划。执行时遵循 TDD，每个任务先写失败测试，再写最小实现，再提交。

## 目标

在现有东方财富只读真实行情上完成首个可运行的量化业务闭环：用户手动创建模拟账户和录入初始持仓，系统用最新真实行情持续盯市，可提交虚拟买卖指令、生成虚拟成交、更新现金与持仓、计算实时盈亏，并在应用重启后完整恢复。

本阶段不连接实盘交易账户、不发送券商委托，也不让 LLM 直接决定订单。当前 `baseline-v1` 只作为可审计策略信号输入；秒级特征、策略组合、DeepSeek 当日约束与未来实盘网关在后续独立计划实现。

## 架构边界

- `astraquant-domain`：账户、持仓、订单、成交、资金快照等不可变业务契约。
- `astraquant-paper`：确定性账本、A 股/ETF T+1 与费用规则、报价触发盯市、虚拟撮合。
- `astraquant-api`：SQLite 持久化、事务边界、行情订阅协调、认证 API。
- `apps/desktop`：模拟账户工作台；只消费 API，不在前端自行核算资金或收益。
- 金额和价格在 Python 内统一使用 `Decimal`；数据库保存为规范化十进制字符串，API 输出字符串，避免浮点累计误差。
- 每个虚拟订单必须携带 `idempotency_key`；成交、资金和持仓在同一数据库事务内提交。

## 完成标准

1. 创建模拟账户，填写初始资金。
2. 手动录入股票/ETF 初始持仓、成本价、可用数量。
3. 真实行情到达后自动更新市值、浮动盈亏、总资产。
4. 以真实最新价或一档报价执行虚拟市价单，生成订单与成交记录。
5. 买入扣现金并按 A 股 T+1 冻结当日新增数量；卖出检查可用数量。
6. 页面展示总资产、现金、持仓、当日/累计盈亏、订单和成交。
7. 重启本地服务后账户、持仓、订单、成交和最近权益快照仍存在。
8. Python、前端测试、类型检查和 lint 全部通过。

## Task 1：建立模拟交易领域契约

**文件**

- 新增：`packages/domain/src/astraquant_domain/portfolio.py`
- 修改：`packages/domain/src/astraquant_domain/__init__.py`
- 新增测试：`tests/domain/test_portfolio.py`

**测试先行**

覆盖：

- 账户模式只允许 `PAPER`、`MIRROR`。
- 数量必须为正整数，价格、现金和成本不得为负。
- `Position` 可计算市值、浮动盈亏和盈亏率。
- `PortfolioSnapshot` 的总资产严格等于现金加持仓市值。
- 订单、成交、持仓和权益快照均包含稳定 ID、账户 ID 与 UTC 时间。

**验证**

```powershell
uv run pytest tests/domain/test_portfolio.py -q
uv run mypy packages/domain/src
```

**提交**

```text
feat(domain): 定义模拟账户与交易账本契约
```

## Task 2：实现确定性虚拟撮合与账本

**文件**

- 新增：`packages/paper/pyproject.toml`
- 新增：`packages/paper/src/astraquant_paper/__init__.py`
- 新增：`packages/paper/src/astraquant_paper/fees.py`
- 新增：`packages/paper/src/astraquant_paper/ledger.py`
- 修改：`pyproject.toml`
- 新增测试：`tests/paper/test_ledger.py`
- 新增测试：`tests/paper/test_fees.py`

**测试先行**

覆盖：

- 买单优先采用 `ask_price_1`，缺失时采用 `last_price`；卖单优先采用 `bid_price_1`。
- 默认 A 股/ETF 费率模型可配置，买卖费用逐项可追溯。
- 资金不足拒单，不改变任何账户状态。
- 可用数量不足拒绝卖出。
- 买入成功增加总持仓但当日新增可用数量为 0；录入的期初可用数量可卖。
- 卖出成功扣减总数量和可用数量，现金增加净额。
- 重复 `idempotency_key` 返回同一结果，不产生第二笔成交。
- 最新报价只改变估值，不修改成本、现金或历史成交。

**实现要点**

- `PaperLedger.preview_market_order(...)` 先计算成交价格、费用和拒单原因。
- `PaperLedger.apply_fill(...)` 返回新的账户、持仓、订单、成交与权益快照，不原地修改对象。
- 费用拆分为佣金、印花税、过户费，规则放入可注入的 `FeeSchedule`。

**验证**

```powershell
uv run pytest tests/paper -q
uv run mypy packages/paper/src
```

**提交**

```text
feat(paper): 实现虚拟撮合与A股账本
```

## Task 3：新增可恢复的 SQLite 模拟账户仓库

**文件**

- 新增：`packages/api/migrations/versions/0003_paper_portfolio.py`
- 新增：`packages/api/src/astraquant_api/paper_repository.py`
- 新增测试：`tests/api/test_paper_repository.py`
- 修改测试辅助：`tests/conftest.py`（仅在现有夹具需要时）

**数据库表**

- `paper_accounts`
- `paper_positions`
- `paper_orders`
- `paper_fills`
- `paper_equity_snapshots`

关键约束：

- 账户名称非空、初始现金非负。
- 每账户每证券最多一条当前持仓。
- 订单 `idempotency_key` 在账户内唯一。
- 成交必须关联订单和账户。
- 所有时间使用 UTC；金额保存为十进制字符串。

**测试先行**

- 迁移从空库升级到 head 后五张表存在。
- 创建账户、期初持仓、虚拟成交与权益快照后可重新构造仓库并读回相同数据。
- 重复幂等键不会写入重复订单。
- 单次成交写入期间制造异常时，现金、持仓、订单和成交全部回滚。

**验证**

```powershell
uv run pytest tests/api/test_paper_repository.py -q
```

**提交**

```text
feat(api): 持久化模拟账户交易账本
```

## Task 4：把真实报价接入模拟账户服务

**文件**

- 修改：`packages/api/src/astraquant_api/market_service.py`
- 新增：`packages/api/src/astraquant_api/paper_service.py`
- 修改：`packages/api/src/astraquant_api/app.py`
- 修改：`packages/api/src/astraquant_api/cli.py`
- 新增测试：`tests/api/test_paper_service.py`
- 修改测试：`tests/api/test_market_service.py`

**测试先行**

- `MarketDataService` 能注册和移除报价观察者。
- `record_quotes` 只向观察者发布已进入缓存的有效订阅报价。
- 某观察者异常不会中断行情缓存或其他观察者。
- `PaperService` 收到报价后为相关持仓生成新的盯市权益快照。
- 没有最新报价时提交虚拟订单返回明确的 `quote_unavailable`，不猜价格。
- 同一报价时间和账户不重复写入等价权益快照。

**实现要点**

- 观察者是进程内边界，不把凭据或供应商对象传入模拟交易包。
- `PaperService` 在 FastAPI lifespan 中注册，在退出时注销。
- 只订阅存在持仓或待交易证券的报价；创建持仓后同步加入行情预算。

**验证**

```powershell
uv run pytest tests/api/test_market_service.py tests/api/test_paper_service.py -q
```

**提交**

```text
feat(api): 用真实行情驱动模拟账户盯市
```

## Task 5：提供认证的模拟交易 API

**文件**

- 新增：`packages/api/src/astraquant_api/paper_schemas.py`
- 新增：`packages/api/src/astraquant_api/paper_routes.py`
- 修改：`packages/api/src/astraquant_api/app.py`
- 新增测试：`tests/api/test_paper_routes.py`

**接口**

- `POST /v1/paper/accounts`
- `GET /v1/paper/accounts`
- `GET /v1/paper/accounts/{account_id}`
- `POST /v1/paper/accounts/{account_id}/positions/opening`
- `POST /v1/paper/accounts/{account_id}/orders`
- `GET /v1/paper/accounts/{account_id}/orders`
- `GET /v1/paper/accounts/{account_id}/fills`
- `GET /v1/paper/accounts/{account_id}/equity`

订单接口沿用 `Idempotency-Key` 请求头；没有该头或格式非法时拒绝请求。

**测试先行**

- 所有接口必须通过本地 Bearer 会话认证。
- 正确创建账户和期初持仓，返回规范化证券代码。
- 真实报价存在时下单成功，返回最新完整账户快照。
- 资金不足、可用数量不足、行情缺失、重复证券期初持仓返回稳定错误码。
- 重复幂等请求返回同一订单结果。

**验证**

```powershell
uv run pytest tests/api/test_paper_routes.py -q
```

**提交**

```text
feat(api): 开放本地模拟账户接口
```

## Task 6：实现桌面模拟账户工作台

**文件**

- 新增：`apps/desktop/src/api/paper-contracts.ts`
- 修改：`apps/desktop/src/api/client.ts`
- 修改：`apps/desktop/src/api/queries.ts`
- 新增：`apps/desktop/src/pages/PaperPage.tsx`
- 新增：`apps/desktop/src/pages/PaperPage.test.tsx`
- 新增：`apps/desktop/src/styles/paper.css`
- 修改：`apps/desktop/src/App.tsx`
- 修改：`apps/desktop/src/components/Sidebar.tsx`
- 修改：桌面样式入口文件（按现有导入位置接入）

**页面结构**

- 顶部账户切换与“新建模拟账户”。
- 总资产、现金、持仓市值、累计盈亏、当日盈亏五个核心指标。
- 手填期初持仓表单：证券代码、名称、数量、可用数量、平均成本。
- 当前持仓表：最新价、市值、浮盈、浮盈率、可用数量、行情时间。
- 虚拟下单卡：证券、买卖方向、数量；明确标注“虚拟成交，不发送券商委托”。
- 订单/成交时间线与权益曲线；无数据时显示下一步操作，不显示假数字。

**测试先行**

- 侧栏 `Paper 模拟` 可导航且不再显示 `Later`。
- 无账户时只显示开户引导。
- 创建账户后显示真实 API 返回的资金指标。
- 录入持仓和下单成功后刷新账户、订单、成交和权益查询。
- 后端错误以中文可执行提示展示，不吞掉错误码。

**验证**

```powershell
pnpm --dir apps/desktop test -- --run
pnpm --dir apps/desktop typecheck
```

**提交**

```text
feat(desktop): 上线实时模拟账户工作台
```

## Task 7：接入当前可审计量化信号，但不自动实盘化

**文件**

- 新增：`packages/api/src/astraquant_api/paper_strategy_service.py`
- 修改：`packages/api/src/astraquant_api/paper_routes.py`
- 修改：`packages/api/src/astraquant_api/paper_schemas.py`
- 修改：`apps/desktop/src/api/paper-contracts.ts`
- 修改：`apps/desktop/src/api/client.ts`
- 修改：`apps/desktop/src/api/queries.ts`
- 修改：`apps/desktop/src/pages/PaperPage.tsx`
- 新增测试：`tests/api/test_paper_strategy_service.py`
- 修改测试：`apps/desktop/src/pages/PaperPage.test.tsx`

**行为**

- 用户可为账户启用/暂停 `baseline-v1`。
- 服务按完整 1 分钟 K 线计算信号，信号记录包含策略版本、输入窗口、理由、置信度和决策 ID。
- 首版默认只生成“建议订单”，用户确认后才进入虚拟撮合；提供明确开关启用“仅模拟账户自动执行”。
- 自动执行受单证券最大仓位、单笔最大金额、现金和 T+1 约束；同一决策 ID 只执行一次。
- 页面展示信号、建议动作、风险拦截原因及其对应虚拟订单。

**测试先行**

- 相同 K 线输入得到相同信号与决策 ID。
- `HOLD` 不生成订单建议。
- 风险不通过时只记录拦截，不创建订单。
- 模拟自动执行关闭时不会成交；开启后且信号、风险均通过时只成交一次。

**验证**

```powershell
uv run pytest tests/api/test_paper_strategy_service.py -q
pnpm --dir apps/desktop test -- --run
```

**提交**

```text
feat(quant): 接通可审计策略与模拟账户
```

## Task 8：回归、文档与发布检查

**文件**

- 修改：`README.md`
- 修改：`docs/development/roadmap.md`（若实际路径不同，使用仓库现有路线图）
- 新增：`docs/architecture/paper-trading-ledger.md`

**文档内容**

- 明确真实行情、虚拟成交、未来实盘网关三者边界。
- 记录默认费率、T+1、估值口径、幂等与重启恢复规则。
- 列出下一阶段：秒级事件总线、特征层、多策略组合、DeepSeek `DailyRegimePlan`、回放与压力测试。

**完整验证**

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy
pnpm --dir apps/desktop test -- --run
pnpm --dir apps/desktop typecheck
pnpm --dir apps/desktop build
```

**提交**

```text
docs: 补充实时模拟交易闭环说明
```

## 执行顺序与检查点

- 检查点 A（Task 1-3）：纯领域账本和重启恢复完成，不依赖前端。
- 检查点 B（Task 4-5）：真实行情可驱动模拟账户，API 闭环完成。
- 检查点 C（Task 6）：用户可在桌面端完整操作和观察。
- 检查点 D（Task 7-8）：当前策略接入、全量回归和文档完成。

每个检查点结束后推送 GitHub。PPT 不在本计划中；待核心量化里程碑完成后，基于最终代码、指标和架构文档单独制作投资展示稿。

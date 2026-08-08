# AstraQuant 项目概念、现状与未完成计划交接

> 更新时间：2026-08-07  
> 用途：交给下一位 AI/开发者继续开发。  
> 重要：本文以当前本地工作树为准。接手者必须先保护未提交改动，禁止直接执行 `git reset --hard`、`git checkout -- .` 或删除工作树。

## 0. 接手后先做这五件事

```powershell
cd D:\AstraQuant\.worktrees\phase-1-desktop-platform
git status --short
git branch --show-current
git log -5 --oneline
git diff --stat
```

当前开发位置与分支：

- 项目主目录：`D:\AstraQuant`
- 实际开发工作树：`D:\AstraQuant\.worktrees\phase-1-desktop-platform`
- 当前分支：`feature/phase-1-desktop-platform`
- 当前远端基线提交：`cb39299 docs: 明确模拟盘产品体验与行情融合设计`
- GitHub：`Xiaogans1/AstraQuant`
- 当前工作树存在约 15 个已修改但未提交的业务文件，约 `1070 insertions / 182 deletions`。这些是正在进行的模拟盘体验重构，不是应当丢弃的临时代码。

建议接手顺序：

1. 阅读本文。
2. 阅读本文末尾列出的两份模拟盘设计文档。
3. 查看当前 diff，理解未提交实现。
4. 先修复“期初持仓证券搜索/代码规范化”问题。
5. 完成测试、桌面视觉检查、提交和推送，再继续扩展量化核心。

---

## 1. 一句话产品定义

**AstraQuant 是一套面向中国 A 股与国内期货的、本地优先、桌面优先、AI 主导的实时量化研究与决策辅助软件。**

它不是普通行情软件加一个聊天框，也不是让大语言模型直接追逐每个 Tick 下单，而是把以下能力组成可审计的完整闭环：

```text
真实实时行情
  → 秒级事件与分时特征
  → 确定性策略 / ML 模型推理
  → 信号、仓位计算与风控
  → 本地虚拟撮合
  → 持仓、现金、收益与回撤统计
  → K 线买卖点和决策证据展示
  → 复盘、改进与模型版本管理

在线 LLM / DeepSeek：
新闻、公告、研报、宏观、行业与情绪情报
  → 生成“当日策略约束与市场状态”
  → 约束实时量化核心，但不进入每个 Tick 的直接下单路径
```

当前阶段使用真实只读行情和本地模拟成交，不向券商发送真实委托。未来项目成熟后可以接入实盘，但必须通过独立交易网关、独立权限、独立风控和明确人工授权实现，不能让研究模型绕过风控直接下单。

---

## 2. 产品边界与核心原则

### 2.1 市场范围

- 第一优先级：中国 A 股、ETF、重要宽基指数。
- 第二优先级：国内期货。
- 架构可以保留多市场能力，但不能为了“大而全”拖慢国内市场闭环。
- 美股夜盘、全球产业链和商品雷达属于后续跨市场观察能力，不是当前核心阻塞项。

### 2.2 本地优先

- 行情、K 线、Tick、特征、策略、模型、账户、虚拟成交和日志默认保存在本机。
- 桌面端使用本地 Loopback API，不要求用户把私人数据上传服务器。
- Token、账户凭据、数据库、行情文件、日志和模型权重不得提交 Git。
- GitHub 只保存源代码、文档、数据契约、迁移、示例配置和脱敏夹具。

### 2.3 AI 主导，但不能由 LLM 裸奔交易

- LLM/DeepSeek 负责搜集并解释新闻、公告、研报、情绪、行业和宏观信息。
- LLM 输出结构化的“市场状态、当日偏好、禁入条件、风险预算、证据链和有效期”。
- 实时量化核心负责秒级行情特征、信号确认、仓位计算、风控和执行。
- 任何策略、模型和 AI 结论必须有版本号、时间、输入摘要、原因、置信度、有效期和失效条件。
- 当前 `baseline-v1` 是验证数据—策略—风控—模拟成交—审计闭环的基础策略，不是最终盈利模型。

### 2.4 产品体验原则

量化用户真正关心的信息按以下顺序展示：

1. 账户当前赚亏、仓位和可用现金是否安全。
2. 当前持仓应持有、减仓还是退出。
3. 信号为什么出现，可信度多高，何时失效。
4. 信号与实际虚拟成交位于真实 K 线的什么位置。
5. 策略日/月/年收益、最大回撤、胜率、稳定性和不同市场状态表现。

证券代码、建议数量、单标的仓位上限、特征版本等工程参数不能占据主界面。它们由策略和风控引擎管理，只在高级设置或审计详情显示。

---

## 3. 目标用户使用闭环

### 3.1 首次使用

1. 启动 AstraQuant，软件自动尝试连接本机已登录的东财掘金终端。
2. 用户无需注册或登录 AstraQuant 模拟账户；本地默认账户自动创建并在重启后恢复。
3. 用户填写“剩余现金”，即当前持仓之外仍可使用的资金。
4. 用户通过与首页自选一致的证券搜索框，连续录入自己真实持有的全部证券：证券、持有数量、可用数量、平均成本。
5. 从此以后用户不在模拟盘手工点虚拟买卖；量化策略负责后续虚拟交易。

### 3.2 日常使用

1. 首页观察真实大盘、核心指数、自选和实时行情。
2. 切换“市场 / 模拟账户”上下文，而不是进入一套完全割裂的行情页面。
3. 选择持仓或自选标的，在同一专业行情工作台查看分时、日/周/月/年 K、指标和十字光标。
4. 图表叠加：量化建议点、模拟成交点、持仓成本线和未来可能的实盘成交点。
5. 查看策略状态、决策理由、风险拦截、持仓盈亏和账户权益。
6. 查看日/月/年绩效、最大回撤、胜率、盈亏比和策略稳定性。

### 3.3 模拟盘资金语义

```text
剩余现金 = 用户当前未投入持仓、后续可用于虚拟买入的资金
持仓市值 = 真实最新行情 × 当前持仓数量
总资产   = 剩余现金 + 持仓市值
权益基线 = 外部现金调整 + 期初持仓成本
策略盈亏 = 当前总资产 - 权益基线（需排除后续入金/出金影响）
```

修改现金属于外部入金/出金，不应伪造成策略盈利或亏损。

---

## 4. 总体技术架构

```text
Tauri Desktop
└─ React + TypeScript + TanStack Query
   ├─ 市场首页 / 专业行情图
   ├─ 模拟账户工作台
   ├─ AI 情报与量化候选（待完善）
   └─ 本地设置、任务和审计

FastAPI Loopback Service（仅监听 127.0.0.1）
├─ 东财只读行情桥接
├─ 行情搜索、快照、分时与 K 线 API
├─ FeatureFrame / SignalFrame / DecisionRecord
├─ PaperService 与账户 API
└─ 本地任务、质量、审计 API

Quant / Paper Core
├─ 行情事件与在线特征
├─ baseline-v1 策略（当前基础闭环）
├─ 风控与 A 股 T+1
├─ 本地虚拟撮合
├─ 现金、持仓、订单、成交与权益账本
└─ 后续：秒级策略组合、ML 推理、绩效分析

Local Persistence
├─ SQLite：账户、订单、成交、自选、设置、任务、审计
├─ Parquet：不可变历史数据与快照
├─ DuckDB：历史/as-of 查询
└─ .astraquant/：本地运行状态，禁止提交 Git
```

### 4.1 当前数据源

- 当前真实数据源：东财掘金量化终端，只读行情。
- 本机 SDK Python：`D:\AstraQuantData\Eastmoney\PythonSDK\Scripts\python.exe`
- 东财终端必须登录并保持运行。
- Token 应保存在 Windows 凭据管理器，不进入代码、日志、文档或 Git。
- 缺少终端、Token、行情或休市时，界面必须显示真实空态，不能回退成假数据。

### 4.2 开源项目借鉴策略

AstraQuant 不 Fork 一个大型项目硬改，也不直接拼接或复制不兼容许可证代码，而是保留自己的领域模型，通过适配器借鉴：

| 项目 | 借鉴方向 | 决策 |
| --- | --- | --- |
| vn.py | 国内市场语义、事件引擎、合约和行情录制 | 深度参考，当前不接下单 Gateway |
| Qlib | 因子、Dataset、Model、Recorder、研究工作流 | 作为可选研究后端，不让核心依赖其格式 |
| LEAN | 证券/订单/组合领域模型、回测与实盘一致生命周期 | 学习设计与回归测试，不直接嵌入 C# 引擎 |
| NautilusTrader | 事件信封、确定性时钟、订单状态机、风险和事件溯源 | 深度参考架构，性能证明确有必要时再下沉 Rust |
| OpenBB | Provider 抽象、金融工作区和桌面产品体验 | 借鉴体验，不复制 AGPL 核心 |

---

## 5. 到目前为止已经完成的能力

以下能力已经存在，不应重新从零实现：

### 5.1 桌面和本地服务

- Tauri 管理本地 FastAPI 的启动、随机端口、会话认证和安全关闭。
- 根目录提供一键启动脚本，不要求用户自己进入深层目录或手工启动多个服务。
- 本地服务在线状态和异常空态已有基础展示。

### 5.2 真实行情

- 已接入东财掘金真实只读行情。
- 支持证券搜索、核心指数快照、自选持久化、真实分时和多周期 K 线。
- 自选保存到本地 SQLite，重启可恢复。
- 已做行情自动连接尝试、缓存和部分稳定性优化。
- 仍未完成真实 A 股交易时段连续 30 分钟的正式验收。

### 5.3 专业行情图

- 支持分时、日 K、周 K、月 K、年 K。
- 支持 MA/BOLL 主图和 VOL/MACD/KDJ/RSI 等指标能力。
- 支持十字光标联动、价格和涨跌幅读取、滚轮缩放限制。
- 支持量化信号图层，并正在扩展模拟成交图层。
- 复权、拆分等公司行为问题已有设计意识，但仍需把“分析使用的复权口径”固化为可审计数据契约。

### 5.4 模拟交易基础闭环

- 已有本地模拟账户、现金、期初持仓、订单、成交、持仓、权益快照和重启恢复。
- 使用真实行情进行盯市和虚拟撮合。
- 已实现 A 股 T+1 跨日结算基础约束。
- 已有风控、同一决策幂等、虚拟成交审计等基础能力。
- 已有 `baseline-v1` 策略到信号、风险、模拟成交、账户变化的首个纵向切片。

### 5.5 已完成并推送的关键设计文档

- `docs/superpowers/specs/2026-08-06-paper-workspace-ux-design.md`
- `docs/superpowers/plans/2026-08-06-paper-workspace-ux.md`
- `docs/superpowers/specs/2026-08-06-ai-quant-portfolio-platform-design.md`
- `docs/superpowers/plans/2026-08-06-realtime-quant-vertical-slice.md`
- `docs/superpowers/plans/2026-08-06-realtime-paper-account-vertical-slice.md`
- `docs/architecture/paper-trading-ledger.md`
- `docs/architecture/adr/0003-ai-native-boundaries.md`

---

## 6. 当前未提交的代码：必须保留并完成

当前本地修改文件：

```text
apps/desktop/src/api/client.ts
apps/desktop/src/api/paper-contracts.ts
apps/desktop/src/api/queries.ts
apps/desktop/src/components/MarketWorkspace.test.tsx
apps/desktop/src/components/MarketWorkspace.tsx
apps/desktop/src/features/market/marketSignalOverlay.ts
apps/desktop/src/pages/PaperPage.test.tsx
apps/desktop/src/pages/PaperPage.tsx
apps/desktop/src/styles/paper.css
packages/api/src/astraquant_api/paper_routes.py
packages/api/src/astraquant_api/paper_schemas.py
packages/api/src/astraquant_api/paper_service.py
packages/paper/src/astraquant_paper/ledger.py
tests/api/test_paper_routes.py
tests/paper/test_ledger.py
```

### 6.1 这批改动已经做了什么

- `PaperLedger.set_cash_balance`：现金修改按外部入金/出金处理，不制造虚假策略盈亏。
- 新增 `PATCH /v1/paper/accounts/{account_id}/cash`。
- 前端增加现金更新 contract、client 和 mutation。
- 模拟盘增加可编辑剩余现金、总资产公式和更清晰的资金语义。
- 删除用户手工虚拟买/卖的主流程；用户只录入期初持仓。
- 策略区隐藏证券代码、建议数量、仓位上限和自动成交等工程参数，收敛为低干预操作。
- 期初持仓表单改为空表单并支持连续添加。
- 持仓增加“查看策略图”。
- `PaperPage` 复用 `MarketWorkspace`。
- `MarketWorkspace` 增加账户上下文和额外图表标记参数。
- `MarketSignalMarker.source` 增加 `PAPER_FILL`。
- 虚拟成交可以转换为买卖点标记传入专业图表。
- 模拟盘 CSS 已大面积重写，以修复按钮溢出、卡片遮挡、字号不一致和响应式问题。

### 6.2 这批改动已经执行过的验证

上一次验证结果：

- 前端：19 个测试文件、84 个测试通过。
- `pnpm --dir apps/desktop check` 通过。
- Vite build 通过，仅有非阻塞的 `chunk > 500 kB` 警告。
- `tests/paper/test_ledger.py tests/api/test_paper_routes.py`：19 个测试通过。

但这些结论必须由接手者在当前代码上重新运行确认。以下尚未完成：

- 全量 Python 测试。
- Ruff format/check。
- Mypy。
- Rust fmt/clippy/test。
- 当前桌面程序常规窗口与全屏视觉验收。
- 当前未提交代码的 Git commit、push 和 GitHub Actions 验收。

---

## 7. 当前最紧急的已知问题（下一步第一任务）

### P0-1：期初持仓不能直接输入裸证券代码

当前模拟盘期初持仓表单输入 `159516` 会直接发送给后端，后端要求规范标识 `159516.SZSE`，因此报错：

```text
Invalid instrument identifier: '159516'
```

用户明确要求：**复用首页“添加自选”的证券搜索体验。**

正确交互应为：

1. 用户输入代码或名称，例如 `159516` 或“半导体设备”。
2. 展示真实证券搜索结果下拉框。
3. 用户选择结果后，内部保存规范 `instrument_id`，例如 `159516.SZSE`。
4. 证券名称由搜索结果自动填充，不让用户手工猜名称。
5. 未选择有效结果前禁止提交。
6. 错误信息使用清晰中文，不把后端英文领域错误直接甩给用户。

当前首页可参考：

- `apps/desktop/src/pages/OverviewPage.tsx`
- `useMarketSearchQuery(client, search)`

推荐实现：抽出可复用的 `InstrumentSearchPicker`，同时用于首页自选和模拟盘期初持仓；不要复制两份搜索逻辑。

### P0-2：完成当前模拟盘视觉验收

重点检查：

- 输入框、按钮、策略卡片是否仍越界或遮挡。
- 全屏和普通窗口是否都正常。
- 12/14/18/30px 字阶是否统一。
- 初始持仓可以连续添加多只证券。
- 证券名称和代码不会出现错误或被截断。
- 现金修改后账户、权益和收益立即一致刷新。
- 共享图表不会因账户轮询产生整块闪烁。

### P0-3：验证、提交、推送

修复 P0-1/P0-2 后，必须先运行本文第 11 节的验证命令，再提交并推送当前分支。不要把半完成的工作留在本地。

---

## 8. 未完成计划与优先级

## P0：收尾当前模拟盘产品重构

- [ ] 抽取并复用 `InstrumentSearchPicker`。
- [ ] 期初持仓只接受已选择的规范证券标识。
- [ ] 自动填充名称，使用中文校验和错误提示。
- [ ] 支持连续添加全部期初持仓。
- [ ] 支持修正/删除录入错误的期初持仓，但修正不能伪装成策略成交。
- [ ] 现金编辑、外部资金基线和收益计算一致。
- [ ] 持仓选择与共享 `MarketWorkspace` 稳定联动。
- [ ] 模拟成交 B/S 点显示在正确证券、正确时间和正确价格。
- [ ] 页面不整块闪烁，不因轮询反复进入全屏 loading。
- [ ] 普通窗口、全屏和较窄窗口无溢出、遮挡或异常字号。
- [ ] 全量验证、提交、推送并确认 CI。

## P1：把模拟盘变成真正可持续运行的量化工作台

当前只有“运行一次检查”的基础切片，后续需要：

- [ ] 策略服务生命周期：启动、暂停、恢复、故障降级和状态持久化。
- [ ] 策略默认覆盖当前持仓和用户自选池，不要求逐只手填代码。
- [ ] 秒级行情事件总线；分时快车道优先于慢速历史 K 线刷新。
- [ ] 增量计算在线特征，避免每次拉全量和整图重绘。
- [ ] 多策略组合和版本化策略注册表，而不是把 `baseline-v1` 写死成最终模型。
- [ ] 策略自动计算建议数量、资金使用、止损、减仓、退出和单标的风险预算。
- [ ] 风控覆盖现金、A 股 T+1、涨跌停、停牌、最小交易单位、重复决策、数据过期和行情异常。
- [ ] 虚拟撮合加入手续费、印花税、滑点、部分成交、拒单和交易日历。
- [ ] 决策全过程审计：输入快照、特征版本、模型/策略版本、约束、信号、风控结果、订单和成交。
- [ ] 支持历史行情回放，让实时策略能在相同事件接口上重复验证。

## P1：统一市场、模拟盘和未来实盘的账户上下文

首页和模拟盘不能继续成为两套割裂页面：

- [ ] 在共享行情工作区增加“市场 / 模拟账户”上下文切换。
- [ ] 未来可增加“实盘账户”，但当前不实现真实下单。
- [ ] 选择账户后，左侧/上方优先展示该账户持仓和真实盈亏。
- [ ] 同一张 K 线按上下文叠加：
  - `QUANT_SIGNAL`：量化建议买卖点。
  - `PAPER_FILL`：模拟成交点。
  - `POSITION_BASELINE`：期初成本线和录入时间。
  - `LIVE_FILL`：未来实盘成交点，当前只保留契约位置。
- [ ] 图层可开关，但行情、周期、指标、十字光标行为必须一致。
- [ ] 图上点击信号可打开理由、置信度、有效期、失效条件和风控结果。

## P1：绩效和投资组合分析

- [ ] 账户实时总资产、现金、持仓市值、当日盈亏和累计盈亏。
- [ ] 日、周、月、年收益曲线。
- [ ] 最大回撤、波动率、夏普/Sortino、胜率、盈亏比和换手率。
- [ ] 已实现盈亏与未实现盈亏分离。
- [ ] 按证券、策略、信号版本和市场状态归因。
- [ ] 对外部入金/出金做时间加权收益处理，不能污染策略绩效。
- [ ] 数据不足时明确显示“不足以评价”，禁止制造好看的假指标。

## P2：AI 情报与当日策略约束

- [ ] 建立新闻、公告、研报、行业、宏观和情绪 Provider 接口。
- [ ] 所有证据保留来源、时间、可用时间、证券映射和去重信息。
- [ ] 由 LLM/DeepSeek 生成结构化 `DailyPolicy`，内容至少包括：
  - 市场状态与置信度。
  - 关注/回避行业和标的类型。
  - 最大风险预算和仓位收缩比例。
  - 禁入、减仓和失效条件。
  - 证据链和有效期。
- [ ] `DailyPolicy` 只能约束确定性策略，不能直接绕过策略和风控产生实盘委托。
- [ ] 前端可视化 AI 情报收集、证据核验、策略形成和生效过程，让用户能参与、质疑和查看来源。
- [ ] Agent/Skill 用于情报工作流和研究，不用于微秒/秒级交易热路径。

## P2：模型研究与生产化

- [ ] 使用 Qlib 风格的可重复研究管线或适配器，建立训练/验证/测试分割和实验记录。
- [ ] 基线策略、传统 ML、深度时序模型分别评估，不因“AI”标签跳过简单基线。
- [ ] 防止未来函数、幸存者偏差、复权错误、数据泄漏和过拟合。
- [ ] 模型必须经过离线回测、走样本外、历史回放、影子模式和模拟盘稳定期才能晋级。
- [ ] 生产信号统一输出 `SignalFrame`，不让每个模型自行发明执行接口。
- [ ] 模型漂移、特征缺失、行情延迟和异常市场状态自动降级或抑制信号。

## P2：国内期货

- [ ] 完善期货合约、主力/连续、换月、夜盘、保证金、乘数和开平语义。
- [ ] 建立期货实时行情 Provider 和本地回放数据。
- [ ] 风控加入保证金、强平风险、涨跌停、夜盘交易日归属和合约到期。
- [ ] 继续借鉴 vn.py 的国内期货语义，但保留 AstraQuant 自有领域契约。

## P3：全球夜盘与产业链雷达

- [ ] 美股主要指数和关键行业夜盘观察。
- [ ] 半导体、AI 算力、存储、云、航天、能源、贵金属等全球产业链主题聚合。
- [ ] 明确数据源授权、延迟和时区，不把延迟数据标成实时。
- [ ] 只作为中国市场次日情报输入，不能与国内实时交易数据混淆。

## P3：未来实盘交易

这是明确可能的长期方向，但当前未实现：

- [ ] 独立 `LiveBrokerGateway`，与只读行情和 Paper 引擎物理/逻辑隔离。
- [ ] 用户明确开通、二次确认和可撤销授权。
- [ ] 独立风控进程、最大损失、熔断、撤单、断线恢复和人工紧急停止。
- [ ] 先影子下单对比，再小资金受限运行，最后才允许扩大。
- [ ] 实盘委托、成交和账户回报必须由券商回报驱动，不能靠本地猜测。
- [ ] LLM 永远不能直接调用实盘下单接口。

## P4：非核心但已规划

- [ ] 暗色、终端和原创动漫主题、自定义本地背景。
- [ ] 可拖拽、可停靠、可保存的桌面工作区。
- [ ] 多端只读同步或移动观察端，必须先设计隐私和同步边界。
- [ ] 项目成熟后制作面向投资人的简洁美观 PPT，重点讲实时数据、AI 情报、可审计量化、模拟闭环、国内市场壁垒和实盘演进路线。

---

## 9. 秒级实时量化的明确要求

用户希望盘中决策达到秒级，而不是仅依赖一分钟 K 线。实现时不要简单把 HTTP 轮询从 10 秒改成 1 秒，而应分层：

```text
快车道：行情事件 / Tick / 秒级聚合
  → 增量特征
  → 策略状态更新
  → 风控
  → 信号与模拟执行

慢车道：分时图、K 线、账户汇总、新闻、绩效
  → 按各自节奏批量刷新 UI
```

要求：

- 行情 Provider 优先采用事件/推送；若 SDK 只能轮询，需要背压、节流、缓存和断线重连。
- 核心计算不能依赖 React 页面是否打开。
- UI 只消费状态和增量事件，不能通过整页 refetch 驱动策略。
- 相同证券/周期请求去重，历史数据缓存，最新 bar 增量合并。
- 标记每条数据的 `event_time`、`available_time`、`received_time` 和延迟。
- 延迟或缺口超过阈值必须抑制信号并告警。
- 秒级不等于高频交易；A 股策略仍受市场微观结构、手续费、T+1 和数据权限约束。

---

## 10. 前端不可违背的产品规则

- 模拟账户进入即用，不要求登录，也不要求用户先创建复杂账本。
- 默认账户本地自动创建，失败时提供“重新读取”和可理解的错误恢复。
- 用户只负责初始化现金和期初持仓；后续买卖由量化策略在模拟盘执行。
- 不在主界面展示“建议数量、仓位上限、策略版本”等开发参数表单。
- 不允许表单按钮超出卡片，不允许文字被挤成竖排。
- 行情刷新时保留上一帧内容，只更新数字和图形，不整块闪白或反复显示 loading。
- 真实数据不可用时显示明确空态，绝不回填假数据。
- 红绿颜色遵循中国市场习惯，同时不能只依赖颜色表达状态。
- 默认风格保持现代、克制、清晰；动漫助手和主题是情绪价值，不得妨碍行情密度与风险信息。
- 普通窗口和全屏都必须进行实际截图检查，不能只靠单元测试判断视觉正确。

---

## 11. 启动与验证命令

### 11.1 一键启动

无论 PowerShell 当前在哪个目录，都可：

```powershell
cd D:\AstraQuant
.\start.ps1
```

`start.ps1` 会自动进入正确工作树并启动 Tauri；Tauri 会自动管理本地 FastAPI，不需要用户再开第二个服务终端。

### 11.2 首次依赖准备

```powershell
cd D:\AstraQuant\.worktrees\phase-1-desktop-platform
uv python install 3.12
uv sync --locked --all-packages
pnpm install --frozen-lockfile
```

### 11.3 前端验证

```powershell
pnpm --dir apps/desktop test -- --run
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

### 11.4 Python 验证

```powershell
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run mypy packages
```

### 11.5 Rust/Tauri 验证

```powershell
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
```

### 11.6 验收定义

只有以下全部满足，当前模拟盘重构才算完成：

- 测试、类型检查、构建、lint 和 Rust 检查通过。
- 东财终端运行时能自动连接真实行情。
- 裸代码/名称搜索可以正确选中规范证券。
- 重启后自选、账户、现金、持仓、订单、成交和权益恢复。
- 现金修改不改变既有策略盈亏。
- 图表展示正确的模拟成交点，切换持仓不串数据。
- 页面无闪烁、越界、遮挡和异常字号。
- 代码已提交、推送，GitHub Actions 成功。

---

## 12. 关键代码入口

### 前端

- `apps/desktop/src/pages/OverviewPage.tsx`：首页、自选、证券搜索参考实现。
- `apps/desktop/src/pages/PaperPage.tsx`：模拟账户主页面，当前重点重构文件。
- `apps/desktop/src/components/MarketWorkspace.tsx`：首页/模拟盘共享行情工作台。
- `apps/desktop/src/features/market/marketSignalOverlay.ts`：量化/成交图层映射。
- `apps/desktop/src/styles/paper.css`：模拟盘布局与响应式样式。
- `apps/desktop/src/api/client.ts`：本地 API client。
- `apps/desktop/src/api/queries.ts`：TanStack Query hooks/mutations。

### 后端和账本

- `packages/api/src/astraquant_api/paper_routes.py`：模拟账户路由。
- `packages/api/src/astraquant_api/paper_service.py`：模拟账户应用服务。
- `packages/api/src/astraquant_api/paper_schemas.py`：Paper API schema。
- `packages/paper/src/astraquant_paper/ledger.py`：纯函数账本与资金/持仓语义。
- `tests/api/test_paper_routes.py`：Paper API 行为测试。
- `tests/paper/test_ledger.py`：账本不变量测试。

### 设计和架构

- `README.md`
- `docs/research/open-source-comparison.md`
- `docs/research/license-and-adoption-matrix.md`
- `docs/roadmap/product-roadmap.md`
- `docs/architecture/adr/0003-ai-native-boundaries.md`
- `docs/architecture/paper-trading-ledger.md`
- `docs/operations/eastmoney-market-data.md`
- `docs/research/eastmoney-realtime-acceptance.md`
- `docs/superpowers/specs/2026-08-06-paper-workspace-ux-design.md`
- `docs/superpowers/plans/2026-08-06-paper-workspace-ux.md`

---

## 13. 禁止事项

- 不要丢弃当前未提交改动。
- 不要重新引入假行情、假市场温度、假 AI 情报或假收益。
- 不要让用户手工输入 `.SSE/.SZSE` 后缀。
- 不要让用户逐次填写策略的建议数量、仓位上限和工程参数。
- 不要用整页轮询和 loading 闪烁模拟“实时”。
- 不要把 LLM 直接放进秒级交易热路径。
- 不要在没有复权/可用时间语义的情况下拿价格序列训练模型。
- 不要在 README、日志或 Git 中写入东财 Token、账户密码和私人持仓数据。
- 不要为了接一个开源框架而破坏现有数据契约、许可证边界和本地优先原则。
- 不要在没有通过模拟、回放和独立风控前连接真实委托。

---

## 14. 推荐的下一次开发批次

下一位 AI 最合理的第一个批次应只做以下闭环，不要同时扩张到新模型：

1. 从首页提取通用证券搜索选择器。
2. 在期初持仓表单中使用该选择器，修复 `159516` 报错。
3. 补充前端测试：搜索、选择、规范 ID、自动名称、未选择不可提交、连续添加。
4. 在桌面程序中验证现金和多持仓初始化。
5. 检查共享行情图的模拟成交点、响应式和刷新稳定性。
6. 跑完整验证。
7. 提交并推送当前模拟盘重构。

完成这一批次后，再进入“持续运行的秒级量化策略服务 + 绩效看板”，这是下一阶段真正的核心。

---

## 15. 最终产品愿景

AstraQuant 最终不应只是一个展示行情和指标的桌面程序，而应成为用户每天打开的本地智能交易研究工作台：它能理解全球与国内信息，持续观察中国市场，给出有证据、有失效条件的盘中策略，在真实行情上进行可审计的模拟执行，清楚展示每次买卖点和长期绩效；当它经过足够长时间验证后，再以严格隔离的方式演进到用户主动授权的实盘执行。

产品竞争力不来自单一“大模型”或单一“神奇策略”，而来自以下能力同时成立：

- 真实、稳定、带时间语义的国内行情。
- 秒级但可降级、可审计的实时量化核心。
- AI 情报与确定性策略的正确分工。
- 研究、回放、模拟和未来实盘共享的数据与事件契约。
- 本地隐私、真实账户语境和优秀桌面体验。
- 每一笔信号、拦截、成交和收益都能解释与复现。

这就是后续所有代码、页面和模型选择的共同判断标准。

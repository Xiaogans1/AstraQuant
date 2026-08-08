# 量化核心升级 Implementation Plan（v2，2026-08-08 重梳理）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把量化核心从"二分类概率 → 阈值全仓切换"升级为"期望收益/信号强度 → 目标仓位"，且费用按用户真实费率建模、做T 有真实信号源、风险有规则兜底、结果可分层验证。每一步以真实回放对照验收。**模型层以 Qlib 等开源成熟实现为基座（分层接入，见 Task 6），交易层保留自研 T+1/费用/做T 语义——各取所长，不做二选一。**

**最高原则（2026-08-08 用户明确指令，见 docs/governance/engineering-principles.md）：**
**永远不追求速度，永远不做临时解决，要做就做到最优方案。** 本计划禁止任何"先跑通再改"的渐进式实现：每个 Task 必须先完成最优方案设计（含出处）并确认，再完整实现。模型以开源成熟实现为基础（Qlib 模型 zoo / 预训练时序模型 / FinRL），不自研低质算法。

**核心原则（本计划全部改动的共同约束）：**
1. **训练/推理特征永远一致**（point-in-time、按交易日 reset、无信息不动作）——出处：López de Prado (2018) ch.7。
2. **费用不写死、跟随用户配置**（用户实际：ETF、免最低佣金、佣金万2、免印花税 → 往返成本 ≈ 0.042%）；回放/模拟盘/实盘同一费用语义——出处：Garleanu & Pedersen (2013)；用户 2026-08-08 确认。
3. **频率是结果不是目标**：只有"期望收益 > 成本门槛"才触发，强信号才动，防每分钟试错——出处：Barber & Odean (2000)。
4. **每个 Task 用同一验收协议**（见 §3），指标对比基线，不靠感觉。

**Architecture:** 分层结构（2026-08-08 最终确认）：
```
模型层（Qlib/开源模型 zoo + Chronos-2 预训练对照）── ResearchProvider 适配 ─┐
信号层（自研：期望收益/成本门槛/频率约束）◄───────────────────────────────────┤
交易层（自研：T+1 回放/用户费用/做T/风控/分层统计）◄── 信号层输入 ────────────┤
```
- 交易层 `packages/quant/src/astraquant_quant/`（features / research_features / strategy_layer / replay / engine）——T+1 日解冻、用户 FeeSchedule、做T 识别、ATR 风控等 Qlib 不具备的 A 股语义，全部保留。
- 模型层 Qlib 通过 `ResearchProvider` 接入（产品计划原始设计：`docs/research/open-source-comparison.md`），数据目录、策略元数据、交易核心不依赖 Qlib。
- 研究工具 `tools/research/`（fetch_minutes / build_training_set / train_model / calibrate_thresholds / replay_model / batch_replay_report / publish_model）；模拟盘费用 `packages/paper/src/astraquant_paper/fees.py` + `GET/PUT /v1/paper/fee-config`（用户可配）。
- 前端决策画像已具备（DecisionProfiles / DecisionDetail / 做T标记）；模型管理页（Task 7）待建。
- **Task 1（P0）已完成（2026-08-08）**：特征窗口漂移、无信息不动作、费用模型统一（FeeSchedule 单一来源）、共享预测器、批量回放报表工具。

**Tech Stack:** Python 3.12、LightGBM、pandas、pyarrow、FastAPI、React。

---

## §1 事实基线（2026-08-08 自测 + 调研核实，不重复讨论）

**自测回放**（159516.SZSE 创业板ETF，5000 根 1min，2026-07-09~08-07，模型 lgbm-minute-v1，阈值 0.5/0.35）：
- 净收益 **-21.55%**，B&H -25.82%，超额 +4.27%，胜率 23.5%，最大回撤 30.89%，17 笔全仓买卖对。
- 画像产物：`.astraquant/research/diagnosis/`（3 图 + decision-profile-159516.json）。

**已确认的缺陷与结论（对应 Task 归属）：**
| # | 缺陷/结论 | 证据 | 归属 |
|---|---|---|---|
| D1 | 推理特征窗口与训练漂移：开盘时用"昨日尾盘特征"或 proba=0 兜底 → 14/17 次 SELL 在 09:30 第一分钟 | 自测画像 | Task 1 |
| D2 | 回放费用模型只有单一 fee_rate，无佣金/印花税/过户费，与模拟盘不一致 | 代码对比 | Task 1 |
| D3 | 全仓进出：仓位只有 0/100% 两值 | 自测画像（17 对全仓） | Task 2 |
| D4 | 信号弱：BUY proba 0.50–0.62、SELL 0.08–0.34 全压线；无止损（单笔 -10.3%） | 自测画像 | Task 2/4 |
| D5 | 特征全为趋势/动量类，无反转类（做T 信号源缺失） | research_features.py | Task 3 |
| D6 | "做T"是假象（开盘清仓+盘中接回），无法验证做T 贡献 | 自测画像 | Task 5 |

**用户费率（已确认，2026-08-08）：** ETF、免最低佣金（minimum_commission=0）、佣金万2、免印花税、过户费万0.1 → **单笔往返成本 ≈ 0.042%**（10 万单笔约 42 元）。对照写死默认（万2.5+最低5+个股印花税）0.102%，差 2.4 倍——费用必须跟随用户配置，写死默认即错。

**引用核实**：§4（全部 Crossref/官方来源核实，含一处修正：Moreira & Muir = JF 72(4):1611-1644）。

---

## §2 任务主线（按依赖顺序执行）

### Task 1 (P0) — 修地基：特征窗口一致 + 无信息不动作 + 费用模型统一

**Files:** `tools/research/replay_model.py`、`packages/quant/src/astraquant_quant/replay.py`、`packages/quant/src/astraquant_quant/research_features.py`（必要时）、`packages/quant/src/astraquant_quant/fees.py`（新增，或复用 paper 包 FeeSchedule）

- [ ] **Step 1.1 推理端特征与训练端一致**
  预测器按交易日分组计算特征（与 `build_training_rows` 同语义）；当日不足 30 根 → 返回"无决策"语义，而非 proba=0.0。
- [ ] **Step 1.2 回放引擎"无信息不动作"**
  `replay_bars` 对无特征决策一律 HOLD。测试：开盘 30 分钟内不会因 proba=0 触发 SELL。
- [ ] **Step 1.3 费用模型统一（复用用户 fee-config，不写死）**
  回放弃用单一 `fee_rate`；引入 `FeeSchedule`（佣金率/最低佣金/印花税率/过户费率，全可配）+ 标的费用属性（是否 ETF 免印花税）。`replay_model.py` 支持 `--fee` 读取模拟盘 fee-config 持久化值，默认跟随用户配置（免5、万2、ETF 免印花税）。报告输出"用户配置计费 / 零费用"两套净收益（参照 qlib 双报告）。
- [ ] **Step 1.4 回归验证**
  重跑 159516 回放：开盘 SELL 消失、决策画像变化；`uv run pytest -q` 全绿；`uv run mypy`（不带参数）全量通过；对比 §3 指标。

**完成定义（Done）：** 回放无 proba=0 触发交易；费用按用户 fee-config 计算且与模拟盘一致；159516 回放画像更新存档。

---

### Task 2 (P1) — 模型输出升级：期望收益 → 目标仓位（含成本门槛与频率约束）

**Files:** `research_features.py`（回归标签）、`tools/research/train_model.py`（回归头/dual-head）、`calibrate_thresholds.py`、`strategy_layer.py`（信号强度→目标仓位）、`replay.py`（目标仓位化）

- [ ] **Step 2.1 期望收益输出**
  保留二分类方向（meta-label），LightGBM 增回归头预测 `future_return`。信号强度 = f(期望收益, 波动率)。
- [ ] **Step 2.2 成本门槛 + 带式调整（Garleanu-Pedersen）**
  仅当 |期望收益| > 单笔往返成本（按用户 fee-config 计算，ETF ≈ 0.042%）才允许调仓；目标仓位向区间调整而非全仓切换（band rebalancing）。`build_target_position` 已有骨架。
- [ ] **Step 2.3 频率与信号强度约束（Barber-Odean）**
  触发 = 期望收益 > 成本门槛 且 信号强度超阈值；相邻调仓最小间隔（默认 15 分钟，可配）与单日调仓上限（默认 20 次，可配）；报告增加"净收益/调仓次数"经济性指标。
- [ ] **Step 2.4 回放引擎目标仓位化**
  逐 bar 向目标仓位调整（100 股整数倍），SELL 受 `available_qty`（T+1 日解冻）约束；保留全仓模式参数对照。
- [ ] **Step 2.5 验证**
  AUC/IC + 含费用净收益 + 调仓次数 + §3 全指标对照 P0 基线。

**完成定义（Done）：** 模型工件含期望收益输出；回放不再全仓进出；成本门槛按用户费率生效；调仓频率受约束。

---

### Task 3 (P2) — 反转特征：做T 的真实信号源

**Files:** `research_features.py`（特征扩展，版本升 intraday-v2）、`strategy_layer.py`（MODEL_FEATURE_COLUMNS 同步）、`build_training_set.py`

- [ ] **Step 3.1 反转类特征（point-in-time、按日 reset）**
  开盘跳空 gap（昨收 vs 今开）、9:30–10:00 时段反转、VWAP 乖离极值回归、尾盘效应（14:30–15:00）、布林带下轨击穿。
- [ ] **Step 3.2 T+1 底仓做T 语义**
  卖出/做T 信号只作用于 `available_qty`（当日解冻底仓）；先卖底仓→低位买回；当日新增买入次日解冻。
- [ ] **Step 3.3 验证**
  重训（含/不含反转特征两版），回放对比做T 段贡献（用 Task 5 的分层统计）。

**完成定义（Done）：** 反转特征入模型且回放有真实"同日卖→买回"交易对；做T 段统计可独立于趋势段。

---

### Task 4 (P3) — 止损/止盈规则层

**Files:** `replay.py`（风控钩子）、`strategy_layer.py`（RiskPolicy 扩展）、`tests/`

- [ ] **Step 4.1 ATR(14) 止损**
  入场后价格跌破 entry − 1.5~2×ATR 强制离场（参数化；ETF 按昨收基准）。
- [ ] **Step 4.2 日内亏损限额**
  当日已实现亏损超限额（默认 -2%，可配）后停止当日开仓，次日 reset（与做T 每日重置语义一致）。
- [ ] **Step 4.3 验证**
  有/无风控回放对比：净收益、最大回撤、胜率、单笔最大亏损。

**完成定义（Done）：** 风控规则生效且可配置；单笔最大亏损受 ATR 止损约束。

---

### Task 5 (P4) — 分层回测：趋势段 vs 做T段

**Files:** `replay.py`（交易对分类统计）、`tools/research/replay_model.py`（输出分层指标）、前端 ReplayResultView

- [ ] **Step 5.1 交易对分类**
  相邻 SELL→BUY 同日 = 做T 对；隔夜持有 = 趋势对。分别统计 PnL、胜率、次数、日均收益。
- [ ] **Step 5.2 前端展示**
  ReplayResult 增加分层字段；ReplayResultView 显示"趋势段 vs 做T段"对比。
- [ ] **Step 5.3 验证**
  对照 Task 3 含/不含反转特征结果，回答"做T 是否真的贡献 alpha"。

**完成定义（Done）：** 回放报告可区分趋势段/做T段收益；可归因做T 的真实贡献。

---

### Task 6 — 最佳模型架构对照实验（2026-08-08 讨论新增，Qlib 分层接入为第一步）

**Files:** `packages/quant/`（ResearchProvider 适配）、`tools/research/`（训练/评估扩展）、`batch_replay_report.py`（多模型矩阵）、`packages/api/`（模型注册扩展）

**背景（最终分析 2026-08-08）**：lgbm-minute-v1 在 10 只板块 ETF 样本外 proba 均值 0.06–0.14、98–100% 时间低于卖出阈值——单一基线模型无法支撑"最优方案"。Qlib 模型 zoo 有 20+ 顶会实现（模型层更强），但 Qlib 回测无 T+1/用户费率/做T 语义（交易层我们更强）——**分层接入：模型层用 Qlib/开源实现，交易层保留自研**。效果不空口断言，用同协议对照实验定胜负。

- [ ] **Step 6.1 ResearchProvider 适配（Qlib 分层接入第一步）**
  参照产品计划（`docs/research/open-source-comparison.md`：Qlib 作为可选研究引擎）与现有 `EastmoneyProvider` 边界：新增 `qlib` 研究 Provider，将 Qlib 模型 zoo 的候选模型接入我们的数据与回放引擎，保持核心解耦。Qlib 回测默认"含/不含费用"双报告（README 示例：成本侵蚀年化 4.9 个百分点）纳入对照基线。
- [ ] **Step 6.2 候选架构集（全部有出处、可复用开源实现）**
  LightGBM（基线）、DoubleEnsemble（Zhang et al. ICDM 2020）、LSTM/ALSTM、TRA（Dong et al. KDD 2021）、Transformer、Chronos-2 预训练微调（Amazon，Apache-2.0，arXiv:2403.07815 / 2510.15821）。参照 Qlib 模型 zoo 官方实现。
- [ ] **Step 6.3 统一评估协议**
  同一数据集（14 标的 30 万行）/特征/费用/回放引擎；**walk-forward 多窗口 + purged CV**；按板块分组报跑分；用多窗口稳定性（非单次指标）定胜负，防过拟合（López de Prado：回测过拟合检验）。
- [ ] **Step 6.4 模型 × 板块跑分矩阵与胜负值**
  输出"每个模型 × 每个板块"的样本外指标矩阵（含费净收益、超额 vs B&H、胜率、回撤、Sharpe）与模型对决矩阵（同板块内 A vs B 的 head-to-head 胜负与差值）。数据源 = `batch_replay_report` 扩展为多模型。
- [ ] **Step 6.5 板块分层训练决策（三层结构）**
  第1层 基座模型（全部标的联合训练）；第2层 适配层（按板块组校准阈值/仓位，数据不足时安全适配）；第3层 专属模型（仅当某板块 ≥5 标的 × 半年 且样本外显著胜出时升级，注册表 `scope` 字段路由）。
- [ ] **Step 6.6 验证与批准**
  最优架构产出模型工件，经发布门槛（样本外 AUC/IC + 含费收益 + 多窗口稳定性）注册批准。

**完成定义（Done）：** Qlib ResearchProvider 接入可用；得出有证据支持的架构结论；模型运营中心（Task 7）可展示跑分矩阵与胜负值。

---

### Task 7 — 模型运营中心（前端功能页，2026-08-08 讨论新增）

**Files:** `apps/desktop/src/pages/`（新页面）、`packages/api/`（模型路由扩展）、`model_registry` 表（scope 字段迁移）

**背景**：现有 `model_registry` 表 + API（注册/批准/发布门槛）已有后端基础，前端仅有策略徽标。产品路线（ai-native-quant-design）要求模型版本管理页面。

- [ ] **Step 7.1 模型列表页**
  版本、状态（草稿/已批准/已下线）、指标（AUC/IC/含费收益）、训练数据范围、特征版本、`scope`（global/板块列表）。
- [ ] **Step 7.2 模型 × 板块跑分矩阵与胜负值**
  展示 Task 6.3 的跑分矩阵与模型对决矩阵；真实数据来自批量回放报表（非估算）。
- [ ] **Step 7.3 训练中心**
  选择数据集组合/特征版本/标签参数 → 训练 → 自动评估 → 申请批准（复用 research 工具后端）。
- [ ] **Step 7.4 回放验证入口**
  一键重跑某模型 × 标的组 × 空仓/全仓，输出到现有 ReplayResultView。
- [ ] **Step 7.5 scope 路由**
  策略服务按标的板块路由到适用模型（global 兜底）。

**完成定义（Done）：** 页面可用；每个模型在各板块的跑分与胜负值可查；模型可训练/批准/回放。

---

### Task 8 — 资金流数据源评估与因子（2026-08-08 实测新增）

**Files:** `packages/data/`（数据源适配）、`tools/research/fetch_minutes.py`（扩展）、`research_features.py`（因子）

**实测结论（2026-08-08）**：
- 掘金 GM `stk_get_money_flow`：**无权限**（报错"用户无此数据接口权限 GetMoneyFlow"）；北向/龙虎榜/财务接口同属数据套餐，大概率同样受限。
- akshare 资金流接口：**反爬断连**（`stock_individual_fund_flow`/`stock_sector_fund_flow_rank` 重试 3 次 RemoteDisconnected）；akshare 基础行情正常。
- 当前通道拿不到官方资金动向字段。

- [ ] **Step 8.1 决策（§5）**：A. 自研分钟量价近似因子（大单占比、量价背离、尾盘资金异动——零成本、可回测） / B. Tushare（资金流/北向，积分制） / C. 掘金付费数据权限。
- [ ] **Step 8.2 实现选定路径**
  A 路径：从已有分钟量价构建资金流代理特征（volume-based flow proxy），入特征集 intraday-v2；B/C 路径：新增 Provider 适配（参照 EastmoneyProvider 边界，不破坏核心解耦）。
- [ ] **Step 8.3 验证**
  因子 IC 检验 + 与基线模型回放对比（Task 6 协议）。

**完成定义（Done）：** 资金动向数据/因子进入研究管线并有 IC 与回放证据。

---

## §3 统一验收协议（每个 Task 后执行）

数据：159516.SZSE 5000 根 1min（2026-07-09~08-07），初始现金 10 万，费用 = 用户配置（免5、万2、ETF 免印花税），对照零费用。

| 指标 | P0 基线（当前） | Task 1 后（✅ 2026-08-08 完成） | Task 2 后 | Task 3/4 后 |
|---|---|---|---|---|
| 净收益（用户费率） | -21.55% | **+13.56%**（零费用 +14.13%） | 更新 | 更新 |
| B&H / 超额 | -25.82% / +4.27% | -25.82% / **+39.38%** | 更新 | 更新 |
| 胜率 | 23.5% | **50%**（6/12） | 更新 | 更新 |
| 最大回撤 | 30.89% | **13.42%** | 更新 | 更新 |
| 调仓次数 / 单笔经济性 | 34 / 亏 | 24 / 净 +13563（集中 2 笔大赚） | 更新 | 更新 |
| 开盘 09:30–09:33 SELL 占比 | 100%（14/14） | **=0%** | =0% | =0% |
| 做T 段贡献（Task 5 后） | 无统计 | - | - | 更新 |

**Task 1 完成注记（2026-08-08）：**
- SELL 全部移至 10:00（当日第 30 根 bar 起的第一个可决策点），proba 均值 0.18 远低于阈值 0.35——模型真实的"开盘半小时后看空"时段信号（符合 Gao et al. 2018 日内时段效应），不再是 bug。
- 收益集中度极高：12 对交易中 7/22（+19954）与 7/31（+9002）两笔贡献全部收益，其余 10 笔合计 ≈ -15391；单笔最大亏损 -11319（08-03，-6.5%）无止损保护 → 是 P1（仓位/成本门槛）与 P3（止损）的直接输入。
- 修复前 -21.55% 的亏损主要来自特征窗口 bug（开盘必卖），非模型能力；修复后模型表现出真实的日内时段择时能力（21 天单标的样本，不外推）。
- 产物存档：`.astraquant/research/diagnosis/`（chart1/2/3 + decision-profile-159516-p0-fixed.json + replay-159516-p0-fixed.json）。
- 涉及代码：domain/fees.py（单一来源）、paper/fees.py（re-export）、replay.py（FeeSchedule + 无信息不动作 + 买入含费降档）、model_predictor.py（共享按日窗口预测器）、replay_model.py（--fee-config + 双报告）、research_routes.py（注入用户 fee-config + 共享预测器）。

每次更新把结果与画像图存档 `.astraquant/research/diagnosis/`，并同步本表。

---

## §4 引用核实记录（2026-08-08，Crossref/官方/源码逐条核实）

| 引用 | 核实 | 出处 |
|---|---|---|
| Barber & Odean (2000) | ✅ 摘要核实：最频繁交易家庭年收益 11.4% vs 市场 17.9% | JF 55(2):773-806, 10.1111/0022-1082.00226 |
| Garleanu & Pedersen (2013) | ✅ 交易成本下最优动态仓位（带式调整） | JF 68(6):2309-2340, 10.1111/jofi.12080 |
| Jegadeesh (1990) | ✅ 短期反转 | JF 45(3):881-898, 10.1111/j.1540-6261.1990.tb05110.x |
| Lehmann (1990) | ✅ 周内反转 | QJE 105(1):1-28, 10.2307/2937816 |
| Heston, Korajczyk & Sadka (2010) | ✅ 日内横截面时段模式 | JF 65(4):1369-1407, 10.1111/j.1540-6261.2010.01573.x |
| Gao, Han, Li & Zhou (2018) | ✅ 日内动量时段效应 | JFE 129(2):394-414, 10.1016/j.jfineco.2018.05.009 |
| Moreira & Muir (2017) | ✅ 波动率目标仓位（修正：非 JFE 124(1)） | JF 72(4):1611-1644, 10.1111/jofi.12513 |
| Kelly (1956) | ✅ Kelly 公式原始文献 | BSTJ 35(4):917-926, 10.1002/j.1538-7305.1956.tb03809.x |
| Almgren & Chriss (2001) | ✅ 最优执行 | J. Risk 3(2):5-39, 10.21314/jor.2001.041 |
| 上交所收费一览表（2026-01） | ✅ 官网：A股经手费 0.00341%、ETF 0.004% 双向 | sse.com.cn/services/tradingservice/charge/ssecharge/ |
| 印花税 0.05% 卖出单边（ETF 免征） | ✅ 财政部/税务总局 2023 年第 39 号公告；与 fees.py 默认一致 | 公开法规 |
| backtrader 费用模型 | ✅ 源码：CommInfoBase（PERC/FIXED/interest/leverage，默认 0 佣金） | github.com/mementum/backtrader |
| qlib 1min/Nested/双报告 | ✅ README：成本侵蚀示例 17.83%→12.90% | github.com/microsoft/qlib |
| Wilder (1978)、Faith (2007)、López de Prado (2018)、Bacon (2008) | 专著标准引用 | 无 DOI |

---

## §5 决策点（状态）

**已确认：**
- [x] 用户费率：ETF、免最低佣金、佣金万2、免印花税（往返 ≈ 0.042%）
- [x] 费用不写死，回放跟随用户 fee-config（复用模拟盘配置体系）
- [x] 回放/模拟盘/实盘共用同一费用语义
- [x] 最优方案原则（2026-08-08）：不追求速度、不做临时解决、先设计后实施（docs/governance/engineering-principles.md）
- [x] 大规模测试结论：lgbm-minute-v1 样本外信号失效（proba 均值 0.06–0.14，≥0.5 占比 0%）→ 阈值失配 + 训练/部署分布漂移，需重训与架构对照
- [x] 模型运营中心（Task 7）与跑分矩阵/胜负值纳入范围
- [x] 板块分层训练采用三层结构（基座+适配+按数据升级，Task 6.5），不预先拍板分板块
- [x] 最佳架构由对照实验决定（Task 6），不预先指定
- [x] **Qlib 分层接入**：模型层用 Qlib 模型 zoo/开源实现（ResearchProvider 适配），交易层保留自研 T+1/费用/做T 语义（Task 6 第一步）

**待确认（Task 2 前需定）：**
- [ ] 目标仓位映射形态：波动率目标（推荐）/ Kelly 分数 / 线性信号强度
- [ ] 频率约束参数：最小间隔 15 分钟、单日上限 20 次（默认建议，需敏感性验证）
- [ ] P2 反转特征在 P1 之后实施（推荐，先有正确仓位/费用语义）还是并行

**待确认（Task 8 前需定）：**
- [ ] 资金流路径：A. 自研分钟量价近似因子（推荐，零成本可回测）/ B. Tushare / C. 掘金付费权限
- [ ] 模型运营中心（Task 7）是否与 Task 6 并行实施

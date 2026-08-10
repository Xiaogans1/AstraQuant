# AstraQuant 量化核心正式架构设计（v3）

日期：2026-08-10<br>
状态：待用户审阅<br>
适用范围：A 股股票与场内 ETF；日线选股/配置、分钟级做 T、回放、Paper/Mirror，以及未来可选 Live 适配<br>
首批正式市场：上交所、深交所普通现金账户；北交所、港股通、融资融券等不得套用沪深规则，只有完成各自真实 API 覆盖、RuleBook、费用和差分场景后才能启用<br>
替代关系：本文经确认后，取代 `docs/superpowers/plans/2026-08-08-quant-core-upgrade.md` 作为量化核心的设计基线；旧 v2 计划不得直接继续实施，须根据本文另写新的 Implementation Plan。

## 1. 决策摘要

### 1.1 最终方向

AstraQuant 不再把“自研 LightGBM 二分类器 + 自研简化回放”继续修补成正式量化核心，也不整体迁移到某一个开源框架。采用以下分层组合：

```text
真实 API 数据（当前 bootstrap：Eastmoney，经 gm Python SDK；更优来源经资格测试后可加入）
  → 原始响应留存 → 规范化 → 质量门 → 不可变、vintage-aware 快照
  → Astra Feature/Label Snapshot
  ├─ Qlib：主研究框架、A 股模型 zoo、实验与风险模型基线
  ├─ vnpy.alpha：独立工程路径的 A 股因子/模型复现实验
  ├─ Chronos-2 / TimesFM 2.5 / Moirai 2 / TTM：受控 challenger
  └─ RD-Agent：研究自动化，晚于正确实验账本上线
  → 标准 AlphaForecast
  → 组合优化与目标仓位（Base Sleeve）
  → 日内做 T 覆盖层（Intraday T Sleeve）
  → 确定性风控与 OrderIntent
  → Astra 统一交易内核（REPLAY/PAPER/MIRROR 共用）
  ├─ RQAlpha：A 股账户、T+1、费用和撮合的主差分裁判
  ├─ 交易所规则 + Broker 对账：最终外部事实裁判
  ├─ WonderTrader/Hikyuu：目标仓位、性能与费用组件的局部交叉参考
  └─ vn.py / 券商网关：未来 Live/算法执行适配候选
```

这不是为了维持现有代码而做的折中。分层方案的原因是：截至本次调研，没有一个开源项目同时在以下四方面都是最强项：

1. A 股模型研究与大规模模型对照；
2. AstraQuant 自有真实 API 数据、不可变快照与可追溯数据血缘；
3. A 股 T+1、底仓做 T、历史规则、订单级费率和保守撮合；
4. REPLAY/PAPER/MIRROR/LIVE 的统一账户、审计和产品生命周期。

### 1.2 对“是否已经是最理想方案”的准确回答

- **架构方向：采用。** 截至 2026-08-10，在已审计项目、当前桌面产品边界和“效果优先”的约束下，“真实 API 数据真相 + Qlib 主研究 + vnpy.alpha 工程复现 + RQAlpha 主语义差分 + 交易所/Broker 对账 + Astra 统一运行内核”是推荐设计基线；这不是对未来所有项目和数据源的绝对最优证明。
- **具体冠军模型：现在不能声称已经最优。** Qlib 官方 A 股 benchmark 只能提供候选先验，不能替代 AstraQuant 自己的真实 API 数据、费用、A 股约束和锁定样本外实验。冠军必须由统一协议选出。
- **开源样例数据：禁止作为正式证据。** 只允许安装冒烟、接口契约和回归 fixture；正式市场/参考数据训练、微调、验证、回放和 Paper 基准全部来自 AstraQuant 真实 API Capture 及其快照，交易规则另以带来源的官方文档快照为证。开源预训练权重可以作为初始化候选，但不能把其训练语料或公开 benchmark 算成 Astra 的 A 股证据。
- **授权：不作为选型门槛。** 按用户指令，仅按实现效果、正确性、维护状态、可验证性和集成风险排序；仍需固定上游版本/commit，避免结果漂移。

出现以下任一情况必须重新调研并写 ADR：上游关键版本改变账户/费用/模型能力；新的真实 API 在 PIT、退市覆盖、L2 或修订版本上显著更强；产品扩到北交所/融资融券/真实资金；当前主裁判与 Broker 事实出现无法解释的系统性差异；新候选在同一冻结协议下显著击败现有 champion。

### 1.3 两条模型轨道，不再混成一个模型

| 轨道 | 目标 | 正式输入 | 首批生产候选 | 说明 |
| --- | --- | --- | --- | --- |
| 日线横截面/Base | 选择标的并决定隔夜基础目标仓位 | 多年日线、PIT 成分/行业/状态/公司行动；后续增加 PIT 基本面 | Ridge/Lasso、LightGBM、XGBoost/CatBoost 基线；DoubleEnsemble、TRA/HIST/MASTER 等 challenger | 数据深、可做多窗口验证，是第一条冠军轨道 |
| 分钟/Intraday T | 围绕基础仓位做日内减仓与回补 | 每日累计的真实分钟/Tick/L2 快照 | 线性/LightGBM 基线；GRU/TCN、PatchTST/iTransformer、TSFM challenger；有足够 L2 后才启用 DeepLOB 类模型 | 当前分钟历史不足以宣称生产级，只能研究/Shadow |

“做 T”不是把 BUY/SELL 相邻配对后贴一个标签，也不是强制每天交易。它是一个在开盘已结算底仓、现金、成本、流动性和风险预算约束下运行的独立目标仓位覆盖层。

## 2. 不可妥协的设计原则

1. **数据真相来自真实 API。** 开源项目提供算法、模型、接口和语义，不提供正式训练事实。
2. **原始市场价格与复权研究视图分离。** 账户、订单、成交和公司行动只用不复权事实；模型可用有明确 `as_of` 的派生复权视图。
3. **任何数据都有 `event_time` 与 `available_time`。** 历史上当时不可见的数据不能出现在特征、规则、成分股或标签中。
4. **模型只输出预测，不直接下单。** 预测、组合、风险、执行和账本必须分层。
5. **目标仓位是策略与执行之间唯一主契约。** 方向概率不能直接映射成“全仓买/全仓卖”。
6. **REPLAY/PAPER/MIRROR 共用同一个状态转换内核。** 模式只能替换时钟、行情源和成交回报源，不能复制账户语义。
7. **A 股规则按生效日期版本化。** T+1/T+0 品种、交易时段、申报单位、最小价位、涨跌幅、价格笼子、停复牌和费用不得写死。
8. **费用按订单和真实账户口径计算。** 部分成交不得重复收取订单最低佣金；实际账户费率优先于公共默认值。
9. **回放不制造成交。** 看见某分钟最高/最低价不等于能成交；涨跌停封单、停牌、量能、参与率、延迟和队列不确定性必须显式建模。
10. **无证据就不晋级。** 最强模型可以是简单模型；复杂度、论文数量和开源热度不是发布门槛。
11. **所有试验计入试验账本。** 不能只记录赢家，以免多重尝试和回测过拟合被隐藏。
12. **无法证明安全时 fail closed。** 规则缺失、数据陈旧、特征不一致、模型工件损坏或优化不可行时，不新增风险。

## 3. 现有 v2 与代码基线审计

旧计划已经正确识别“全仓进出、样本太少、模型单一、真实费率和反转特征不足”等问题，也完成了部分基础修复；但它仍把过多责任留在现有简化回放与单模型管线中，不能直接作为正式实现计划。

### 3.1 必须先清除的 P0 语义错误

| 问题 | 当前证据 | 影响 | v3 决策 |
| --- | --- | --- | --- |
| 回归目标期限不一致 | `research_features.py` 的分类标签使用 `index + horizon`，但 `future_return` 实际使用 `index + 1` | 分类、回归、阈值校准和报告评估不是同一个预测任务 | 引入版本化 `LabelSpec`，入口价、退出价、期限、基准、成本和不可交易处理都由一个实现生成 |
| 同 bar 决策与成交 | `replay.py` 在完整 bar 已被模型看见后，仍按该 bar `close` 立即成交 | 产生不可实现的乐观成交与未来泄漏 | 默认最早只能在 `decision_time + latency` 后的下一可交易事件成交 |
| 无预测时曲线断点 | `predict is None` 直接 `continue`，跳过盯市 | 权益、回撤和收益序列失真 | 无信号仍必须推进时钟、盯市、订单和账本 |
| 期末现金/持仓混用 | 期末持仓被按最后价和卖出费折入 `final_cash`，同时仍保留 `position_remaining` | 资产状态与“假设清仓”场景混为一谈 | 期末输出真实现金、持仓市值、权益；强制清仓只作为单独 scenario |
| 标量持仓不能完整审计做 T | Replay/Paper 只保存总数量与 `available_quantity` | 无法追踪开盘底仓、当日冻结买入、卖出来源、公司行动与每笔已实现成本 | 改为批次/结算桶账本，由总持仓派生汇总字段 |
| 最低佣金按 fill 重复风险 | `FeeSchedule.calculate` 只接收单次成交金额 | 一笔订单多次部分成交会重复套用最低佣金 | 以 provisional→Broker identity 绑定的 `FeeChargeUnit` 累计同一计费单元的 fills，终态完成最低佣金补差 |
| 正式行情路径默认复权 | Eastmoney `bars()` 当前调用 `adjust=1` | 回放成交价、涨跌停、公司行动和真实现金流会被复权价格污染 | API 原始层只保存不复权事实；复权是带版本和 as-of 的派生视图 |
| 快照“latest”选择错误 | `research_store.py` 对 snapshot hash 路径排序后取最后一个 | hash 字典序没有时间含义，训练可能读取任意历史快照 | 正式运行必须显式 pin `snapshot_id`；用户 `as_of` 只在入口解析一次 |
| 快照身份与完整性不闭合 | manifest hash 含 `created_at`；读取时不重新校验每个文件 SHA-256 | 相同内容重复抓取得到不同身份，落盘文件被改后仍可能被读取 | 分离稳定 `content_digest` 与 publication id；每次 formal read 递归验 hash |
| 正式/样例数据可混入 | 当前 fixture、AKShare、任意 dataset id 和训练时直拉行情没有递归 provenance gate | 改名或混合即可把非正式数据伪装为正式数据 | `evidence_class/run_class` 机器门控，目录、catalog、凭据与权限物理隔离 |
| Bar 时间声明不可靠 | 规范化路径可能优先使用 `bob`；`source_fetched_at` 可由数据最大时间推算 | 开始时间被当成完成时间，或伪造“已经抓取”时点 | 同时保存 bob/eob/session/observed receive；nominal availability 不早于 eob，Paper/Live 不早于真实接收，严格 PIT 的精确值版本不早于可证明时间 |
| 验证集被重复使用 | 当前固定跳过 5 行代替 purge，并在同一 test 上选阈值再报告 | 泄漏和选择偏差使 AUC/收益门槛失真 | 外层 walk-forward、内层 purged CV、锁定 holdout；阈值只能在 inner valid 选择 |
| 规则与品种属性静态化 | ETF 免税、T+1、lot size 等由调用参数或默认值传入 | 历史规则变化与不同 ETF/股票品种被错误统一 | `RuleBookSnapshot + InstrumentMasterSnapshot` 成为每次运行必需输入 |

### 3.2 对旧回放结论的处理

旧计划中 `159516.SZSE` 的收益、胜率和回撤只能作为历史诊断记录，不能作为任何新模型的晋级基线，原因是其标签、成交时点、期末权益与账户语义尚未通过 v3 正确性门。v3 会保留旧结果并标记 `LEGACY_SEMANTICS`，不会删除或悄悄改写。

## 4. 开源项目重新调研与采用矩阵

### 4.1 模型与研究

| 项目 | 已确认强项 | 已确认边界 | v3 采用方式 |
| --- | --- | --- | --- |
| Microsoft Qlib | A 股 Alpha158/Alpha360、模型 zoo、20 seeds benchmark、数据/Handler/Recorder、PIT、风险模型与组合基线 | 官方固定 train/valid/test、股票池、close 成交和简化成本不是现代 Astra walk-forward；样例数据和结果不是我们的正式证据 | **主研究框架**。由 Astra 快照导出 Qlib cache，模型输出转成 `AlphaForecastArtifact`；Qlib 自带回测只作研究对照 |
| vnpy.alpha | A 股 Alpha158、Lasso/LightGBM/MLP、时序/横截面策略、研究到实盘接口；可接国内数据 | 模型集合比 Qlib 窄；Alpha158 明确源于 Qlib，因此不是第二份独立学术证据；账户与高保真 A 股回放也不是本项目真相 | **独立工程复现路径**。同一 Astra 数据跑共同基线，识别 Runner、预处理或契约错误；未来 vn.py Gateway 可作 Live 适配 |
| RD-Agent(Q) | 基于 Qlib 的因子与模型联合迭代、自动研究 | 会显著增加试验数量；若试验账本与隔离不正确，会放大过拟合 | 基础管线、锁定验证和 trial accounting 完成后再启用；只生成候选，不自动发布 |
| Chronos-2 / TimesFM 2.5 | 预训练、多变量/协变量或长上下文时序、概率/分位数预测 | 通用时序 benchmark 不等于 A 股 alpha；公开预训练数据还可能污染较早测试期；输出需转成可交易收益并校准 | 分钟 OHLCV 或 ETF 时序 **challenger**，分 zero-shot/冻结头/LoRA/微调赛道；不作为横截面首发 |
| Moirai 2 / TTM 等 | 通用时序预训练、微调与滚动评估；TTM 可提供轻量 CPU 对照 | 同样缺少 A 股交易语义与直接 alpha 证据 | TSFM 挑战组；只有在资源、post-release holdout 和数据满足时进入决赛 |
| DeepLOB 类实现 | L2 订单簿建模的成熟研究方向 | 当前正式数据没有足够长期、连续、可回放的 L2 历史 | L2 数据达到发布标准前不训练、不宣称可用 |
| FinRL / FinRL-X | 目标权重、组合/时序决策和 DRL 研究框架；FinRL-X 明确采用 weight-centric contract | 原始 FinRL 当前定位偏教育/研究；FinRL-X 与 A 股账户/撮合仍需适配；DRL 样本效率和过拟合风险高 | 借鉴权重契约；DRL 只作为后期组合/执行 challenger，不作为首批 alpha 冠军 |

Qlib 官方 CSI300 表中，不同特征集的冠军并不相同：Alpha158 上 DoubleEnsemble 很强，Alpha360 上 HIST、IGMTF、TRA 等更有竞争力；到 CSI500 时 LightGBM 与 DoubleEnsemble 的顺序又发生变化。官方实验还是固定历史切分而非滚动 walk-forward。因此 v3 不再写“Transformer/Chronos 必然更强”，也不按单次公开榜单拍板。

### 4.2 A 股回测、账户与执行

| 项目 | 已确认强项 | 已确认边界 | v3 采用方式 |
| --- | --- | --- | --- |
| RQAlpha | 明确的股票 T+1 可卖量、账户/风险/撮合/交易成本模块；维护仍活跃 | 数据 bundle、策略生命周期和产品账户不等于 Astra；费用缺完整过户/券商分项，bar/tick matcher 也不能证明真实队列；不能直接统一 REPLAY/PAPER/MIRROR | **第一语义裁判**。只对已核查行为运行精确/不变量差分；必要时移植已验证算法，不把整个框架当最终市场事实 |
| Hikyuu | 深度适配 A 股、C++ 核心、费用组件、MoneyManager、组合/止损/滑点 | 核心 `TradeManager` 的聚合持仓不能作为通用 T+1 账户真相；分钟 T+1 依赖特定 MoneyManager/交易系统配置；部分默认费率已过时 | 用于组合构件、费用分项和性能局部参考；**不作为完整 T+1 裁判** |
| vn.py | 国内网关、事件引擎、组合策略、算法单、Paper 与运行生态 | 通用账户、PortfolioStrategy 回测和 PaperAccount 不主动实施完整股票 T+1、真实费用、现金与共享盘口撮合 | 未来 Broker/AlgoExecution 适配并回放真实异步事件；不接管研究真相或 Astra 账本 |
| WonderTrader | C++ 性能、目标仓位型 SEL 引擎、执行算法、国内交易接口；回测中存在 T1 frozen/target 不低于 frozen 的实现 | 挂单冻结、多单并发预占、费用分项和高保真统一撮合仍不完整 | T+1 目标不可达情景的第二局部参考，以及性能/目标仓位执行参考；不接管账本 |
| QUANTAXIS | A 股生态、QIFI 账户/订单/成交对象，正在推进 Rust 组件 | 当前处于架构迁移/alpha 阶段，正式采用会增加不确定性 | 不作为首批依赖；保留协议与账户研究参考 |
| hftbacktest | 延迟、队列和盘口成交模型 | 不是 A 股账户与规则引擎 | 有合格 L2 数据时，作为 `QUEUE_REPLAY` matcher 候选 |

### 4.3 三条路线与取舍

| 路线 | 近期成本 | 长期效果/正确性 | 决策 |
| --- | --- | --- | --- |
| 整包替换成一个 A 股框架 | 中高 | 会被该框架在数据、费用、撮合或实盘侧的缺口锁死，最终仍需大改 | 拒绝 |
| Qlib/RQAlpha 回测 + vn.py 实盘的双内核 | 低到中 | 上线较快，但账户、费用和成交语义会逐渐漂成两套真相 | 只允许作为短期适配手段，不作为正式终局 |
| 语义移植 + 自有统一状态机 + 差分验证 | 中高 | 初期要写核心契约，但可以让回放、Paper、Mirror 和未来 Live 共用同一事实，并持续吸收更强开源实现 | **采用** |

整体替换会同时丢失或重做：AstraQuant 的 API 原始数据链、不可变清单、Tauri/React 产品契约、Paper/Mirror 持久化、事件审计和未来 Broker Adapter。更关键的是，任何单一候选都不是 Qlib 模型研究、完整 A 股账户语义与生产网关的共同替代品。

最佳效果不是“代码复用率最大”，而是：

- 把 Qlib/vnpy.alpha 的成熟模型实现直接用于研究；
- 把 RQAlpha 的成熟 A 股语义、WonderTrader/Hikyuu 的局部实现和交易所/Broker 事实变成可执行的差分规范；
- 只保留 Astra 必须拥有的统一生产状态机；
- 任一自有语义都必须有交易所规则、开源裁判结果或明确 ADR 支撑。

### 4.4 本次源码审计冻结点

以下是 2026-08-10 本次结论实际核查的默认分支/发布提交，不代表运行时可以追随 `latest`：

| 项目 | 本次核查提交 | 用途 |
| --- | --- | --- |
| Qlib | [`79633dd`](https://github.com/microsoft/qlib/tree/79633dd9506ea689e5400dea0197717b5b3d74b7) | benchmark、模型与研究接口 |
| vn.py | [`fa5206f`](https://github.com/vnpy/vnpy/tree/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09)（4.4.0 时代） | `vnpy.alpha`、核心对象与 Gateway 边界 |
| RQAlpha | [`3503ab5`](https://github.com/ricequant/rqalpha/tree/3503ab57932540cd36bf8375134e52c6923bf0d2)（`release/6.3.0`） | T+1、费用与 matcher 主差分 |
| Hikyuu | [`7e1a61d`](https://github.com/fasiondog/hikyuu/tree/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95) | 组合/费用局部核查 |
| WonderTrader | [`70feef1`](https://github.com/wondertrader/wondertrader/tree/70feef13ef7cbc6d4c3333a6158a92b919311d48) | 目标仓位/T1 frozen/执行架构核查 |
| QUANTAXIS | [`a69e978`](https://github.com/yutiansut/QUANTAXIS/tree/a69e978a2e38d045a64c380cc3b5c9fa08fa4903) | 排除性账户/费用核查 |

Implementation Plan 必须为实际 Runner 再生成可复现 lockfile、镜像/环境 hash 与补丁清单。升级上游版本只能创建新的 oracle/model version，重跑 canonical scenarios 后晋级，不能覆盖旧证据。

## 5. 目标架构与包边界

```text
┌──────────────────────────── Data Truth Plane ────────────────────────────┐
│ API Capture → Canonical/Vintage → Quality Gate → Immutable Snapshot Registry │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ approved snapshot ids only
┌────────────────────────── Research Plane ────────────────────────────────┐
│ FeatureGraph/LabelSpec → Qlib | vnpy.alpha | challengers → Trial Ledger  │
│                    → ForecastArtifact → Validation/Registry              │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ approved AlphaForecast only
┌────────────────────────── Decision Plane ────────────────────────────────┐
│ Base Forecast → Base Optimizer → BaseTarget                              │
│ Intraday Forecast + BaseTarget/current lots → TPlan/OverlayTarget        │
│        → TargetReconciler → RiskAdjustedExecutableTarget → OrderIntent   │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ deterministic intent
┌────────────────────────── Execution Plane ───────────────────────────────┐
│ RuleBook + FeeProfile + Lot Ledger + OMS + Matcher + Accounting          │
│       REPLAY feed | PAPER feed | MIRROR opening | future LIVE reports    │
└──────────────────────┬───────────────────────────────────────────────────┘
                       │ scenario traces
              RQAlpha oracle + exchange/Broker facts + local cross-checks
```

### 5.1 推荐代码边界

| 边界 | 职责 | 禁止事项 |
| --- | --- | --- |
| `astraquant_domain` | 时间、预测、目标、订单、成交、批次、规则、费用与审计契约 | 不依赖 Qlib/vn.py/数据库/UI |
| `astraquant_data` | API capture、规范化、PIT、快照、质量、数据目录、Qlib/vnpy 导出 | 不训练模型，不计算账户收益 |
| 新 `astraquant_research` | FeatureGraph、LabelSpec、实验账本、Runner adapters、模型注册与验证 | 不写 Paper 账户，不直接下单 |
| `astraquant_quant` | Alpha 组合、目标仓位、组合优化、风险策略、OrderIntent | 不自行制造成交，不持久化真实账户 |
| 新 `astraquant_execution` | RuleBook、OMS、批次账本、费用、matcher、确定性事件状态机 | 不包含模型训练，不读取开源样例数据 |
| `astraquant_paper` | Paper/Mirror 运行编排、SQLite 事务、恢复和投影 | 不复制交易状态转换；调用 execution core |
| `astraquant_api` | 用户命令、查询、任务、审批与运行控制 | UI/API 不直接改账本内部状态 |

Qlib、vnpy.alpha、Chronos、Moirai、RQAlpha、WonderTrader 和 Hikyuu 不全部安装进主 Python 3.12 runtime。每个外部框架运行在固定 lockfile/commit 的隔离 Runner 中，通过 Arrow/Parquet 与版本化 JSON 契约通信。这样既保留全部实现效果，又避免依赖冲突和一次升级改变历史实验。

## 6. 真实 API 数据真相与快照体系

### 6.1 数据来源边界

| 数据类型 | 正式用途 | 是否可训练/发布 | 处理方式 |
| --- | --- | --- | --- |
| `provider_id=eastmoney`：现有 `EastmoneyProvider`，经 `interface_id=gm_python_sdk` 和 `transport_id=local_ndjson_bridge` 访问 | 当前 bootstrap 行情、标的信息、交易日历等；其他能力逐项实测 | 只有 `ProviderQualificationReport` 已证明的 endpoint/字段/范围可以 | `gm` 是 SDK/interface，不是第二 provider；原始响应与请求元数据先不可变留存 |
| 第二个认证市场/Broker API | 交叉核验、缺口补充或未来成交/账户事实 | 只有经 `ProviderApproval` 纳入白名单后才可 | 独立 provider/snapshot；禁止在主源失败时静默混源，冲突进入 quarantine |
| 交易所、税务、中国结算官方文件/接口 | RuleBook、费用、日历和结果核验 | 只作对应规则/核验输入，不可冒充行情或标签 | 保存原文、发布日期、生效/失效期、暂缓条款和内容 hash |
| AKShare 等开源聚合接口 | 可用性探索或独立核验 | 永久否 | 包装器本身不能升级为正式 provider；若其上游确有合格真实 API，必须另写直接 adapter 并重新做资格测试 |
| Qlib/vn.py/RQAlpha/Hikyuu 自带样例数据 | 安装冒烟、接口回归、差分 fixture | 否 | 标记 `SAMPLE_ONLY`，不能注册为正式 dataset |
| 合成/随机数据 | 属性测试、故障注入、边界情景 | 否 | 标记 `SYNTHETIC_TEST_ONLY` |
| 预训练模型的原始训练语料 | challenger 的预训练先验 | 不能当作 A 股证据 | 只有 Astra API 的锁定样本外结果可晋级 |

“真实”不等于“直接请求后立刻喂给模型”。API 可能修订历史值、改变 schema、发生限频、返回部分数据或使用复权口径。正式数据必须经过以下层级：

```text
L0 Capture       原始请求/响应，保留 provider、SDK/终端版本、request hash、received_at
L1 Canonical     统一标的、时区、单位、不复权 OHLCV/Tick/L2，保留 source row id
L2 PIT/Vintage    历史标的状态、上市/退市、ST、停牌、成分、权重、公司行动、RuleBook
L3 Feature/Label 由固定 FeatureGraph + LabelSpec + cutoff 生成的不可变训练/推理快照
L4 Runner Cache  Qlib bin/parquet、vnpy 数据缓存等可重建派生产物
L5 Experiment    模型工件、处理器、fold、seed、预测、报告与审批记录
```

L4/L5 永远引用 L0-L3 的内容哈希；不能用“最新数据集”这种可变指针重现历史模型。

每个数据对象增加 `evidence_class`，每次运行增加 `run_class`：

- `REAL_API_MARKET`：白名单行情 endpoint 的认证真实调用；
- `REAL_API_REFERENCE`：白名单标的、成分、状态、公司行动/基本面 endpoint 的认证真实调用；
- `REAL_API_BROKER`：券商资金、持仓、订单、成交和交割事实的认证真实调用；
- `DERIVED_REAL_API`：全部市场/参考祖先递归为合格 `REAL_API_*` 的确定性派生；
- `OFFICIAL_RULE`：交易所/税务/登记结算规则，只能作为规则与校验输入；
- `TEST_ONLY`、`EXPLORATORY_ONLY`、`LEGACY_UNVERIFIED`：永远不能进入正式证据链。

`run_class=FORMAL` 时，目录名、provider 字符串或人工勾选都不能升级证据等级；系统递归检查全部 ancestors、原始 payload hash 和 provider 白名单。白名单键不是一个可伪造字符串，而是 `vendor + product + endpoint + SDK/terminal build + permission tier + schema fingerprint`。当前 bootstrap 只含项目认证账户真实调用且通过逐项资格测试的 Eastmoney endpoint；RQData、JQData、Wind、Choice 或其他真实 API 都可按效果参与同一资格评估，但在报告通过前默认拒绝。任一祖先未知或混源即拒绝。现有未保存原始调用证据的数据全部标记 `LEGACY_UNVERIFIED`，不能事后改 manifest 追认。

`ProviderQualificationReport` 对每个 endpoint 单独记录真实 probe 的请求/响应 hash、首末日期、退市标的、PIT/vintage 能力、复权与单位、分钟分页/静默截断、L2 时间戳、公司行动/状态、修订行为、限频、schema 演化和重叠源差异。Eastmoney 在这些能力全部被证明前只是当前 bootstrap provider，不能被文档预先宣布为永久最优主源。

### 6.2 CaptureEnvelope

每次正式 API 调用至少记录：

- `provider_id`、接口名、SDK/终端版本、账户权限档位（不含密钥）；
- 规范化后的请求参数与 `request_hash`；
- `requested_at`、`received_at`、provider 给出的数据时间；
- 原始响应 bytes；SDK 不暴露 bytes 时，保存按固定 serialization version 无损规范化的响应对象；两者都记录 hash、行数、截断/分页/限频状态；
- schema fingerprint、时区、价格/成交量单位、复权参数；
- 重试次数、错误码和是否完成全量分页；
- 对应交易日历/标的主数据版本。

密钥、token 和账户隐私不进入 Capture，也不进入 Git。原始响应保存在本地状态目录，Git 只保存 schema、规则和代码。

当前项目 `market.bars` 服务层把单次 bars 返回限制为 5,000 条，而 51 个标准交易日约有 12,240 根 1 分钟 bar；上游 SDK 公布值即使更大，也不能绕过项目入口的实测限制。因此正式抓取必须按交易日/时间段分页，并由 `ProviderQualificationReport` 持续实测两层上限。每个 chunk 都有独立 request/response hash；父 Capture 只有在所有计划 chunk 完整、无重叠冲突、没有静默截断并通过 coverage 校验后才能 sealed。

### 6.3 不可变快照身份与读取规则

Manifest 同时具有：

- `content_digest`：只由规范化数据内容、canonical serialization version、字段顺序、Decimal/浮点编码、schema、provider、calendar、rule、`quality_policy_id/version`、确定性 `quality_result_digest` 和 parent digests 决定；质量运行的时间、日志路径、worker/attempt ID 与 `created_at` 等易变字段只属 publication metadata，不能进入内容身份；
- `snapshot_id`：一次发布实体的唯一 ID，可包含发布元数据；
- `parent_snapshot_ids/supersedes`：增量、修订和合并关系；
- 精确 raw object hashes 与全部文件 hashes；
- `evidence_class`、coverage、quality report 与 sealed 状态。

每次正式读取必须重新计算 manifest 和全部数据文件 SHA-256，并递归校验祖先证据链。训练、回放和模型注册只接受精确 `snapshot_id`；若 UI 提供 `latest/as_of`，API 入口解析一次后就把精确 ID 写入任务，Worker 不得再次查询 latest。hash 路径字典序、文件修改时间和目录创建时间都不能决定数据版本。

为防止数据文件和 manifest 被一起重写，snapshot publication 还要写入 append-only hash-chain ledger，并把批次 Merkle root/签名锚定到受保护 catalog 或 Git-tracked publication record。任何更正只能发布新 vintage/snapshot，不能修改旧 ledger entry。

### 6.4 时间和可见性

所有可用于研究的记录必须区分：

- `interval_start/interval_end`：bar 的明确区间，`event_time = interval_end`；日线供应商若给 `00:00/bob`，必须按交易日历映射到 session close；
- `event_time`：市场事件时间；非 bar 事实另存 `effective_from/effective_to`，不能让一个字段同时表示公告与生效；
- `source_available_time`：逻辑 observation 按市场/来源语义应当可用的 nominal 时间，例如 bar 结束并经供应商声明延迟后的时间；它不证明当前 payload 中这个精确值版本当时已经存在；
- `observed_received_time`：AstraQuant 此次真实收到 payload 的时间；
- `recorded_time`：不可变 Capture 成功落盘的时间；
- `source_revision_time/revision_id`：上游声明的该精确值版本及发布时间（如适用）；
- `vintage_id/value_hash/supersedes_vintage_id` 与 `first_received_time`：值版本身份、替代关系和本地首次观察；
- `vintage_proven_time`：当前精确值版本最早可被证明确已存在的时间；来源认证首版取 `source_available_time`，来源版本化修订取 `source_revision_time`，上游不提供版本证据时保守取 `first_received_time`；
- `vintage_kind`：`SOURCE_CERTIFIED_INITIAL`、`SOURCE_VERSIONED_REVISION`、`LOCALLY_OBSERVED_REVISION` 或 `AS_DELIVERED_UNVERSIONED`；
- `availability_basis`：`PROVIDER_TIMESTAMP`、`OFFICIAL_PUBLICATION`、`OBSERVED_LIVE` 或 `CONSERVATIVE_ESTIMATE`；
- `trading_date/session_id`：按交易所规则归属的交易日和时段。

Bar 必须满足 `interval_start < event_time <= source_available_time`；历史回补通常是 `source_available_time << observed_received_time`，二者没有全局大小约束。公司行动等事实可能先公告、后生效，因此 `effective_from` 与可见时间也不能套用一条通用不等式，必须由对应 policy 判定。

规范化层不得把今天批量下载多年前历史 bar 的 `observed_received_time` 写成 observation 的 nominal 可用时间，否则普通历史回放都会被错误阻断；也不得反过来把今天才观察到的修订值伪装成当年已存在的精确 vintage。`AvailabilityPolicy` 按模式从 nominal 时间与版本证据派生该记录的 `visible_time`，派生特征再由全部祖先的 `visible_time` 计算自身 `available_time`：

- `PAPER/MIRROR/LIVE`：`visible_time = max(source_available_time, observed_received_time, source_revision_time〔若有〕)`；迟到/补发/修订只影响到达后的未来决策；
- `REPLAY_AS_DELIVERED`：固定某次 API snapshot，以 observation 的 `source_available_time` 推进可重复历史回放；允许 `AS_DELIVERED_UNVERSIONED` OHLCV，但这是“按 nominal 时间调度当前快照”，不证明精确值当年存在。报告必须披露 `data_vintage_cutoff` 与占比，不能声称精确复原当时的原始数据版本；
- `REPLAY_PIT_STRICT`：`visible_time = max(source_available_time, vintage_proven_time)`，且只允许 `visible_time <= decision_time` 的值版本；今天首次抓到且无历史版本证据的 2010 数据不能假装通过严格 PIT；
- 对财报、公司行动、成分、ST/停复牌等可修订事实，若没有 PIT vintage/官方发布时间证据，最早可见时间只能取首次真实观察或可证明的公告时间，不能按事件归属日倒推；
- 任一 Feature/Label snapshot 都固定 `data_vintage_cutoff`、`availability_policy_id`、`revision_policy_id`、`vintage_mode` 和 `pit_fidelity`。`REPLAY_AS_DELIVERED` 可以用于候选筛选和可重复 OOS，但不能成为发布的唯一证据，必须由严格可用的 PIT 部分与 forward Shadow/Paper 补强。

所有 timestamp 以带时区 UTC 持久化，同时保留 venue local time 和 `trading_date`；禁止 naive datetime。`source_fetched_at` 必须来自真实 Capture 时钟，不能由数据最大时间加一分钟伪造。模型看到 09:30-09:31 bar 后产生的订单，仍不能按这根 bar 的收盘价成交。

### 6.5 不复权事实、公司行动和研究复权

建立四种严格分离的视图：

1. `RAW_EXECUTION`：不复权价格、真实成交量、真实现金/证券变动；唯一允许进入订单、成交、涨跌停和账本的视图。
2. `FEATURE_PIT_ADJUSTED`：只使用决策时已知公司行动生成特征，固定 `as_of=decision_time`。
3. `LABEL_REALIZED_TOTAL_RETURN`：用入场到退出区间实际发生的分红、送转等结果生成已实现标签；这些未来结果不能回流到特征，且标签只有在区间结束与必要修订等待后才成熟。
4. `RESEARCH_NORMALIZED`：为 Qlib/模型生成的尺度归一化视图，必须带 `adjustment_snapshot_id`、输入视图和 `as_of`。

分红、送股、拆并股、配股、ETF 分拆等以显式 `CorporateActionEvent` 进入账本，不能靠修改历史成交价“修正”账户。

### 6.6 防幸存者偏差与历史 Universe

训练日 `d` 的可选池只能来自 `d` 当时已知的：

- 上市/退市与暂停上市状态；
- 历史指数成分及权重；
- ST/风险警示、停复牌与板块；
- 可交易状态、最小上市天数和历史流动性；
- 资产类别和是否允许当日回转。

当前仍在上市的代码列表不能回推成历史 universe。退市、长期停牌和失败公司必须保留。若 API 无法提供某项历史主数据，该研究范围必须降级并在报告中标红，不能用今天的字段代替。

### 6.7 数据质量门

现有 `evaluate_bars` 只检查空集、重复、时序、日期和估计可用时间；正式门还必须覆盖：

- schema/单位/精度、symbol mapping、时区和 session 对齐；
- OHLC/价格/成交量/成交额不变量；
- 分页完整性、重复/缺口、午休、集合竞价与零成交 bar 语义；
- 日线与分钟聚合的一致性（允许明确的 auction/修订差异）；
- 前收盘、涨跌停价与公司行动断点；
- 历史成分、上市/退市和停牌覆盖；
- 主源与核验源的价格、量、日历差异分布；
- 异常值、突然 schema 变化和历史修订；
- 每个标的/日期/频率的 coverage map。

致命错误进入 quarantine，不发布 snapshot。缺失值不在原始层自动填补；模型层若采用填补，必须输出缺失 mask，并将处理器参数与模型一起冻结。

### 6.8 日线与分钟双轨

当前接口实测显示：个别标的日线可回溯约 21 年，分钟线只返回近期约 51 个交易日。它们是**已测接口/标的的观测，不是 provider 永久保证**，所以每次正式抓取都要记录实际 coverage。

- 日线轨道立即按已通过资格测试的沪深 universe、每只证券实际上市区间拉取 API 可用全历史；退市/PIT/status 能力未证明的范围必须显示 coverage gap，不能用当前列表补齐后声称“全 A 股”。
- 分钟轨道每个交易日增量捕获，并主动回补最近窗口；snapshot 以 parent/segment 关系合并，去重但不改写旧快照。
- Tick/L2 只有在 API 权限、连续性、时间戳和盘口字段通过专项门后才入正式轨道。
- 分钟样本未覆盖足够独立交易日与状态前，做 T 模型只能处于 `RESEARCH` 或 `SHADOW`，不能因单标的短期盈利晋级。

## 7. 特征、标签与模型研究架构

### 7.1 FeatureGraph 是唯一特征定义

禁止再分别手写“训练特征”和“实时特征”。每个特征由版本化 `FeatureSpec` 声明：

- 输入字段、窗口、频率和 session reset；
- 可见时间与最大回看；
- 横截面/时序处理顺序；
- 缺失、异常、winsorize、标准化和拟合区间；
- 适用资产/板块与单位；
- 上游实现来源（如 Qlib Alpha158 expression 及固定 commit）；
- 浮点容差、参考 fixture 和在线/离线等价测试。

Qlib 的 Alpha158/Alpha360 定义可以直接导入或在 Qlib Runner 内物化，但服务时必须复用同一 `DataHandler`/processor 工件或通过逐行等价测试的导出实现，不能手工仿写一个“差不多版本”。

派生时间是数据血缘的一部分，不能由下游任意盖章。对任一 vintage mode，`feature.available_time >= max(全部直接/递归数据祖先 visible_time, 拟合参数/Universe/规则工件 visible_time) + declared_processing_delay`；窗口特征还必须包含窗口内最后一个实际输入。任何实现若无法重算并证明该不变量，产物不得进入 Formal。

### 7.2 LabelSpec 绑定可执行价格

`LabelSpec` 至少包含：

- decision cutoff；
- 最早可执行入场规则（下一 bar open 仅在对应 opening price/capacity 证据允许时、下一事件 touch、VWAP 窗口等）；
- 预测 horizon 和退出规则；
- `label_matures_at` 规则，包括退出完成与预声明的修订/grace window；
- 绝对收益或相对基准/行业收益；
- 不可交易、涨跌停、停牌、退市与跨日处理；
- gross return、base-cost net return 和 stress-cost net return；
- 是否为 ranking、regression、classification、quantile 或 survival target。

日线默认任务是“使用 `d` 日 cutoff 前可见信息，预测 `d+1` 可执行后未来 H 日的超额收益/排名”；分钟默认任务是“bar t 完成并可见后，从下一可交易事件起预测 H 分钟收益”。具体 cutoff、成交窗口与标签成熟规则在实验开始前冻结。`label_matures_at` 必须不早于 `max(退出实际完成时间, 全部标签输入在当前 vintage mode 下的 visible_time, grace_window_end)`。任何训练样本必须满足 `label_matures_at <= training_cutoff`；尚未成熟的未来收益不能因行已存在就进入训练、标准化或阈值选择。

### 7.3 标准预测输出

所有模型统一输出 `AlphaForecast`，至少包括：

```text
forecast_id, instrument_id, model_id, feature_snapshot_id
as_of_time, decision_time, valid_from, expires_at, horizon
expected_return, expected_excess_return, rank_score
direction_probability, q10/q50/q90 或其他不确定度
calibration_id, universe_snapshot_id, reason/contribution references
```

模型缺少某个字段时明确为空；组合层根据模型能力选择 rank 或 calibrated return。不得把未经校准的 score 当成收益率，也不得把 0.51 概率直接当成 51% 仓位。

### 7.4 首批模型矩阵

#### 日线必跑矩阵

1. 无技能与可审计基线：截面均值/行业中性、Ridge/Lasso、简单动量/反转、等权与 benchmark。
2. Qlib Alpha158：LightGBM、XGBoost、CatBoost；稳定后再加以 LightGBM 为骨干的 DoubleEnsemble。
3. Qlib Alpha360/序列：GRU、TCN、ALSTM、TRA。
4. 有可靠 PIT 行业/概念/市场上下文后：HIST、MASTER、IGMTF 等关系模型；MASTER 公开仓库不含完整业务实现，必须标记为重实现 challenger。
5. 真正研究在线漂移时：先建立滚动重训基线，再比较 DoubleAdapt，不把 TRA 当成完整漂移治理。
6. vnpy.alpha：至少复现 Lasso/LightGBM/MLP 中的共同基线。

#### 分钟必跑矩阵

1. 无交易、持有、日内季节均值、VWAP/均值回归、线性模型；
2. LightGBM、XGBoost/CatBoost；
3. 数据量足够后再加 GRU/TCN、N-HiTS/TSMixer、PatchTST/iTransformer；
4. 随后才比较 TTM、Chronos-2、TimesFM 2.5、Moirai 2 的 zero-shot/轻量微调；
5. 合格 L2 长历史后才加 OFI/queue-imbalance 基线及 MLPLOB/DeepLOB/TLOB 等；
6. DRL 不进入首批分钟 alpha 矩阵。

“必跑”表示同阶段候选必须在相同数据、fold、费用和预算协议下比较，不表示全部进入产品。开发筛选至少 5 seeds；决赛随机模型按 Qlib 风格运行 20 seeds。同类模型还必须获得相同 HPO trial、wall-clock/GPU 预算，避免用算力差异冒充架构优势。

### 7.5 试验隔离和 Trial Ledger

每一次特征、模型、超参、seed、universe、标签、fold、费用、滑点和代码 commit 组合都产生不可变 `TrialRecord`。失败试验也记录。任何自动调参或 RD-Agent 提议必须先申请 trial budget，并在 Deflated Sharpe/PBO/多重比较中计入全部试验，而不是只计最后展示的模型。

Runner 不得访问最终 lockbox 标签；评估服务只返回预定义统计量。候选冻结后才允许一次性打开 lockbox，失败后如果继续修改，旧 lockbox 自动变为普通验证集，并创建新的未来 lockbox。

## 8. 从预测到目标仓位

### 8.1 四步目标，而不是概率乘仓位

```text
BaseTarget(d)                   日线预测先经基础组合优化得到隔夜权重
TPlan/OverlayTarget(t)          分钟预测结合 BaseTarget 与当前批次产生临时 delta
ReconciledTarget(t)             合并工作中订单、多个 sleeve 与账户事实后的唯一目标
RiskAdjustedExecutableTarget(t) 风险层裁剪并标出当前可达/不可达部分
```

对标的 `i`：

```text
desired_weight_i(t)
  = clip(base_weight_i(d) + intraday_overlay_i(t), instrument/risk constraints)
```

组合层只消费经校准的 expected excess return、rank、uncertainty、协方差/风险暴露和成本模型。若模型只有 rank score，使用排名型组合基线，不伪造收益率尺度；若模型输出概率分布，先完成校准再进入优化。

权重转数量使用决策时已可见且由 `ValuationPolicy` 选出的价格、当前权益、lot/odd-lot 规则和确定性 rounding；不得使用未来成交价。`TargetReconciler` 先投影 `current lots + working buy - working sell`，再合并 sleeve，避免重复下单。硬风险与 Broker/账户事实优先级最高；Base 与 T 的相反指令先在账户内净额化，不制造自成交。

净额化不能抹掉经济归因。版本化 `LotDispositionPolicy` 决定每个卖出 fill 处置哪些 `PositionLot` 及其执行成本/已实现 PnL（税务处置仍由独立 `TaxProfile/TaxHoldingLot` 决定）；`PnLAttributionPolicy` 在 OrderIntent 生成前固定 Base/T/Risk 等 sleeve 的 allocation claims，并确定 partial fill、非线性最低佣金、税费、滑点、机会成本、rounding remainder 与 residual/`AttributionTransfer` 的分摊顺序。任一时点必须满足 `Σ sleeve position/PnL/cost = account position/PnL/cost`，政策 ID/hash 写入 RunManifest，成交后不得为美化某个 sleeve 追溯改分配。

### 8.2 组合构建候选

首批统一比较：

1. 等权/Top-K/Top-K Dropout（研究 sanity baseline）；
2. 波动率目标与风险预算；
3. Qlib `EnhancedIndexingStrategy`/risk model 基线；
4. 基于 CVXPY/cvxportfolio 思路的带交易成本、换手、跟踪误差、行业/标的/流动性约束优化；
5. 只有上述稳定后，才研究 DRL allocator/timing overlay。

生产优化器的目标函数和约束必须可审计，至少包含：

- 预测收益/超额收益；
- 因子/协方差风险与单标的、行业、板块暴露；
- 当前持仓到目标的真实预计交易成本；
- 换手、流动性、参与率、最小订单与现金缓冲；
- T+1 导致的不可达目标；
- 用户风险预算和账户限制。

优化器不可行时保留上一个安全目标，并允许确定性风险层减少**可卖**风险；禁止随机放松约束直到求解成功。

### 8.3 做 T 的正式语义

`Intraday T Sleeve` 必须在决策时标记，而不是成交后按相邻 SELL→BUY 猜测：

- `BASE_REBALANCE`：日线基础目标永久变化；
- `T_SELL_THEN_BUYBACK`：先卖开盘已结算底仓，计划在价格/信号满足时回补；
- `T_BUY_THEN_SELL_BASE`：先买临时仓，随后最多卖出开盘可卖底仓；
- `RISK_REDUCTION`：风险层减仓，不保证回补；
- `USER/MIRROR`：用户或外部账户行为，不归因给模型。

每个 sleeve 有独立预算、PnL、费用、滑点、机会成本和风险归因。若卖出后信号/风险不再允许回补，订单可以转为 `BASE_REBALANCE` 或取消回补，但必须留下状态迁移原因；不能为了让报表出现“做 T 成功”而强制买回。

做 T 的最大可卖量由开盘结算批次和当前挂单预占共同决定；最大回补量受现金、目标上界、lot/tick、流动性、成本门槛和风险约束。策略没有净成本后优势时保持不动。

每次做 T 建立一等 `TPlan`，而不是两笔松散订单：

```text
PLANNED → LEG1_RESERVED → LEG1_ACTIVE → LEG1_PARTIAL/FILLED
        → LEG2_ACTIVE → LEG2_PARTIAL/FILLED
        → COMPLETED / ABORTED / RESIDUAL_OVERNIGHT
任一非终态 ──断线/重启/未知回报──→ RECOVERING ──对账后──→ 原状态或上述终态
```

`TPlan` 固定 `planned_qty`、两腿累计成交量、活动子单、预占与重试 lineage，并始终满足 `0 <= leg2_filled_qty <= leg1_filled_qty <= planned_qty`、`residual_qty = leg1_filled_qty - leg2_filled_qty`。`T_BUY_THEN_SELL_BASE` 还必须满足 `leg2_filled_qty <= reserved_opening_qty`；第二腿上限为 `min(leg1_filled_qty, reserved_opening_qty)`。第一腿 partial 后可按 policy 分批激活第二腿，但不得卖出尚未由第一腿成交覆盖的计划量。

`T_BUY_THEN_SELL_BASE` 在第一腿提交前以 `SecurityReservation(owner_kind=TPLAN)` 独占相应开盘可卖 lots，防止 Base、其他 TPlan 或策略重复预占；生成第二腿 BrokerOrder 时，预占必须在同一事务中由 `TPLAN` 转移为 `ORDER`，不能新建一份重复预占。取消/重试产生新子单 identity，但沿用同一 TPlan 和剩余数量；已确认终态子单才释放其 owner。硬风险接管也必须先原子转移 reservation，再中止 TPlan/撤销冲突余单，不能绕过现有 reservation 直接双重下单。

三个终态互斥：`COMPLETED` 要求 `residual_qty=0`、全部子单终态、reservation=0 且满足冻结的 completion policy；`ABORTED` 要求全部子单终态、reservation=0，并且 `residual_qty=0`，或正 residual 已通过同一事务的 `AttributionTransfer` 全量转入 Base/Risk sleeve；`RESIDUAL_OVERNIGHT` 表示 `residual_qty>0` 且尚未完成该转移。仍有活动/UNKNOWN 子单或 reservation 时只能处于非终态 `RECOVERING`，不能用 `ABORTED` 隐藏残仓。

`T_SELL_THEN_BUYBACK` 未回补时必须形成显式 `RESIDUAL_OVERNIGHT`、基础目标变更或风险减仓归因。`T_BUY_THEN_SELL_BASE` 的正 `residual_qty` 则是未卖出的临时增仓；两者都不能被报成 `COMPLETED`。停牌、跌/涨停、临近收盘、断线或进程恰在两腿间重启时，从 journal 恢复同一 TPlan，默认不为完成报表而追价。

## 9. A 股 RuleBook、批次持仓与真实费用

### 9.1 RuleBook 是有生效期的数据，不是代码常量

上交所、深交所 2026 修订版交易规则自 2026 年 7 月 6 日起施行；上交所通知同时明确部分条文继续暂缓实施。因此不能把“文档已生效”直接等同于“每一条都已实施”。历史回放必须加载交易日当时实际有效的条款集合，Paper/Mirror 加载当前已审批版本。`RuleBookSnapshot` 至少覆盖：

- venue、board、asset type、instrument effective interval；
- T+0/T+1 或其他回转规则；
- 交易时段、集合竞价、连续竞价、盘后交易和撤单禁限时段；
- 买入/卖出申报单位、零股、单笔数量上限；
- tick size、价格舍入；
- 涨跌幅、新股无涨跌幅期、风险警示/退市状态；
- 连续竞价价格笼子和有效申报范围；
- 停复牌与不可交易状态；
- 通用规则与股票、基金/ETF、板块等补充业务规则的优先级；
- 每条规则的 `ACTIVE/DEFERRED/SUSPENDED` 状态、来源、发布日期、生效/失效日期和 hash。

若某标的在某交易日找不到唯一适用规则，正式回放与运行 fail closed。

静态 `RuleBook` 与当日动态事实必须分离：前者保存公式、申报单位、回转类别和条款状态；`InstrumentSessionSnapshot` 由真实 API 保存当日前收盘、实际涨跌停价、ST/停牌、新股阶段、当日可交易状态与来源。静态公式不能凭今天的证券状态重算整段历史，动态字段缺失也不能用“通常规则”猜测。

独立 `CashSettlementRule` 至少声明 `cash_settlement_lag`、卖出所得何时可交易/可取、入出金可用时点、结算日历、账户/Broker override、来源、生效区间和 hash。普通沪深现金账户的公共基准可表达“卖出所得当日可继续交易、下一结算日才可取”，但这只是带证据的默认 scenario，不能扩展成全部 ETF、申赎或特殊账户常量。

### 9.2 批次/结算桶持仓

统一账本至少维护证券与现金的独立结算桶：

```text
settled_qty               已完成证券结算的剩余数量
unsettled_qty             尚未完成证券结算的剩余数量
rule_sellable_qty         当前按 RuleBook/动态状态允许卖出的剩余数量
non_sellable_qty          因 sellable_at 未到或司法/质押/公司行动等锁定的数量
security_reserved_qty     全部活动 SecurityReservation 的数量（独立投影）
reserved_sellable_qty     reservation 与当前 rule_sellable lots 的交集
available_to_new_sell     扣除交集预占后可供新卖出意图使用的数量
sold_today                当日卖出数量及来源批次（journal 投影，不属于剩余持仓）
settled_cash              已完成资金结算的现金
unsettled_receivable      已记账、尚未完成结算的应收
unsettled_payable         已记账、尚未完成结算的应付
eligible_trade_cash       按规则当前可交易的现金基数
eligible_withdrawable_cash 按规则当前可取的现金基数
buy_order_reserved_principal 活动买单预占的最坏成交本金
cash_fee_reserved         按 BrokerFeeProfile 须由当前现金承担的活动订单最坏费用
contingent_tax_cash_reserved 活动卖单按 policy 必须由当前现金预覆盖的或有补扣税
contingent_tax_receivable_haircut 从预期卖出所得中先扣除的有证据或有税上界（不占当前现金）
pending_withdrawal_cash   已申请但尚未完成的出金预占
tax_outstanding           已确认且尚未清偿的税负总额
tax_cash_reserved         已从当前现金额度中锁定、等待实际扣收的税负
unpaid_tax_liability      因可扣资金不足而尚无现金覆盖的已确认税负
base_trade_cash           扣除订单、费用、税与出金预占后的交易现金
cash_available_to_trade   当前可用于新买单的投影视图
cash_available_to_withdraw 当前可转出的投影视图
corporate_action_pending  尚未生效的证券、现金和税务权益
```

证券“是否完成交收”、“规则是否允许卖出”和“是否被某 owner 预占”是三个正交投影，不能用一个 `settled/available` 布尔值或互斥总桶代替。交易内生成的 `PositionLot(origin_kind=TRADE_ACQUIRED)` 记录 acquisition fill、交易日、剩余数量、单位成本、独立的 `security_settlement_at`、`sellable_at`、锁定原因和公司行动 lineage；合格 T+0 品种可处于 `unsettled` 但已 `rule_sellable`，普通 T+1 股票当日买入则通常二者都未到。

Broker/MIRROR opening 若只有聚合持仓而无逐笔成交历史，只能建立 `OPENING_BALANCE_LOT(source_snapshot_id, acquisition_fill_id=null, acquisition_time=null, broker_reported_cost?, sellability_evidence, pnl_fidelity=INCOMPLETE)`，不能伪造一笔 opening fill 或取得日期。后续若导入合格交割历史，通过 append-only `LotReconstructionEvent` 建立真实 lots 并 supersede 该 opening projection，历史报表仍保留原 fidelity；在闭合前，依赖精确成本的 realized PnL 不能作为唯一发布证据。

`SecurityReservation` 记录 `reservation_id`、lot/数量、`owner_kind=ORDER|TPLAN|RISK|CORPORATE_ACTION`、owner identity、状态和转移 lineage；同一 lot 单位在任一时刻最多一个活动 owner。reservation 创建后若 lot 因公司行动、司法锁定或 Broker 对账变为不可卖，它仍保留到 owner 被确认 `CONSUMED/RELEASED/TRANSFERRED`，但不再计入 `reserved_sellable_qty`，相关订单/TPlan 进入取消或恢复流程；不得因 sellability 改变就提前释放或把预占悄悄迁到另一 lot。

剩余库存也不能替代证券交收义务。每个 fill 另建不可变 `SecuritySettlementObligation(obligation_id, direction=RECEIVE|DELIVER, quantity, settle_at, status, source_fill_id, netting_group, netting_rule_id)`；只有版本化市场/Broker 规则允许时才能净额结算，并保留净额前后 lineage。T+0 买入后同日卖到零库存时，RECEIVE/DELIVER 两条腿或其合规净额记录仍保留到 `ApplySecuritySettlement` 完成，不能因 `PositionLot.remaining_qty=0` 消失或在结算日生成幽灵持仓。

`eligible_trade_cash`、`eligible_withdrawable_cash`、应收/应付与税务字段都必须由带 `trade_available_at/withdrawable_at/settle_at` 的不可变 cash journal 投影，不能作为可被业务代码独立改写的资产桶。卖出所得是否可当日再买、何时可取由账户/市场 `CashSettlementRule` 决定，不能把 `cash_available_to_trade` 与 `cash_available_to_withdraw` 合成一个字段。汇总 `quantity`、`available_quantity` 和 average cost 只是投影视图，不再是状态真相。

每次状态转换后必须满足并记录不变量：

- `total_qty = settled_qty + unsettled_qty = rule_sellable_qty + non_sellable_qty = Σ PositionLot.remaining_qty`；结算与 sellability 是对同一库存的两个正交分区；
- `security_reserved_qty = Σ active SecurityReservation.remaining_qty` 是第三个独立投影；`reserved_sellable_qty` 是 reservation 与 `rule_sellable_qty` 的 lot-level 交集，`available_to_new_sell = rule_sellable_qty - reserved_sellable_qty`，且任何策略、TPlan 或订单不能重复预占同一 lot 单位；
- `tax_outstanding = tax_cash_reserved + unpaid_tax_liability`，三者非负；已支付税额不再留在任一 outstanding 字段；
- `base_trade_cash = eligible_trade_cash - buy_order_reserved_principal - cash_fee_reserved - contingent_tax_cash_reserved - tax_cash_reserved - pending_withdrawal_cash >= 0`；`contingent_tax_receivable_haircut` 只降低对应卖单的 projected net receivable，不能再从当前现金重复扣除；
- `cash_available_to_trade = 0 if unpaid_tax_liability > 0 else base_trade_cash`；
- `cash_available_to_withdraw = 0 if unpaid_tax_liability > 0 else max(0, min(base_trade_cash, eligible_withdrawable_cash - contingent_tax_cash_reserved - tax_cash_reserved - pending_withdrawal_cash))`，所以 `0 <= cash_available_to_withdraw <= cash_available_to_trade`；
- 证券、现金和费用 journal 的借贷/增减合计守恒，除明确的入金、出金、公司行动和税费事件外不得凭空变化；
- `cash_available_to_trade >= 0`、所有 reservation 非负且不超过其来源 lot/现金余额；
- 快照可以加速读取，但必须能从 append-only events/journal 重建出完全相同的订单、批次、现金和权益 digest。

买单提交前必须原子预占“未成交数量的最坏合法成交金额 + 本 FeeChargeUnit 按政策须由当前现金承担的最坏费用”，partial fill 后重算余单。卖单费用若按 Broker 规则从成交所得净额扣除，则不占用当前现金，但必须在应收中先扣除最坏费用；若要求当前现金承担，则进入 `cash_fee_reserved`。订单处于提交结果未知、撤单中或对账中时不得提前释放；只有 Broker/Matcher 已确认终态且余单不存在，才能释放剩余预占。

必须通过的底仓情景：

1. 昨日持有 1000，今日买 1000：今日最多仍只可卖 1000；
2. 昨日持有 1000，先卖 500 再买 500：期末 1000，其中 500 可卖、500 当日冻结；
3. 昨日持有 1000，先买 500 再卖 1000：允许，期末剩余当日买入 500 且不可再卖；
4. 今日从零买入 500：同日卖出拒绝（适用 T+1 品种）；
5. 目标降为 0 但含冻结量：生成“当前可达目标”，剩余量标记 `UNREACHABLE_T1`，不能假装已清仓；
6. 对规则允许当日回转的 ETF/品种，按 instrument RuleBook 处理，不能仅按“ETF”三个字统一判断。
7. 当日买入合格 T+0 品种：证券可以仍为 `unsettled_qty`，但同时进入 `rule_sellable_qty/available_to_new_sell` 并允许同日卖出；卖到零库存后 RECEIVE/DELIVER obligations 或合规净额记录仍存在，结算完成后不得产生幽灵持仓。

### 9.3 FeeProfile 与订单级费用累计

费用来源优先级：

1. 券商/账户 API 或真实交割单核验后的 `BrokerFeeProfile`；
2. 用户明确配置、带生效日期的账户费率；
3. 交易所/中国结算/税务规则形成的公共 scenario；公共 scenario 不得显示为“用户实际费率”。

`FeeRule` 按账户、venue、instrument class、side、日期和 order/fill scope 匹配，支持：

- 券商佣金与最低佣金；
- 证券交易印花税；
- 过户费；
- 经手/规费是否已包含在佣金；
- ETF/基金/债券等豁免或独立规则；
- 金额精度、四舍五入和补差时机；
- 基准、压力和实际三套 cost scenario。

最低佣金由显式 `FeeChargeUnit/FeeAccumulator` 决定，默认一个被 Broker 接受的 `BrokerOrder` identity 是一个计费单元，而不是策略 `OrderIntent`。一个目标被拆成多个 Broker 子单时，除非真实费率/交割单证明可合并，否则每个子单分别适用最低佣金；同一 Broker order 多次 partial fill 才按累计成交额只应用一次最低额。取消后重报默认产生新单元；replace 是否沿用、Broker algo parent 是否聚合，只能由 `BrokerFeeProfile` 证明。零成交拒/撤单默认不收成交佣金，部分成交后撤单按该单元最终成交额结算。

`FeeRule` 是可复用政策，只固定 `commission_scope`、`charge_timing`、`rounding_scope`、适用条件和费率，不携带某笔订单的 `fee_charge_unit_id`。提交前以本地 `client_order_id/broker_child_id` 建立 provisional FeeChargeUnit 并完成费用预留；收到 `OrderAcceptedEvent` 后幂等绑定 `venue_order_id`（LIVE 为真实 `broker_order_id`），不得重建累计器或重复应用最低佣金。ACK 未知时保留 provisional unit 与 reservation，Rejected/零成交终态按 policy 关闭为 0。

费用累计器区分 `EstimatedFee`、`ReservedFee` 与 `ActualBrokerFee`：每次 fill 后计算应新增费用，提交时保守预留，终态按 `BrokerFeeProfile` 进行补差/返还，不能统一假设“每 fill 收最低额”或“只在最后才收费”。

印花税、过户/结算/经手费等按其真实 scope 逐项记录；分红所得税等持有期相关扣税以独立 `CorporateActionTaxEvent` 进入账户，不伪装成交易佣金。每个 fill 保存费用分项与规则 ID，订单保存累计/补差，账户现金流水保存最终可与 Broker API/交割单对账的金额。

### 9.4 公司行动与分红税

公司行动至少拆成 `CorporateActionEvent`、`CorporateActionEntitlement`、`TaxHoldingLot` 与 `DividendTaxAssessment`。`PositionLot` 服务 T+1、库存和成本；`TaxHoldingLot` 按账户级税务规则服务持有期、日终净增减与 FIFO，二者不能偷懒共用一套 execution lots。

Broker opening 聚合持仓通常不能证明税务取得日期。`TaxLotImportPolicy` 必须优先导入并核对可用的历史成交、交割、分红与补扣记录；仍无法闭合的开盘数量只能建立 `UNKNOWN_TAX_LOT(acquisition_time=null, evidence_ids, unknown_reason)`，绝不能用 opening date、平均成本日期或最有利持有期伪造。

最保守税率本身不足以得到金额。每份未知 lot 还要建立 `ConservativeDividendTaxExposure(tax_base_amount_or_bound, base_method, entitlement/evidence_ids, max_applicable_rate, amount_bound, collection_source, fidelity)`：opening 导入时它只是或有 exposure，不进入 `tax_outstanding`。REPLAY、PAPER 与 MIRROR simulation fork 在虚拟卖单提交前，按可证明的历史分红税基上界、最保守税率和冻结的 `TaxCollectionPolicy` 分流：`FROM_SELL_PROCEEDS` 形成订单级 receivable haircut；只有 Broker/账户证据明确要求预先从当前现金覆盖时，才形成 `contingent_tax_cash_reserved`。

提交阶段也必须使用与 fill 同构的非负公式：`projected_paid_from_proceeds_bound = min(projected_gross_proceeds, contingent_tax_exposure_bound)`，`projected_net_receivable = projected_gross_proceeds - projected_paid_from_proceeds_bound >= 0`，`projected_contingent_shortfall_bound = contingent_tax_exposure_bound - projected_paid_from_proceeds_bound >= 0`。前两者形成 `contingent_tax_receivable_haircut` 与净应收投影；在 `FROM_SELL_PROCEEDS` 下，shortfall bound 只进入风险/压力披露，不能变成提交前 current-cash 门槛，fill 后才按实际 assessment 进入 current-cash/unpaid 分支。

fill 发生时，按实际成交比例释放对应 contingent exposure 并生成 `DividendTaxAssessment`。`FROM_SELL_PROCEEDS` 先计算 `paid_from_proceeds = min(gross_receivable, assessment_amount)`、`net_receivable = gross_receivable - paid_from_proceeds >= 0`；若 `residual_tax = assessment_amount - paid_from_proceeds > 0`，再按 policy 从 current cash 覆盖，仍不足才进入 `unpaid_tax_liability` 并冻结买入/出金。当前现金扣收分支同样转成 `tax_outstanding/tax_cash_reserved|unpaid_tax_liability`，任何分支都不能生成负 receivable/现金。终态未成交余量释放。只有 `BrokerObservedAccount` 的真实外部成交与 LIVE 账户使用 Broker 实扣对账。

若历史交割、分红或 entitlement 证据无法形成有限税基上界，状态为 `TAX_BASE_UNKNOWN`：Formal REPLAY/PAPER/MIRROR 不得生成一个伪精确税后 cash/PnL；需要单值账户状态的虚拟卖单 fail closed，只允许在明确的探索模式输出带上界未知标记的区间。报告标记 `tax_fidelity=CONSERVATIVE_UNKNOWN_LOT` 或 `TAX_BASE_UNKNOWN`，都不能作为精确税后收益的唯一发布证据。

生命周期为：股权登记日固化 entitlement → 除权/派息或股份上市事件入账 → 建立或有税负 → 后续转让时按当时有效 `TaxProfile` 评估 → 生成 assessment → Broker/模拟扣税写独立现金 journal。`FROM_SELL_PROCEEDS` 的 assessment 在成交 batch 中先按上述 `min` 公式抵扣，只有 residual tax 才进入 current-cash/outstanding 分支；未结部分原子拆成 `tax_cash_reserved + unpaid_tax_liability` 并立即重算两个 cash-available 投影。不存在“税已确认但既未抵扣所得、也未占用额度”的窗口，也不能把 outstanding 与 unpaid 重复计负债。

对 current-cash/outstanding 分支实际扣收时，同一 journal 事务同时减少 eligible cash、`tax_cash_reserved` 与 `tax_outstanding`；后续入金用于清偿时，先把相应 `unpaid_tax_liability` 原子转入 reserve/支付，再恢复交易额度。全过程不能为了平账制造负 `cash_available_to_trade`。MIRROR/LIVE 按 Broker 返回进入 `DEGRADED_READ_ONLY` 或 `HALTED` 并持续对账，REPLAY/PAPER 按冻结的 `TaxCollectionPolicy` 处置；任何模式都不能丢弃税负或虚构入金。

个人、机构、基金和特殊证券分别配置。当前个人投资者公共 scenario（2015-09-08 起）按账户日终净增减与先进先出计算：持股不超过 1 个月实际税负 20%，1 个月以上至 1 年 10%，超过 1 年暂免；1 年以内派息时暂不扣，转让时再按最终持有期扣收。它必须作为带来源/生效期的 policy，不写死在成交费用函数；Live/Mirror 以交割单实际扣税为最终对账事实。

## 10. 统一执行与回放语义

### 10.1 事件顺序

每个交易日先按版本化 `DailyLifecyclePolicy` 完成账户开闭日；任何一步失败都不进入 `READY`：

```text
TradingDayOpen
→ ExpirePreviousDayOrders
→ ApplyCorporateActions
→ ApplySecurity/CashSettlement
→ BrokerReconcile（适用时）
→ SealOpeningSnapshot
→ AccountReady / AcceptNewDecisions
...
TradingDayClose
→ ExpireDayOrders
→ FinalReconcile
→ MarkToMarket
→ SealDailyJournal
```

一次正式决策/成交必须满足：

```text
MarketEvent received
→ DataAvailable
→ FeatureComputed
→ AlphaForecast
→ TargetPortfolio
→ RiskDecision
→ OrderIntent
→ OrderSubmitted(after configured latency)
→ OrderAcceptedEvent / Rejected
→ PartialFill(s)/Cancel/Expire
→ FeeAccrual + Lot/Account Journal
→ MarkToMarket
```

同一时间戳事件使用固定 priority 和 sequence；运行清单记录时钟、latency 和排序版本。不能由 Python 容器遍历顺序决定结果。

### 10.2 订单状态机与冻结

订单不能把生命周期、待处理动作和对账状态硬塞进一个线性枚举；至少使用三个正交状态轴，并另设账户就绪状态：

```text
OrderLifecycle:
  CREATED | SUBMITTING | ACK_PENDING | WORKING | PARTIALLY_FILLED |
  FILLED | CANCELED | EXPIRED | REJECTED | REPLACED | UNKNOWN

PendingAction:
  NONE | CANCEL_PENDING | REPLACE_PENDING

OrderSyncState:
  IN_SYNC | RECONCILING | DISCREPANT

AccountReadiness:
  BOOTSTRAPPING | RECONCILING | READY | DEGRADED_READ_ONLY | HALTED
```

`CANCEL_PENDING`/`REPLACE_PENDING` 期间余量仍冻结；CancelRejected 只清待处理动作并返回原工作状态。撤单中到达 fill 先按 execution time/sequence 入账，全部成交时 `FILLED` 胜出；`CANCELED` 可以带已有 `cumulative_filled_qty`。发送超时进入 `UNKNOWN + RECONCILING`，不得盲目重发。只有已确认终态，或对应运行模式同一 watermark 的全量对账证明余单不存在，才能释放预占。

`OrderAcceptedEvent` 是领域事件而不是第四个持久状态轴：它把 `SUBMITTING/ACK_PENDING` 推进为 `WORKING`，并原子记录 `acceptance_source=MATCHER|BROKER`、`accepted_at`、`accepted_sequence`、venue order identity 与 provisional FeeChargeUnit 绑定。后续 fill 必须因果晚于该事件；REPLAY、PAPER 与 MIRROR simulation fork 都由 simulated venue/matcher 生成同构 Accepted，只有 LIVE 订单使用去重后的 Broker 回报。`BrokerObservedAccount` 只摄取外部真实订单/成交事件，绝不能把它们冒充为 simulation fork 的 acceptance 或 fill。

Gateway ingress 必须把原始到达顺序与规范化因果顺序分开保存。若 LIVE/MIRROR 先收到 fill callback、重连时只看到成交，或 ACK 丢失，原始回报先以 `PendingExecutionReport(raw_received_sequence, execution_id, raw_hash)` 进入 `RECONCILING`，全部 reservation 保持不变，不能丢弃、猜测归属或直接越过 Accepted。只有后续 ACK、权威订单查询或同一 Broker watermark 的订单/成交证据闭合后，才能先补录带 `acceptance_evidence` 的 `OrderAcceptedEvent`，再分配 `causal_apply_sequence` 并按 `execution_id` 恰好一次过账 fill；迟到 ACK 只幂等补全 identity/timestamp，不重建订单、费用单元或成交。始终无法证明归属的回报保持 `DISCREPANT/HALTED`，由全量对账生成 `RecoveredExternalOrder` 或补偿分录后才可恢复 READY。

重连时账户先进入 `RECONCILING`。LIVE 的资金、持仓、活动订单、成交必须与同一 Broker watermark 一致；MIRROR 则维护两个不可混写的账本：`BrokerObservedAccount` 只记录 Broker 事实并与四表 1:1 对账，`MirrorSimulationFork` 从某个已对账 anchor snapshot 出发，只记录虚拟 orders/fills。MIRROR 的 READY 条件是 observed ledger 与 Broker 一致，且 overlay 自身在固定 matcher/event watermark 下可重放；`MirrorProjectedAccount = anchor + admitted external events + simulation overlay` 只是派生的反事实视图，本来就不要求等于当前 Broker 账户。REPLAY/PAPER 没有 Broker watermark，必须以固定输入 snapshot、matcher/event watermark、journal 尾序列和本地四表投影一致为 READY 证据。

Broker 或 matcher 快照都不能直接覆盖 journal；差异生成带来源的 `ReconciliationRecord`，修正只能用冲正/补偿分录。`RECONCILING/DISCREPANT` 禁止新增风险，只允许有证据的撤单或安全动作。

订单/journal 还必须满足：

- `requested_qty = cumulative_filled_qty + open_remaining_qty + terminal_unfilled_qty`；
- `security_reserved_qty = Σ all active SecurityReservation.remaining_qty`；其中 `order_sell_reserved_qty = Σ owner_kind=ORDER` 只是子投影，不能漏掉 TPLAN/RISK/CORPORATE_ACTION owner；
- `buy_order_reserved_principal = Σ nonterminal buy orders.worst_case_remaining_principal`，不包含费用；`cash_fee_reserved = Σ active FeeChargeUnit.current_cash_worst_case_fee`，两者不得重复累计；
- 每个 `execution_id` 最多过账一次，每个 journal batch 借贷平衡，已过账分录不可修改；
- 每个终态 `FeeChargeUnit` 的 posted fee 等于其累计 fills 在固定 `FeeRule` 下的最终金额，终态订单预占为 0；
- `AccountReadiness=READY` 时必须保存 `ReadinessEvidence`：LIVE 对应同一 Broker watermark 的四表快照；MIRROR 同时包含 observed/Broker 对账证据与 simulation fork 的 anchor、matcher/event/journal watermarks；REPLAY/PAPER 对应固定 matcher/event watermark 与 journal 投影。不得要求 MIRROR 的反事实 projected account 等于 Broker，也不得用不适用于该模式的空 watermark 伪造 READY。

状态按 exchange/broker event time、source sequence 与因果关系单调归并，不能按本机到达顺序覆盖。幂等键只能防重复提交，不能代替 Broker order id、exchange order id 和 execution id 去重。

### 10.3 撮合分级

| Matcher | 数据 | 用途 | 保守要求 |
| --- | --- | --- | --- |
| `BAR_CONSERVATIVE` | 日/分钟 OHLCV | 正式低/中频基线 | 下一 bar 才可成交；停牌无成交；量能参与率；锁死涨跌停默认不成交；不能从 OHLC 路径猜队列 |
| `QUOTE_TOUCH` | Tick/一档 | Paper 与实时影子 | 买用 ask、卖用 bid；检查行情年龄、价差、可见量、延迟 |
| `DEPTH_AWARE` | 多档盘口 | 更高精度 Paper/Replay | 消耗共享盘口深度、部分成交、冲击和跨订单竞争 |
| `QUEUE_REPLAY` | 逐笔委托/成交/队列 | L2 研究 | 明确队列模型、撤单、延迟和不确定性；可借鉴 hftbacktest |
| `BROKER_REPORT` | 券商回报 | 未来 Live | 不模拟成交，只以去重后的真实回报推进账本 |

`BAR_CONSERVATIVE` 必须把下一 bar 拆成两个因果阶段，不能用收盘后才知道的量反填开盘成交：

1. `BarOpenEvent` 只暴露当时已知的 open/集合竞价事实。只有 API snapshot 含带独立可见时间的集合竞价成交量、开盘累计量或等价 opening-capacity 证据时，才允许按冻结的 opening participation cap 在 open 价格加不利滑点后成交；没有该证据时 Formal 默认 open fill capacity 为 0。历史量预测只能用于下单 sizing，不能冒充成交证据。
2. `BarCloseEvent` 才暴露完整 OHLCV/最终 volume。共享 `bar_total_budget` 扣除已经由 opening evidence 成交的数量后分配其余 partial fills；这些 fill 的 `execution_time` 不早于 bar close。若有真实 VWAP/窗口数据，按冻结 policy 加不利冲击；只有 OHLC 时使用 close/不利边界或结果区间，不能仍按 open 价成交。
3. `BarCloseEvent` 不得修改、扩充或回溯任何已记录 open fill；低开高走、大成交量和收盘后修订都不能把开盘可见量为 0 的大单伪装成 open 成交。

Bar 回放必须同时输出 base/stress 场景。若只有 OHLCV，报告不能使用“精确成交”措辞；对同一 bar 内先高后低还是先低后高未知的策略，采用保守路径或区间结果。

同一 `instrument + market event + scenario` 只有一个全账户流动性预算，按订单 `accepted_time/source_sequence` 在 Base、T、Risk 和多策略之间共享，不能让每个策略各自获得 5%。完整 bar 的最终 volume 只能在 `BarCloseEvent` 限制截至 close 的累计成交，不能用于决策 sizing 或反填 `BarOpenEvent`；事前参与率只能使用已可见历史量或冻结预测量。partial fill 是否跨 bar 延续由 TIF/expire policy 决定，活动余单持续预占。

`FillPricePolicy` 必须显式区分 market/limit、开盘跳空、价格改善、limit touch 与滑点：Quote/Depth market order 使用下一可观察 ask/bid 加不利滑点；Bar market order 只能按上述 Open/Close 两阶段各自允许的价格与容量成交。limit order 不因 OHLC 极值就获得优于委托价的虚构成交；无 bar、停牌或不满足 touch/队列条件即不成交。任何 fill 必须满足 `submit_time >= decision_time + configured_latency`、发生在 `OrderAcceptedEvent` 之后，并引用 sequence 晚于 `accepted_sequence` 的市场事件。

### 10.4 四种模式如何共核

| 模式 | 时钟/行情 | 成交来源 | 账户起点 | 核心状态机 |
| --- | --- | --- | --- | --- |
| `REPLAY` | 不可变历史事件；manifest 固定 AS_DELIVERED/PIT_STRICT | 选定 matcher | 自定义/历史 opening snapshot | `astraquant_execution` |
| `PAPER` | 真实 API 实时事件 | Quote/Depth matcher | 本地模拟账户 | 同一内核 |
| `MIRROR` | 真实 API 实时事件 + 连续只读 Broker 对账 | Quote/Depth matcher，仅写 simulation fork | 已对账的 Broker observed snapshot 作为不可变 anchor | 同一内核；observed 与 simulation overlay 分账，绝不发送真实委托 |
| `LIVE` | 真实行情 + Broker | Broker reports | Broker 对账快照 | 同一 lot/account journal；matcher 被 report adapter 取代 |

回放结束默认只做 mark-to-market，不假装清仓。若用户选择 liquidation scenario，生成显式平仓订单并受 T+1、停牌、量能和费用限制；不能直接把市值加到现金。

MIRROR 不能假定导入开盘持仓后用户不会在外部交易。若无法连续读取 Broker 资金/持仓/订单/成交，则必须显式声明 `NO_EXTERNAL_CHANGE` 假设并在检测到差异时 halt；有连续能力时，每个 run 必须冻结 `MirrorExternalChangePolicy`。默认 `SEAL_AND_REANCHOR`：检测到 anchor 之后的外部成交/资金/公司行动时，在最后共同 watermark 封存旧 simulation fork，先完成 observed 对账，再从新 Broker snapshot 启动新 fork。可选 `INJECT_AS_USER_EVENT` 只有在事件能按原始因果顺序进入 fork、释放/冲正冲突 reservation 且全部不变量仍成立时才允许；否则自动退回封存重锚。两种方式都保留旧 run，不静默覆盖，不把虚拟 fill 写进 `BrokerObservedAccount`。

### 10.5 RQAlpha 差分与其他交叉验证

RQAlpha 作为主要 executable oracle，重点复用/验证：

- `closable = quantity - today_non_closable - unfilled_close` 类 T+1 可卖量；
- 同一 `FeeChargeUnit` 跨 fills 的最低佣金累计；RQAlpha 的 `other_fees=0`，所以它不裁判过户费、完整规费或真实 Broker rounding；
- 涨跌停、停牌、bar/tick 成交量参与率、partial fill 和滑点；
- 目标仓位在冻结量存在时的可达性。

差分不是要求所有框架整段收益完全相同。先构造最小 canonical scenarios，对状态、拒单原因、可卖量、现金、费用、成交上限和订单终态做精确比较；组合级结果在相同 matcher 假设下比较。差异必须通过 ADR 解释并附交易所规则或 Broker 实际对账证据。

WonderTrader 用于 T1 frozen/目标仓位的局部交叉；Hikyuu 用于费用/组合构件参考；vn.py 用于真实 Gateway 事件映射与回报重放。它们的简化 Paper/回测组件不被当成账户真相。

### 10.6 ValuationPolicy

权益、回撤和风险必须固定 `ValuationPolicySnapshot`：盘中估值 mark 可优先使用未陈旧的 quote mid 或 last，日终优先使用交易所/API 官方收盘，但 mark 不是可成交价；清算/风险压力另用多头 bid、未来空头 ask 加 side-specific impact/haircut。停牌或无最新价使用最后一个已验证价格并标记 `STALE`，同时报告 haircut/stress scenario，不能填充成可成交报价。公司行动通过 journal 调整证券/现金后再估值，禁止同时复权价格和加现金造成双计。每个 mark 保存价格来源、时间、陈旧度、haircut、FX（若未来适用）和 policy hash。

## 11. 风控架构

风控是确定性 policy，不由 alpha 模型或 LLM 改写。它接受模型建议但只能保持或降低风险，不能因为“置信度高”绕过账户/市场硬约束。

### 11.1 Pre-trade 硬门

- 行情、RuleBook、FeeProfile、instrument/status 和 model artifact 新鲜且 hash 匹配；
- 决策未过期，`decision_time < earliest_execution_time`；
- 交易时段、停牌、T+1/T+0、lot/tick、价格上下限与价格笼子合法；
- 现金/证券/订单预占充足，不重复使用已冻结资源；
- 单标的、行业、主题、组合、账户和 sleeve 上限；
- 订单 notional、参与率、ADV、价差、冲击和容量上限；
- 当前权益、当日亏损、回撤、波动率与 kill-switch 状态；
- MIRROR/LIVE 中外部持仓和未完成订单已经完成对账。

### 11.2 Continuous/Post-trade

- 实际成交价、滑点、费用和 partial fill 与已批准 scenario 的偏差；
- 账户现金、持仓批次、冻结量和 Broker/Paper journal 不变量；
- 单日/滚动亏损、回撤、暴露、流动性和集中度；
- feature/score distribution、coverage、模型 IC/校准（标签成熟后）与 concept drift；
- T sleeve 是否偏离基础目标、临近收盘无法回补和隔夜风险；
- 数据中断、乱序、时钟回退、重复事件、撮合/对账差异。

### 11.3 安全动作

风险动作按权限分级：

1. `HOLD_NO_NEW_ORDER`：停止新增风险，保留已有订单或按 policy 撤单；
2. `CANCEL_OPEN_ORDERS`：撤销可撤活动单；
3. `REDUCE_SELLABLE_RISK`：只减少当前可卖/可平风险，不承诺 T+1 冻结仓可立即退出；
4. `DISABLE_SLEEVE/MODEL`：原子切回上一已批准 champion 或无模型 HOLD；
5. `HALT_ACCOUNT`：停止账户新指令，等待人工对账。

推理失败时不得暗中切换到一个未经同一数据、费用和发布门批准的规则策略。默认 fallback 是 HOLD，不是“可能还能赚钱”的旧模型。

## 12. 统一验证协议

### 12.1 切分与泄漏控制

1. 全 universe 使用同一时间轴切分，不能先把不同证券拼成数组再按行号切。
2. 外层 chronological walk-forward 是最终权威；内层 purged CV/valid 只做特征、超参、阈值和校准选择。
3. Purge 删除所有 `label interval [t0,t1]` 与 valid/test 相交的训练样本；embargo 由 label horizon、执行延迟和依赖政策计算，不固定为“5 行”。
4. scaler、填补、winsorize、行业中性、特征选择、early stopping、stacking 和 DoubleEnsemble 二层输入只能在 fold 内拟合；stacking 使用 out-of-fold 预测。
5. universe、行业/概念、停牌、规则、费率和公司行动全部以 decision point 的 PIT snapshot join。
6. 最终 lockbox 只揭盲一次；任何揭盲后的修改都会使该 lockbox 失效并计入 Trial Ledger。
7. Feature/Label materialization 必须从不可变祖先重算时间血缘；验证器拒绝早于祖先 `visible_time`、工件可见时间、处理延迟、退出完成或 grace window 的伪造时间戳。

初始 `SplitPolicy v1`：

| 任务 | Train | Inner valid | Outer OOS/步长 | 发布限制 |
| --- | --- | --- | --- | --- |
| 日线横截面 | 滚动 5 年 | 1 年 | 下一季度，按季度滚动；另聚合半年/年度报告 | 必须覆盖多个市场状态与足够 PIT universe |
| 分钟 OHLCV（数据成熟后） | 120 交易日 | 20 日 | 下一 5-20 日，与预声明重训频率一致 | 当前约 51 日只能 25/5/5 初筛与 Shadow，不得称跨状态生产级 |
| L2 | 至少 60 日起步 | 10 日 | 下一 5 日 | 仅为启动下限；最终由有效独立样本/MinTRL 门决定 |

窗口不是永恒常数，但必须在候选比较前由 `SplitPolicy` 冻结。修改 split 会创建新实验族，并将此前所有尝试计入多重检验。

### 12.2 公平比较

- 同一 dataset/snapshot、FeatureSpec/LabelSpec、fold、universe、RuleBook、FeeProfile 和 matcher；
- 同类模型相同 HPO trial、wall-clock/GPU、seed 和 early-stop 预算；
- 开源模型固定 repository commit、dependency lock 和 checkpoint hash，运行时禁止隐式下载 latest；
- 预训练模型分开报告 zero-shot、冻结骨干/线性头、LoRA 和全量微调；
- 对预训练模型保留晚于 checkpoint 发布/训练截止的 post-release holdout，降低预训练污染风险；
- 所有指标按 fold、seed、板块、流动性和市场状态展示分布，不只展示一条全期曲线。

### 12.3 指标

**预测层：** IC/Rank IC、ICIR/Rank ICIR、校准、Brier/NLL（概率模型）、分位数 coverage、预测分布和稳定性。AUC/准确率只作诊断。

**组合层：** gross/net return、相对 benchmark 与无技能/线性/LightGBM incumbent 的 active return/IR、Sharpe/Sortino/Calmar、最大回撤/恢复期、turnover、持仓/行业暴露、tail loss 和收益集中度。

**执行层：** fill rate、partial/cancel、implementation shortfall、spread/impact/fee、每单位换手净收益、参与率、容量 AUM 曲线、延迟和行情陈旧敏感度。

**做 T 归因：** Base、T sleeve 和 Risk Reduction 按冻结的 `LotDispositionPolicy/PnLAttributionPolicy` 计算独立 PnL；卖出腿、回补腿、未回补机会成本、费用/滑点、隔夜偏离和对基础目标的增量贡献。全部 sleeve 汇总必须回到账户 journal；禁止用事后相邻交易分类或事后挑 lot 代替决策归因。

### 12.4 成本、延迟与容量压力

每个正式报告至少运行：

- 用户实际 `BrokerFeeProfile`；
- 法定税费/过户费按各情景交易日真实规则重算，不机械乘倍数；
- base/adverse/severe：对不确定的 Broker 佣金、spread、impact、队列与滑点分别使用冻结参数（初始可为 1×/1.5×/2×），每个组件单独披露；
- 在合法最早成交之后额外 0/1/2 bar（或对应毫秒）延迟；
- 可成交量/参与率收紧场景；
- 涨跌停、停牌、缺 bar、断线和修订故障场景；
- 规模递增的 AUM/capacity 曲线。

初始容量 policy 建议把 P95 单笔限制在**决策时已完成的历史分钟量或冻结预测量**的 5%、ADV20 的 1%，并压力到 10%/5%；未来实际 bar volume 只能在 matcher 中限制成交结果，不能反向用于订单 sizing。这些值在发布前冻结，之后用真实 Paper/Broker fills 校准，不宣称为市场常数。

### 12.5 统计与 `ReleasePolicy v1`

在第一轮候选结果出现前冻结以下初始门槛；改变门槛需 ADR，且不能回头选择性拯救某个模型：

- 外层 OOS 总净收益、median fold 净收益为正，至少 70% folds 为正；
- 相对主要 incumbent 的配对净指标差值，按交易日 block bootstrap 的 95% 下界大于 0；
- `PSR(SR_net > 0) >= 0.95`、Deflated Sharpe probability `>= 0.95`；
- PBO/CSCV `<= 0.20`，作为候选族脆弱性门；
- 对模型族运行 White Reality Check/SPA，显著性 `p <= 0.05`；
- base 与 adverse 成本下满足收益/风险门，severe 下不得突破硬风险预算；
- 任一预声明板块、流动性层或市场状态出现结构性失败，不能由全期均值掩盖；
- 最大回撤、单日损失、集中度和 capacity 满足用户冻结的风险预算。

CPCV 用于生成 OOS 路径分布和脆弱性检查，不替代 chronological walk-forward。分钟 bar 数不能被当成独立样本数量虚增显著性；PSR/MinTRL 使用合适频率的组合收益和自相关处理。

`ReleasePolicy` 是机器可执行 artifact，不能留下“主要”“足够”“结构性”等自由文本判断。它至少固定：`incumbent_model_id`（候选运行前指定）、全部计划 folds 与失败 fold 的计数规则、`candidate_family_id`（同一 target/universe/split 下 Trial Ledger 的全部成功/失败尝试）、bootstrap 方法/block length/repetitions/seed、`RegimeSpec` 及每层最小观察数、PBO/SPA denominator、全部收益/回撤/容量阈值和缺失结果处理。预声明层样本不足时结论是 `INSUFFICIENT_EVIDENCE`，不能从分母中删除；任何字段仍为占位符时发布服务 fail closed。

## 13. 模型注册、Shadow、Paper 与回滚

### 13.1 状态机

```text
DRAFT → OFFLINE_VALIDATED → SHADOW → PAPER_CANARY → CHAMPION
  └──────────────→ QUARANTINED / RETIRED
```

每个 `ModelVersion` 不可变并固定：

- artifact/checkpoint/processor hash；
- repository commit、dependency lock、运行环境和硬件信息；
- 全部 raw/snapshot/dataset/feature/label/split/cost/rule IDs；
- trials、seeds、fold predictions、报告、解释和批准记录；
- serving schema、latency budget、适用 universe/sleeve 与风险 policy；
- predecessor/challenger/champion 关系。

`champion` 是原子 alias，不是可变模型行；至少保留前两版及其完整环境，可一键回滚。回滚只改变 alias/运行配置，不覆盖历史决策。

### 13.2 Shadow 与 Paper v1 门

- Shadow 与 champion 消费完全相同的 live event IDs；candidate 只能写预测、目标和模拟订单，不改正式 Paper/Mirror 账本。
- 同时满足：至少连续 20 个交易日；至少 200 个可执行决策机会；若 PSR 推导的 minimum track record length 更长则继续到该长度；无法覆盖预声明状态时继续观察。
- 推理成功率 `>= 99.9%`；特征、预测、目标和状态重放 digest 一致率 100%；未来数据、陈旧输入下单和规则违规均为 0。
- 1 分钟策略初始 p99 端到端决策延迟 `< 5s`，随后按真实行情频率/策略期限收紧；日线策略在下一 session cutoff 前完成。
- Paper canary 初始使用计划规模的 10%，至少连续运行 10 个交易日且累计 100 个可执行机会；运行、对账、成本和风险硬门全部通过后才能扩大，证据不足则延长。任何模型、特征、阈值、RuleBook 或 FeeProfile 改变都会创建新版本并重置观察。
- 项目尚未单独批准 Live 前，`CHAMPION` 只代表 Paper/Mirror champion，不代表可用真实资金。

Shadow/Paper 主要证明在线特征、运行语义、延迟、成本和对账稳定，不用 20 天在线表现替代长期 alpha 证据。经济优势仍以锁定 OOS、可证明的 PIT 部分和持续 forward 结果共同决定。

### 13.3 自动隔离/回滚触发

- artifact、snapshot、schema、calendar、rule、fee 或 dependency hash 不匹配；
- 检出时间泄漏、同 bar 成交、T+1/lot/tick/涨跌停违规；
- 账户 journal 不平、重复/漏成交、Broker/Paper 对账失败；
- 输入陈旧、coverage/feature drift 与绩效共同恶化；
- 在 `ReleasePolicy` 固定的最小 fill 数和窗口内，P95 实际滑点超过已批准 severe 上界；
- 连续两个不重叠、长度由 `ReleasePolicy.performance_window_sessions` 固定的成熟标签窗口，其 PSR/校准/净优势低于 policy；
- 损失、回撤、暴露或 capacity 硬限触发。

正确动作是 `HOLD + no-new-orders`、撤活动单或原子回滚到上一 champion；不能在故障时现场训练、改阈值或自动启用未批准模型。

## 14. 核心契约与运行清单

### 14.1 必需契约

| 契约 | 关键字段 |
| --- | --- |
| `ProviderApproval/CaptureEnvelope` | vendor/product/endpoint/build/permission/schema、request/raw hash、received、qualification |
| `DatasetSnapshot` | snapshot/content/raw hashes、evidence、vintage/PIT policy、coverage、quality、parents、publication proof |
| `FeatureSnapshot` | FeatureGraph/processor、input snapshot IDs、as-of/available、online parity digest |
| `LabelSpec` | entry/exit/horizon/matures-at/benchmark/tradability/cost/time semantics |
| `AlphaForecast` | model/feature、有效期、expected/rank/quantiles/uncertainty/lineage |
| `BaseTarget/TPlan/TargetPortfolio` | base/T/risk targets、planned/leg/residual qty、working-order projection、reservation lineage、constraints、unreachable reasons |
| `RuleBook/InstrumentSessionSnapshot` | clause status、instrument/date/session/T+N/lot/tick/limit/cage/dynamic facts/source/hash |
| `CashSettlementRule/CashSnapshot` | journal-derived trade/withdraw availability、receivable/payable/reservations、tax liability、calendar/source/hash |
| `FeeProfile/FeeChargeUnit` | account/instrument/date/side、scope、charge/rounding、estimated/reserved/actual、source/hash |
| `CorporateAction/TaxHoldingLot/TaxExposure` | entitlement、record/ex/pay、holding/FIFO、tax base/bound/fidelity/collection source、cash reserve/receivable haircut、assessed/paid/unpaid tax、source/hash |
| `OrderIntent/Order/Fill` | sleeve、target delta、OMS/Broker/execution ids、三个状态轴、reservation、fee lineage |
| `PositionLot/AccountJournal` | origin/opening snapshot 或 acquisition、remaining、settlement/sellable、cost/PnL fidelity、cash/debit-credit、event/reversal lineage |
| `SecurityReservation/SettlementObligation` | owner/lot/transfer/status、receive/deliver/settle/netting/source fill lineage |
| `LotDispositionPolicy/PnLAttributionPolicy` | lot selection、sleeve claims/priority、partial/fee/slippage/remainder/residual allocation、effective/hash |
| `ReconciliationRecord/ReadinessEvidence` | source kind、Broker 或 matcher/event watermark、四表 hashes、difference、compensation、readiness |
| `RiskPolicy/ValuationPolicy` | limits/actions、price priority/staleness/haircut、source/hash |
| `ReleasePolicy` | incumbents/folds/family/bootstrap/regimes/thresholds/sample/seed/version |
| `RunManifest` | code/env/input/config/randomness/event-order/matcher/vintage/policy hashes、run class |

### 14.2 决定性

相同 sealed inputs、code/env、RunManifest 与 seed 必须产生相同：

- Feature/Label/Forecast digests；
- TargetPortfolio 与 OrderIntent；
- 订单状态、fills、费用、lots、现金和权益 journal；
- 指标、报告和最终 run digest。

浮点模型允许按预声明容差比较 tensor/score，但最终离散订单、Decimal 现金、批次数量和状态必须精确一致。GPU 非决定算子存在时要明确记录并禁止其模型进入要求精确复现的生产路径，或改用确定性实现。

## 15. 故障、可观测性与审计

### 15.1 Fail-closed 矩阵

| 故障 | 行为 |
| --- | --- |
| API 断线/数据陈旧/时间倒退 | 停止新预测与订单；继续展示陈旧标记和可证明的账户状态 |
| schema/单位/coverage 改变 | Capture quarantine，不发布新 snapshot |
| RuleBook/InstrumentSession/Fee/Tax/Settlement/Valuation policy 缺失或冲突 | 相关 instrument 禁止新订单；无法可靠估值时账户降级并显式标陈旧 |
| Feature parity/hash 失败 | 隔离模型，HOLD，不切未批准 fallback |
| 优化器不可行 | 保留上一安全目标；只允许硬风险减少可卖风险 |
| matcher/oracle 差分失败 | 阻断相关版本晋级，保存最小复现 trace |
| journal 不平/重复回报/对账失败 | 账户 halt，重放日志并人工核对 |
| 模型漂移/绩效退化 | 进入 Shadow/Retired 或回滚上一 champion，不在线改参 |

### 15.2 每个决策可追溯

界面中的每个 B/S/目标变化都必须能追到：

```text
API raw response → snapshot → feature rows → model/version → forecast
→ optimizer/constraints → risk decision → order intent → order/fill
→ fee/lot/cash journal → PnL attribution
```

解释不只显示 SHAP/特征贡献，还要显示“为何当前目标是这个数”“哪些约束裁掉了多少仓位”“为何不可卖/未成交”“实际成本与预期差多少”。

## 16. 实施顺序与阶段退出条件

本文是设计基线，不是逐文件 Implementation Plan。用户确认后，必须用 `superpowers:writing-plans` 另写可执行计划。计划顺序固定为：

### Phase 0：隔离不可信旧证据

- 旧快照/模型/回放标记 `LEGACY_UNVERIFIED` 或 `LEGACY_SEMANTICS`；
- 修正所有正式入口的 run/evidence gate；
- 建立 P0 最小失败测试，防旧结果继续被发布。
- 现有 Paper 账本封存为只读 legacy，不把标量历史伪造成 lots；经现金/持仓/活动单/成交核对后只导入一次性 opening snapshot，新旧绩效分段展示。

退出：没有旧样例/混源/未 pin snapshot 能进入 formal run。

### Phase 1：真实 API 证据链与 RuleBook

- ProviderQualification、Capture、canonical、vintage/PIT modes、stable digest、publication ledger、recursive hash、coverage 与质量门；
- 不复权事实/公司行动/历史 universe/status；
- 日线全量、分钟分块增量；
- 2026 当前/暂缓条款与历史规则版本，另建动态 `InstrumentSessionSnapshot`。

退出：100% formal inputs 按角色递归可追到合格真实 API/official rule；AS_DELIVERED 与 PIT_STRICT 不可互相改名升级；同一 snapshot 可验证复现。

### Phase 2：统一交易内核

- 在写状态转换前先从固定 RQAlpha 版本、官方规则和 Broker 契约冻结 canonical scenarios、golden traces 与期望不变量；
- lots/settlement/cash/reservations、TPlan、OMS 三轴状态、FeeChargeUnit、公司行动税、RuleBook、matchers、valuation、journal；
- REPLAY/PAPER/MIRROR 切到同一内核；
- 修正 decision/fill clock、期末权益和无信号盯市。

退出：T+1/做 T/费用/partial/limit/suspension canonical scenarios 全部通过，账本不变量成立。

### Phase 3：开源语义差分

- 对 Phase 2 golden cases 做完整 RQAlpha 精确/不变量差分，并固定 oracle trace hash；
- WonderTrader/Hikyuu/vn.py 局部 replay adapters；
- Broker 回报契约与对账 fixture。

退出：所有差异有机器结果和 ADR；无未解释的资金/持仓/可卖量差异。

### Phase 4：研究平台与无争议基线

- `astraquant_research`、FeatureGraph、LabelSpec、Trial Ledger、walk-forward/lockbox；
- Qlib/vnpy.alpha runners；
- no-skill、Ridge/Lasso、LightGBM、XGBoost/CatBoost 基线。

退出：真实 API 日线数据上形成可重复的基线矩阵；Qlib/vnpy 对共同模型的输入/输出差异可解释。

### Phase 5：日线冠军与目标组合

- DoubleEnsemble/GRU/TCN/TRA/HIST/MASTER 等分阶段 challenger；
- 风险模型、组合优化、BaseTarget；
- Shadow/Paper promotion。

退出：至少一个候选通过全部 offline 与 forward gates；若无人通过，安全结论是“暂无可发布模型”。

### Phase 6：分钟做 T 覆盖层

- 持续积累分钟数据；
- 专用分钟 baselines/sequence/TSFM challengers；
- 两种做 T 顺序、目标不可达、sleeve attribution 和收盘偏离风险。

退出：足够独立真实历史 + forward Paper；净增量收益在成本/延迟压力和全部 T+1 情景下成立。

### Phase 7：L2 与未来 Live

- 数据权限与连续 L2 捕获先行；
- OFI/queue 基线后再 DeepLOB/TLOB；
- vn.py TORA/XTP 等仅作 gateway，真实 Broker reports 驱动账本；
- Live 必须另立审批、权限、风控与熔断设计。

退出：不属于本文自动授权范围，必须单独经用户批准。

## 17. 最终验收矩阵

| 验收项 | 硬门 |
| --- | --- |
| Formal 原始行情/参考对象为合格 `REAL_API_*`；特征/标签为 `DERIVED_REAL_API` 且其市场/参考祖先全部合格 | 100% |
| 非白名单、样例、fixture、AKShare 或未知祖先进入 formal | 0 |
| provider schema 变更、成功码静默截断、重复/遗漏分页、历史值修订的故障注入 | 100% 被 quarantine 或发布为新 vintage，不静默通过 |
| Manifest/全部文件 hash、ancestor chain、append-only publication proof 在 formal read 时校验 | 100% |
| 未 pin snapshot 的 formal train/replay/model | 0 |
| `REPLAY_AS_DELIVERED` 报告缺 data vintage/占比，或被标成 `PIT_STRICT` | 0 |
| 2010 bar 在 2026 首次抓取、随后再修订 | `AS_DELIVERED` 可按 nominal 时间回放且披露 vintage 风险；`PIT_STRICT` 在 `first_received_time`/修订证明时间前拒绝该精确版本；Paper 在真实接收前拒绝；旧决策不被新修订回写 |
| `feature.available_time > decision_time`，或 Feature/Label 时间早于任一祖先、工件、处理延迟、退出完成/grace window | 0 |
| `label_matures_at > training_cutoff` 的样本进入任何拟合/选择 | 0 |
| Live/Paper/MIRROR 任一对应账本在 `observed_received_time > decision_time` 时消费事件 | 0 |
| `submit_time < decision_time + configured_latency`、fill 早于 `OrderAcceptedEvent`/earliest execution、`accepted_sequence` 之前成交或 same-bar close fill | 0 |
| LIVE 原始回调顺序为 fill→ACK；或重连只发现 fill | 先进入 Pending/RECONCILING 并保留预占；证据闭合后 Accepted→fill 因果应用，`execution_id` 只过账一次；无法闭合则 DISCREPANT/HALTED |
| 下一 bar 开盘可见 capacity=0，低开高走且最终 volume 很大，大额订单跨 Open/Close | open fill=0；最终 volume 只能约束 close 阶段且不得回填 open 时间/价格；结果符合冻结的保守价格 policy |
| 同 instrument/event 全账户 fills 超过共享流动性预算 | 0 |
| 当前/历史 RuleBook 条款或动态 InstrumentSessionSnapshot 缺失/暂缓却仍交易 | 0 |
| T+1、`unsettled-but-sellable` 合格 T+0 品种、两种底仓做 T、不可达目标、两腿 partial/取消/重试/重启/跨日/公司行动 | 数量不变量成立；终态订单与 reservation 全部归零；100% 通过 |
| TPlan 预占可卖 lot 后，该 lot 被公司行动/司法/Broker 事实锁定且撤单仍 pending | settlement、sellability、reservation 三投影分别守恒；预占不提前释放，锁定量不再可成交/供新卖单使用 |
| 合格 T+0 品种同日买 100、卖 100 至零库存，随后证券交收 | RECEIVE/DELIVER obligations 或合规净额 lineage 完整；结算完成后库存仍为 0，无幽灵持仓 |
| MIRROR opening Broker 持仓 1000，虚拟单经 matcher Accepted→partial/fill 卖出 100 而 Broker 订单表不变；随后出现真实外部成交 | observed 始终与 Broker 对账，projected 可为 900 且 overlay 可重放；虚拟事件不污染 Broker 四表；外部变化严格按冻结 policy 注入或封存重锚，不产生假 discrepancy |
| Base 卖 100、T 买 60 先内部净额，净卖单再 partial fill；跨多个 PositionLot 且触发最低佣金/rounding/residual transfer | lot disposition 与各 sleeve 数量、费用、滑点、PnL 完全由冻结 policy 决定；各 sleeve 汇总与账户 journal 精确相等 |
| 卖出所得当日可交易、下一结算日可取，覆盖周末/节假日与 Broker override | 与 `CashSettlementRule` 精确一致 |
| 一个 BrokerOrder 三次 fills、一个 strategy parent 拆两单、部分成交撤单、零成交撤单、replace | `FeeChargeUnit`、最低佣金、税/过户/rounding 与 policy/Broker 证据一致 |
| 分红税持有期、账户级 FIFO/日终净增减、卖出补扣、确认到扣收窗口与资金不足 | `tax_outstanding = reserved + unpaid`，不重复计负债、不产生负现金；不足时交易/出金额度立即为 0；与版本化 `TaxProfile`/Broker 证据一致 |
| opening 聚合持仓没有 execution/acquisition 历史，但历史分红税基上界可由 entitlement/交割证据证明；MIRROR fork 虚拟卖出 | 创建 `OPENING_BALANCE_LOT + UNKNOWN_TAX_LOT + ConservativeDividendTaxExposure`；提交时按 collection policy 形成 sell-receivable haircut 或 current-cash reserve，fill 时才按成交比例转 assessment；Broker observed 不变，伪造成交/日期或 opening 即确认税负为 0 |
| current cash=0、持有可卖旧股且有已知分红补扣 exposure，发出允许从卖出所得扣税的风险卖单 | 卖单可提交/成交；当前现金预占为 0，projected/gross sell receivable 先扣 tax haircut 后入账；不得因或有税错误阻断减仓 |
| current cash=0 且实际补扣税大于本笔 gross sell proceeds | `paid_from_proceeds=min(gross, tax)`、net receivable=0，残余进入 `unpaid_tax_liability` 并冻结买入/出金；负 receivable、负现金或税负丢失均为 0 |
| 卖单提交时 `contingent_tax_exposure_bound > projected_gross_proceeds` 且 collection source 为卖出所得 | projected haircut 以 gross proceeds 封顶、net receivable=0，shortfall 只进入压力披露；提交前 current-cash 预占=0，fill 后再按实际 assessment 分流 |
| opening lot 的历史分红税基无法形成有限证据上界 | 标记 `TAX_BASE_UNKNOWN`；Formal 单值虚拟卖出 fail closed，探索报告只给不完整区间；不得用“20%×未知”伪造 reserve 或确定税后 PnL |
| 停牌、涨跌停封板、量能、无 bar、撤单交叉、重复/迟到回报 | 100% 通过 |
| 提交超时、CANCEL_PENDING fill、断线重连四表对账 | 不提前释放预占；不重复过账；差异不静默覆盖 |
| 停牌/陈旧价/公司行动日 mark-to-market | `ValuationPolicy` 可追溯，无复权/现金双计 |
| 固定输入/config 的离散订单、账本和 run digest | 100% 重现 |
| Offline statistical/economic/cost/capacity gates | 全部通过，任一失败不晋级 |
| Shadow/Paper 数据、推理、规则和重放 gates | 全部通过 |
| 任何收益能追到 raw→model→order→fill→PnL | 100% |

## 18. 明确不做

- 不在现有 `replay.py` 上继续叠加复杂模型并把结果称为正式证据；
- 不用开源样例行情、示例模型成绩或公开预训练 benchmark 证明 Astra 有 alpha；
- 不整体迁移到 RQAlpha/Hikyuu/vn.py/FinRL-X 并接受它们的缺口；
- 不把所有 ETF 都写成 T+1 或 T+0；
- 首期不实现融资融券、做空、ETF 申赎、北交所或港股通交易；这些范围不得复用沪深现金账户默认值，须单独设计后启用；
- 不把今天的费率、成分、ST/停牌和规则回填整段历史；
- 不按同一 bar close 决策并成交；
- 不把强制期末清仓藏在 final cash；
- 不按交易后相邻 SELL→BUY 猜做 T 归因；
- 不因模型复杂、预训练或论文新就绕过线性/树模型和真实成本基线；
- 不让 RD-Agent、LLM、HPO 或 UI 访问/反复试探最终 lockbox；
- 不在故障时自动启用未批准 fallback 或自动发送真实委托。

## 19. 文档治理

本文确认后：

1. 新写完整 Implementation Plan，旧 v2 计划标记 superseded，不在原计划上继续打补丁；
2. 更新 `docs/research/quant-core-learning-guide.md`，明确它当前只描述 legacy demo；
3. 更新 `docs/architecture/paper-trading-ledger.md`，删除过时默认费率和标量持仓真相；
4. 更新 `docs/research/open-source-comparison.md`，加入 RQAlpha/Hikyuu/WonderTrader/QUANTAXIS、vnpy.alpha、FinRL-X 和 TSFM 的最新定位；
5. 每个架构差异和 ReleasePolicy 变化写 ADR；
6. 实施代码、文档、测试和真实本地产物按逻辑阶段独立提交，数据/模型/密钥仍不进 Git。

## 20. 一手来源

### 开源框架与模型

- [Qlib 官方仓库](https://github.com/microsoft/qlib)
- [Qlib A 股模型 benchmark（含 20 seeds 与 Alpha158/Alpha360；本次审计提交）](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/examples/benchmarks/README.md)
- [Qlib LightGBM Alpha158 官方固定切分配置（本次审计提交）](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml)
- [Qlib PIT 数据库](https://qlib.readthedocs.io/en/stable/advanced/PIT.html)
- [Qlib Enhanced Indexing（本次审计提交）](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/examples/portfolio/README.md)
- [vn.py / vnpy.alpha 官方仓库](https://github.com/vnpy/vnpy)
- [vn.py 4.4.0 发布记录](https://github.com/vnpy/vnpy/releases/tag/4.4.0)
- [RQAlpha 官方仓库](https://github.com/ricequant/rqalpha)
- [RQAlpha 6.3.0 T+1 持仓源码（固定提交）](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/rqalpha/mod/rqalpha_mod_sys_accounts/position_model.py)
- [RQAlpha 6.3.0 费用源码（固定提交）](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/rqalpha/mod/rqalpha_mod_sys_transaction_cost/deciders.py)
- [RQAlpha 6.3.0 bar matcher（固定提交）](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/rqalpha/mod/rqalpha_mod_sys_simulation/matcher/bar_matcher.py)
- [Hikyuu 官方仓库](https://github.com/fasiondog/hikyuu)
- [WonderTrader 官方仓库](https://github.com/wondertrader/wondertrader)
- [QUANTAXIS 官方仓库](https://github.com/yutiansut/QUANTAXIS)
- [hftbacktest 官方仓库](https://github.com/nkaz001/hftbacktest)
- [FinRL 官方仓库](https://github.com/AI4Finance-Foundation/FinRL)
- [FinRL-X 官方仓库](https://github.com/AI4Finance-Foundation/FinRL-Trading)
- [RD-Agent 官方仓库](https://github.com/microsoft/RD-Agent)
- [Chronos-2 官方仓库](https://github.com/amazon-science/chronos-forecasting)
- [TimesFM 官方仓库](https://github.com/google-research/timesfm)
- [Moirai / Uni2TS 官方仓库](https://github.com/SalesforceAIResearch/uni2ts)
- [IBM Tiny Time Mixers / Granite TSFM 官方仓库](https://github.com/ibm-granite/granite-tsfm)
- [DoubleEnsemble 原论文](https://arxiv.org/abs/2010.01265)
- [TRA 原论文](https://arxiv.org/abs/2106.12950)
- [HIST 官方实现](https://github.com/Wentao-Xu/HIST)
- [MASTER 官方实现](https://github.com/SJTU-DMTai/MASTER)
- [PatchTST 官方实现](https://github.com/yuqinie98/PatchTST)
- [iTransformer 官方实现](https://github.com/thuml/iTransformer)
- [DeepLOB 原论文](https://arxiv.org/abs/1808.03668)
- [TLOB 原论文与官方实现](https://github.com/LeonardoBerti00/TLOB)

### 数据、规则与费用

- [东财掘金 `gm` Python SDK 行情查询（history/current/复权参数）](https://emt.18.cn/api/quant-help/python/python_select_api_history.html)
- [东财掘金 `gm` Python SDK 数据订阅与事件](https://emt.18.cn/api/quant-help/python/python_subscribe.html)
- [东财掘金 `gm` Python API 介绍](https://emt.18.cn/api/quant-help/python/python_basic.html)
- [上交所交易规则（2026 修订，2026-07-06 生效）](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)
- [深交所交易规则（2026 修订）](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)
- [上交所收费一览表](https://www.sse.com.cn/services/tradingservice/charge/ssecharge/)
- [深交所收费及代收税费标准](https://www.szse.cn/marketServices/deal/payFees/index.html)
- [中国结算上海市场收费及代收税费表（2025-06-30 更新）](https://www.chinaclear.cn/zdjs/fbzyls/202506/9d22b74d9f2e40edb67b44d1f6596f18/files/%E4%B8%8A%E6%B5%B7%E5%B8%82%E5%9C%BA%E8%AF%81%E5%88%B8%E7%99%BB%E8%AE%B0%E7%BB%93%E7%AE%97%E4%B8%9A%E5%8A%A1%E6%94%B6%E8%B4%B9%E5%8F%8A%E4%BB%A3%E6%94%B6%E7%A8%8E%E8%B4%B9%E4%B8%80%E8%A7%88%E8%A1%A8.pdf)
- [中国结算深圳市场收费及代收税费表（2025-06-30 更新）](https://www.chinaclear.cn/zdjs/fbzyls/202506/ab6384ba25514554a7eceaee3e521032/files/%E6%B7%B1%E5%9C%B3%E5%B8%82%E5%9C%BA%E8%AF%81%E5%88%B8%E7%99%BB%E8%AE%B0%E7%BB%93%E7%AE%97%E4%B8%9A%E5%8A%A1%E6%94%B6%E8%B4%B9%E5%8F%8A%E4%BB%A3%E6%94%B6%E7%A8%8E%E8%B4%B9%E4%B8%80%E8%A7%88%E8%A1%A8.pdf)
- [财政部、税务总局 2023 年第 39 号证券交易印花税公告](https://fgk.chinatax.gov.cn/zcfgk/c102416/c5211343/content.html)
- [中国投资者网投教材料：股票 T+1 与卖出资金当日可交易](https://www.investor.org.cn/xxzx/tjzl/tjnrgmjytx/bk/kj/jyxl_3455/202303/P020230307500878344055.pdf)
- [财税〔2015〕101 号：个人股息红利差别化所得税](https://tianjin.chinatax.gov.cn/11200000000/0300/030004/03000418/20260122140833589.shtml)
- [财税〔2012〕85 号：股息红利税持有期与扣收操作](https://tianjin.chinatax.gov.cn/11200000000/0300/030004/03000418/20260122140336284.shtml)

### 验证与回测过拟合

- [Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
- [Probabilistic Sharpe Ratio / Sharpe Ratio Efficient Frontier](https://www.davidhbailey.com/dhbpapers/sharpe-frontier.pdf)
- [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
- [White’s Reality Check](https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152)
- [Hansen：A Test for Superior Predictive Ability](https://doi.org/10.1198/073500105000000063)
- [Harvey–Liu–Zhu：多重检验与因子发现](https://www.nber.org/papers/w20592)
- [Romano–Wolf stepwise multiple testing](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-0262.2005.00615.x)

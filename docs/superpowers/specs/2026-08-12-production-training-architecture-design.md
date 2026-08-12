# AstraQuant 生产级统一训练架构设计

**日期：** 2026-08-12  
**状态：** 已批准，约束 Quant Core v3 全部后续阶段  
**目标：** 让 AstraQuant 从“单一二分类 demo”演进为可覆盖全市场、多任务、多周期、多市场状态，并最终产生可执行目标仓位的生产级训练系统。

## 1. 不可退让的最终目标

AstraQuant 不以“跑通某个模型”作为训练核心完成标准。最终系统必须形成以下闭环：

`真实全市场历史数据 → 多任务标签 → 共享市场表征 → 个股/行业/概念关系建模 → 市场状态路由 → 模型组合与不确定性 → 目标仓位 → A 股执行/风控 → Shadow/Paper/Live 反馈`

完成任何单个模型只能关闭对应 challenger，不得关闭训练核心总任务。训练核心只有在任务分层、关系建模、状态路由、模型组合、执行语义和上线反馈闭环全部完成后才能结束。

## 2. 训练范围

### 2.1 数据范围

- 训练数据来自 AstraQuant 已封存的真实 API snapshot，不使用开源项目附带样例数据替代真实行情。
- 首批可以用小 universe 验证工程正确性，但接口、数据结构和训练流程从第一天就必须支持任意股票、ETF、指数成分及历史 universe。
- 开源项目只提供模型、训练器、特征处理或验证思想；A 股数据、规则、费用、涨跌停、停牌、T+1、目标仓位和回放语义由 AstraQuant 掌控。

### 2.2 任务分层

训练系统必须支持彼此独立、可组合的任务，而不是把所有目标压进一个标签：

| 任务 | 主要输出 | 典型周期 | 在程序中的作用 |
|---|---|---|---|
| `BASE_TARGET` | 预期收益/上涨概率 | 日级、多日 | 形成基础选股与持仓方向 |
| `CROSS_SECTIONAL_ROTATION` | 截面排序分数 | 日级、周级 | 比较股票、行业和 ETF 的相对强弱 |
| `TREND` | 趋势持续概率/强度 | 多周期 | 控制顺势暴露与持仓周期 |
| `MEAN_REVERSION` | 回归概率/预期幅度 | 日内、短周期 | 捕捉超跌反弹和短期反转 |
| `INTRADAY_T` | 做 T 买卖机会与区间 | 分钟、L2 | 在底仓和 T+1 约束下改善持仓成本 |
| `RISK` | 波动、尾部风险、流动性风险 | 多周期 | 降仓、禁买、容量与止损控制 |

每个任务必须显式声明 `label`、预测周期、可见时间、分数语义、评价指标、可交易 universe 和执行假设。概率、预期收益、截面 rank、风险值不得混用同一个阈值。

## 3. 模型组织方式

### 3.1 共享主干，不按个股各训一套

默认采用全市场共享训练，使模型能够学习跨股票共性并扩大有效样本。证券代码、行业、概念、规模、流动性和市场状态作为特征或关系进入模型。只有在统一模型经稳定实验证明存在系统性盲区时，才增加轻量 specialist/adapter；不为每只股票维护独立模型。

### 3.2 专家模型与动态路由

系统逐步形成共享 backbone 加专家模型：趋势、反转、轮动、日内 T 和风险专家分别给出声明过语义的预测。`RegimeRouter` 根据市场状态、流动性、波动和模型近期可靠度分配权重；路由只能使用当时可见信息。

### 3.3 组合层是正式组件

模型输出不直接变成订单。`ForecastCombiner` 负责校准、冲突消解和不确定性；`PortfolioConstructor` 把组合预测转成目标仓位；执行核心再处理 T+1、费用、容量和成交约束。组合过程必须可回放、可解释、可版本化。

## 4. 开源方案吸收路线

以 Qlib 作为研究编排和公平比较骨架，但不把 Qlib 的数据、账户或 A 股执行语义当作生产真相源。

Challenger 顺序：

1. **DoubleEnsemble**：先建立可靠的树模型集成、样本重加权和特征选择基线。
2. **Kronos**：直接复用官方 `Kronos-base` 预训练权重，验证 K 线原生基础模型的 zero-shot 价格路径、预期收益、波动和不确定性；不从零重复预训练。
3. **StockMixer**：验证跨股票时序/截面混合是否稳定优于树模型。
4. **MASTER**：引入市场状态条件化和股票间关系建模。
5. **HIST**：引入行业/概念先验及潜在关系发现。
6. **TRA**：让样本按时间模式路由到不同预测器。
7. **DoubleAdapt**：处理滚动市场中的分布漂移和在线适应。

这是一条逐层增加能力的路线，不是“先做简单版就结束”。前一 challenger 的统一数据、切分、成本、日志和 gate 必须被后一 challenger 复用。

Kronos 保持为独立外部基础模型通道，不覆盖自有训练架构。其官方源码固定在 `external/Kronos`，AstraQuant 适配代码位于 `runners/kronos`；缺少权重或 runner 失败时，自有模型必须继续工作。只有 zero-shot 公平验证通过后，才允许开发 K 线图“核预测”按钮与概率路径图层；只有预测在跨时期、跨证券和执行成本后稳定，才允许将其输出转换为组合因子。Kronos 永不直接产生订单。

## 5. 公平实验与晋级规则

所有模型在相同 snapshot、universe、时间切分、label、费用、滑点、延迟、容量和随机种子预算下比较。最终 lockbox 不参与训练、选模或阈值调整。

模型至少通过：

- 跨时间、跨证券和跨市场状态稳定性；
- 扣除真实费用后的收益、回撤、换手和容量；
- 0/1/2 bar 延迟、滑点和参与率压力测试；
- 多随机种子及失败 trial 全记录；
- Shadow/Paper 的预测漂移、成交偏差和账户一致性。

允许结论为 `INSUFFICIENT_EVIDENCE`。不得因为某个复杂模型能训练或某次回测收益高就晋级。

## 6. 分阶段交付

### Stage A：统一训练协议与强基线

建立 `TrainingTaskSpec`、`ScoreSemantics`、统一数据导出、walk-forward 和 DoubleEnsemble challenger。目标是让不同模型能够在同一规则下接受训练和比较。

### Stage B：全市场共享表征

在 Stage A 的真实多标的评价链路完成后，先接入 Kronos zero-shot 独立 runner，再接入 StockMixer；完成动态 universe、证券/行业特征、缺失与停牌 mask，验证外部预训练表征和自有全市场共享训练。

### Stage C：关系与市场状态

接入 MASTER/HIST，建立行业、概念及可学习关系图，并引入市场状态条件化。

### Stage D：专门化、路由与漂移适应

接入 TRA/DoubleAdapt，形成任务专家、状态路由、滚动重训、漂移检测和回退机制。

### Stage E：组合与实盘反馈闭环

统一输出 `AlphaForecast`，经组合层和目标仓位层进入 A 股执行核心；Shadow/Paper 反馈成交、容量和漂移，达到发布门后才允许进入 Live 设计。

## 7. 对全部阶段的约束

- Phase 0–1：保证真实 API 数据、snapshot 和时间语义能支撑全市场共享训练。
- Phase 2–3：保证 label 与评估使用真实可执行价格、费用和 A 股账户语义。
- Phase 4：承担 Stage A–D 的研究训练平台与 challenger 公平竞赛。
- Phase 5：组合 forecast、目标仓位、发布状态机和 Shadow/Paper gate。
- Phase 6：实现独立的 `INTRADAY_T` 专家并与底仓任务协调。
- Phase 7：为关系/日内模型提供 L2 能力，但不得让无 L2 模型无法运行。
- macOS/Windows：只允许数据接入与运行环境不同；训练契约、artifact 和结果语义必须跨平台一致。

## 8. 参考实现

- [Microsoft Qlib](https://github.com/microsoft/qlib)
- [Qlib benchmark protocol](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)
- [DoubleEnsemble](https://arxiv.org/abs/2010.01265)
- [StockMixer](https://github.com/SJTU-DMTai/StockMixer)
- [MASTER](https://github.com/SJTU-DMTai/MASTER)
- [HIST](https://arxiv.org/abs/2110.13716)
- [TRA](https://arxiv.org/abs/2106.12950)
- [DoubleAdapt](https://github.com/SJTU-DMTai/DoubleAdapt)
- [Kronos](https://github.com/shiyu-coder/Kronos)

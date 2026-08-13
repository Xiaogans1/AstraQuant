# Quant Core v3 当前进度（2026-08-13）

> **长期完成标准：** 当前 no-skill、Logistic、LightGBM 与 Qlib LightGBM 只是统一实验协议的基线。训练核心按[生产级统一训练架构](../specs/2026-08-12-production-training-architecture-design.md)继续推进，只有多任务、全市场共享表征、关系建模、状态路由、组合决策和 Shadow/Paper 反馈全部闭环才算完成。

## 最终交付目标

AstraQuant 最终交付的不是“一个预测模型”，而是一套可持续训练与淘汰模型的 A 股决策系统：

1. 用真实、可锁定的全市场历史数据进行统一训练，不为每只股票各维护一套模型。
2. BaseTarget、轮动、趋势、反转、日内做 T 和风险任务各自产生语义明确的 forecast。
3. 共享模型、关系模型和专家模型经过市场状态路由与不确定性校准，组合成唯一目标仓位。
4. 目标仓位经过真实费率、T+1、涨跌停、停牌、流动性、容量和风控后才能形成委托。
5. 只有跨时间、跨证券、跨市场状态和 Shadow/Paper 前瞻验证持续成立的版本，才能申请实盘设计。

单个模型接入、单次回测盈利或某个 AUC 达标都不能关闭总任务。

## 训练主线控制表

| Stage | 当前状态 | 程序交付 | 进入下一阶段的硬门 |
| --- | --- | --- | --- |
| A 统一协议与强基线 | **完成** | exact snapshot、统一 score、walk-forward、真实执行评价、DoubleEnsemble | 不同模型能在相同数据/费用/切分下可重复比较 |
| B 全市场共享表征 | **v2 Batch 1 完成 / 待宽历史** | D1/D5/D10 截面标签、收益校准、统一目标组合；待真实宽历史与模型矩阵 | 跨证券与跨时期稳定，且扣费后优于简单基线 |
| C 关系与市场状态 | 未开始 | MASTER/HIST、行业/概念/潜在关系、regime conditioning | 关系输入无未来信息，跨 regime 改善可重复 |
| D 专家路由与漂移 | 未开始 | TRA/DoubleAdapt、任务专家、漂移检测、可靠 fallback | 路由可解释，失效时自动回退且不放大风险 |
| E 组合与发布闭环 | 未开始 | ForecastCombiner、唯一目标仓位、Shadow/Paper 反馈 | 成本、容量、回撤、漂移和账户一致性全部过门 |

**当前唯一主节点：** Stage B v2 Batch 1 已关闭；下一步直接扩展东方财富真实 A 股日线宽历史和动态 universe，物化同一套截面任务，然后先验证 Ridge/LightGBM 是否能学到稳定排序信号。标签不可学习时不启动 MASTER/StockMixer v2，以免把算力消耗包装成进展。

**Stage B v2 已批准方向：** 采用[全市场截面训练设计](../specs/2026-08-13-stage-b-v2-cross-sectional-design.md)。第一主战场改为真实 A 股日线动态 universe；统一训练 `D1/D5/D10` 的收益、截面 rank 和风险 heads；先通过 Ridge/LightGBM/DoubleEnsemble 标签可学习门，再让 StockMixer v2 与 MASTER 竞争。模型输出进入统一 rank-aware long-only 目标组合，不再把 rank score 当作固定收益阈值。

**刚刚完成：** [Stage B v2 Batch 1](2026-08-13-stage-b-v2-batch-1-label-portfolio.md) 已交付 D1/D5/D10 next-open 标签、inner-valid Huber 收益校准和统一 rank-aware long-only 目标组合。程序现在能回答“某日哪些股票在不同周期相对更强、校准收益是否为正、在 3% 单票和 20% 换手约束下目标仓位是多少”；这只是训练与组合语义闭环，不代表已经获得 alpha 或盈利证据。

**效率纪律：** 每个开发批次必须产生一种用户可理解的新增能力或明确淘汰结论；不以重复造基础设施代替策略结果，不降低门槛包装模型，不允许新模型绕过统一执行评价。

## 已完成

- Phase 0：49/49，旧 demo 数据、模型和 Paper 语义已隔离。
- Phase 1a：Tasks 1–6 已完成；真实 API 接入、资格、capture、batch 与后台任务可用。剩余真实 endpoint 最终 sign-off。
- Phase 1b：Tasks 1–4 已完成；canonical、时间可见性、coverage/quality、snapshot v2 可用。

## 当前开发

- 生产训练 Stage A：统一 task/score 契约、声明式 Qlib runner、DoubleEnsemble 接入和真实多标的 Task 4 均已完成。9 个 Eastmoney exact snapshots 的两次独立训练得到完全相同的 input/fold/prediction/report digests；DoubleEnsemble 扣费净收益 `-2.5082%`，Ridge 为 `-1.8550%`，两者均为 `NO_NET_EDGE`，因此不进入 Shadow/Paper。Stage A 的公平评价通道保留，训练核心继续推进。
- Kronos K 线基础模型：Tasks 1–5 全部完成。官方 `Kronos-base` 在 RTX 4060 Ti 上对 9 个 Eastmoney exact snapshots、40,437 个窗口完成两次逐字节一致的 CUDA 推理；统一执行结果为净收益 `-9.1663%`、4,257 笔、0/3 正收益 folds、最差单标的回撤 `29.84%`，正式状态 `NO_NET_EDGE`。工程能力保留，正式 UI/组合因子/Shadow/Paper 暂停，主线转入 StockMixer。
- StockMixer Stage B 首轮已完整收口：官方 `SJTU-DMTai/StockMixer@cce13598`、动态 universe panel、共享模型、train-only normalization、masked regression/ranking loss、inner-valid/purge/早停、pickle-free artifact 和统一执行 adapter 均已完成。相同 9 ETF exact 请求的 CUDA 训练与执行报告独立双跑逐字节一致。最终扣费净收益 `-4.0930%`、2,123 笔、胜率 `34.06%`、`0/3` 正收益 folds、最差单标的回撤 `14.99%`；正式状态 `NO_NET_EDGE`，不进入 Shadow/Paper，也不围绕本轮结果事后调参。
- Stage B v2 Batch 1 已完成：冻结 D1/D5/D10 next-open 标签矩阵、2.5% 双尾 train-only 极值掩码、inner-valid-only Huber 分数收益校准，以及 top 10%/最多 50 只/单票 3%/单边换手 20% 的统一 long-only 组合。退出开盘后的日内低点不会污染持有期风险标签；80 项批次与旧逻辑回归通过。下一批才接真实 A 股宽历史，当前不声称模型有效。

- Strategy Fast Lane S1：公平开源基线矩阵，6/6 已完成；同一 Eastmoney snapshot 可比较 no-skill、Logistic Regression 与 LightGBM 的 OOS 扣费净收益。
- S2a Qlib 公平对照：3/3 已完成；同一 Eastmoney 行集/folds 可在固定 commit 的独立 Qlib LightGBM runner 训练，再由 AstraQuant 统一按相同费率与阈值评分。
- S2b Alpha158 特征对照：已完成；固定 Qlib 官方 158 个表达式直接消费东方财富 raw bars，未使用 Qlib 示例数据或自写近似公式。
- 真实结果（snapshot `7ae18d...cbec`，159516.SZSE，1,500 OOS rows）：十特征 AUC/净收益 `0.53454/0.04359`，Alpha158 `0.52992/0.02229`；Alpha158 净收益低 `0.02130`，因此不替换现有十特征。
- S3 A 股可执行净收益：已完成；训练目标和成交统一为 next-open，资金按 100 股整数手、10 万元/折、当前持久化费率（万 2.5、最低佣金 0、ETF 免税费）、2 bps 滑点和 10% participation 顺序执行，重叠信号不重复使用现金。
- S3 真实结果（同 snapshot、1,500 OOS rows）：ASTRA10 仅执行 2 笔，净收益 `-0.9782%`、最大回撤 `2.9345%`；Alpha158 仅执行 1 笔，净收益 `+0.3571%`、最大回撤 `0%`。交易样本太少，结论是证据不足，不能据此替换或晋级模型。
- 两次 S3 报告 SHA-256 均为 `A27413872478A2FFFAB45604ED0F7B8D5A82A61666378FA86203F15D5DA35502`。
- S4 目标仓位与做 T：已完成；forecast 先形成不可变 BaseTarget，再按现金、整数手、活动委托预占和 T+1 可卖量解释当下能执行多少，避免直接把概率变成买卖按钮。
- S4 真实模型状态：ASTRA10 仅 2 笔、Alpha158 仅 1 笔，均低于 30 笔证据门槛；程序保留当前目标并输出 `INSUFFICIENT_EVIDENCE/HOLD`，不伪选“最佳模型”。
- S4 canonical 场景：实际持仓 2,000、规则可卖 1,000、目标 0 时，只提出卖出 1,000，剩余 1,000 明确为 `T1_FROZEN`；sell-first 做 T 受已有预占限制为 800，buy-first 做 T 受现金限制为 500。
- 两次 S4 目标规划报告 SHA-256 均为 `343DAC4F35EEFCF87E9AB0EB410A9EED22E91B166C945BD92319E7EE9AABE1AC`。
- S5 通用多标的评估：已完成；CLI 接受任意数量的 Eastmoney dataset IDs，按统一 decision timestamp 构造带 purge 的 folds，再将预测落回每只标的独立执行，不写死首批 10 只 ETF。
- S5 首轮真实结果（10 ETF、44,934 OOS rows）：no-skill 0 笔；LightGBM 9 笔、等权净收益 `+0.1152%`，仍为 `INSUFFICIENT_EVIDENCE`；Logistic Regression 79 笔、胜率 `53.16%`、等权净收益仅 `+0.0274%`、最差单标的回撤 `5.34%`，状态仅为 `CANDIDATE`。
- Logistic Regression 的 79 笔中 48 笔来自 `512480.SSE`，扣除佣金 `3,888.60` 元并承受滑点成本 `3,110.89` 元后，300 万元等权测试资本只增加 `820.82` 元；优势过薄且成交集中，不能进入 Shadow/Paper。
- 两次 S5 报告 SHA-256 均为 `F7D5FF095797B310C6F7BBF27D8AD0722439B02C9ED19D39A958C17D94A99195`。
- macOS 数据源 P0：已完成通用 Provider 注册表、AKShare A 股 5 分钟归一化、
  有界并发/重试/按标的 checkpoint、失败阻止发布、不可变 Parquet 和
  `EXPLORATORY_ONLY` Formal 拒绝门。真实样本 `600000.SSE`（2026-08-11）发布 48 行并
  验证断点重跑；Mac 默认使用 30 秒 AKShare 全市场/核心指数延迟轮询，UI 与信号门均明确
  其非交易级实时语义。P0 已收口，下一步进入 P1 认证数据源资格验证。
- S6 时间稳定性报告：已完成；每个模型现在同时输出各 OOS fold 的起止时间、净收益、交易数、胜率、回撤和盈利标的数，不再只看全期汇总。
- S6 首轮真实复核：Logistic Regression 三段净收益分别为 `-0.0807% / +0.3152% / -0.1524%`，交易数分别为 `46 / 30 / 3`，只有 1/3 folds 为正；全期 `+0.0274%` 主要由中间一段贡献，不能视为稳定优势。
- LightGBM 三段净收益为 `+0.1894% / +0.1563% / 0%`，但仅有 `3 / 6 / 0` 笔交易，仍为 `INSUFFICIENT_EVIDENCE`。
- 两次 S6 报告 SHA-256 均为 `5C1C7254BF4D798015697F24C365E588CB52C4058DC3496A19D30C835860362D`。
- 当前阶段：已有结果证明 Logistic Regression 的微弱优势不稳定；下一节点是从真实 API 扩大历史和市场状态，再改善模型信号，而不是降低 `0.5` 阈值放大交易。
- DoubleEnsemble Task 4：9 个 ETF、91,507 行特征、3 个 walk-forward folds；两次预测 digest 均为 `D4A9A95BD2CB61D83F5EF6B77A02F91B4DFA94AA6D4AA37DB9FB47A5BA874EFF`，两次报告 digest 均为 `8F8393694CF686F9BEE7A99D370A4146AC32A433AA93AA0590E1D0A4CE08D504`。
- DoubleEnsemble 的 1,450 笔成交、`41.52%` 胜率和 `-2.5082%` 净收益说明增加模型复杂度与交易数没有形成净优势；程序不会为了“完成模型”而发布负收益 challenger。

## 延后而非删除

- Phase 1b publication trusted head、Merkle、防回滚与完整故障注入。
- 完整 research registry/lockbox/UI。
- 上述内容在模型准备进入 Shadow/Paper 前恢复，不阻塞当前策略效果研究。

## 下一结果

现在进入 Stage B v2 Batch 2：从东方财富真实 API 扩展日线宽历史和历史时点 universe，生成可重复的截面 feature/label snapshot，并让 Ridge、LightGBM/DoubleEnsemble 在相同 folds、费用和目标组合上先跑。Batch 2 的结果只回答“标签是否可学习、简单基线能否形成净优势”；只有门槛通过，Batch 3 才让 StockMixer v2 与 MASTER 竞争。

macOS、Choice、AKShare 批量训练与未来 Broker Gateway 的完整调研、优先级和验收条件见
[macOS 数据源与批量训练数据计划](2026-08-11-macos-data-source-and-batch-training.md)。

## 后续任务顺序

1. **Stage A 统一训练协议（已完成）**：task/score 契约、DoubleEnsemble 与真实多标的统一评价已经关闭；概率、预期收益、rank、风险各走声明过的选择规则。
2. **扩大全市场真实历史（下一步）**：用已资格认证的东方财富真实 API 构建历史时点动态 universe 和可重复日线 snapshot；训练接口不写死当前十只 ETF，并先覆盖 300–800 只、至少 5 年，目标 10 年。
3. **Kronos 基础模型通道（已完成，`NO_NET_EDGE`）**：官方预训练权重、批量推理和公平评价已关闭；保留研究通道但不微调、不开发正式图层、不进入组合，待更长历史与更多 regime 出现新证据后再挑战。
4. **Stage B 全市场共享表征（首轮完成，`NO_NET_EDGE`）**：StockMixer 官方语义、动态 universe、正式训练和统一执行均已关闭；下一步先重做 Stage B v2 的数据/任务/horizon 实验设计，不为每只股票单独训练，也不在失败结果上事后调参。
5. **Stage C 关系与状态**：接入 MASTER/HIST，验证行业、概念、潜在关系和市场 regime 是否带来可重复净改善。
6. **Stage D 路由与漂移**：接入 TRA/DoubleAdapt，形成任务专家、动态路由、滚动适应与可靠 fallback。
7. **Stage E 组合和发布**：把各任务 forecast 校准并组合为唯一目标仓位，完成压力测试、治理收口与 Shadow/Paper 反馈。
8. **P1 第二认证源与跨平台一致性**：实测 Tushare Pro/Choice；macOS 与 Windows 只保留 provider/runtime 差异，训练 artifact 语义一致。
9. **LIVE 设计**：只有账户、订单、费用、T+1、对账及 Stage A–E 全部通过后才讨论 Broker Gateway 与 LIVE。

当前 Strategy Fast Lane S1–S6、DoubleEnsemble、Kronos、StockMixer 首轮和 Stage B v2 Batch 1 均已完成，但仍无可晋级模型。工程已具备统一生成可执行截面标签、稳健校准模型分数并形成风险受控目标仓位的能力；当前停止继续实现新网络，先用真实宽历史验证任务/horizon 信号质量。Kronos 保留为独立研究能力，不再占用当前主线。

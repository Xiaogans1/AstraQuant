# Quant Core v3 当前进度（2026-08-12）

## 已完成

- Phase 0：49/49，旧 demo 数据、模型和 Paper 语义已隔离。
- Phase 1a：Tasks 1–6 已完成；真实 API 接入、资格、capture、batch 与后台任务可用。剩余真实 endpoint 最终 sign-off。
- Phase 1b：Tasks 1–4 已完成；canonical、时间可见性、coverage/quality、snapshot v2 可用。

## 当前开发

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

## 延后而非删除

- Phase 1b publication trusted head、Merkle、防回滚与完整故障注入。
- 完整 research registry/lockbox/UI。
- 上述内容在模型准备进入 Shadow/Paper 前恢复，不阻塞当前策略效果研究。

## 下一结果

macOS 数据源 P0 已完成；下一步生成明确标为 `EXPLORATORY` 的多标的日线/5 分钟快照，
并启动 Tushare/Choice 认证源资格验证。随后扩大时间跨度并增加不同市场状态，重点验证
Logistic Regression 的微弱优势能否跨时期复现。只有数据快照已 pin，且净收益、回撤和
成交分散性同时稳定后，才冻结候选并恢复 publication/model registry。

macOS、Choice、AKShare 批量训练与未来 Broker Gateway 的完整调研、优先级和验收条件见
[macOS 数据源与批量训练数据计划](2026-08-11-macos-data-source-and-batch-training.md)。

## 后续任务顺序

1. **P0 macOS 数据源前置（已完成）**：AKShare 批量探索快照和延迟看盘均已接通；现有东财 `gm` 保留为 Windows Provider，不再定义通用配置和 UI。
2. **S6 更长历史与更多标的**：时间稳定性报告已完成；探索数据用于扩大覆盖和候选筛选，正式结论继续通过已资格认证的真实 API 快照，不改变本轮 `0.5` 阈值后重跑统一 panel。
3. **P1 第二认证源**：实测 Tushare Pro 与 Choice `EMQuantAPI C++ Mac`，完成 endpoint 资格、Apple Silicon/Rosetta bridge、授权与跨源差异报告；至少一个 Mac 可用 Provider 进入 Formal。
4. **S7 策略信号改进**：在相同 folds、费用和资金约束下研究跨标的排序、行业/风格中性与 Qlib 候选模型；以可执行净收益、回撤和成交分散性选择候选，不以单一 AUC 选择。
5. **S8 稳健性压力测试**：固定候选后运行更高费率、滑点、延迟、容量与分市场状态报告；任何主要场景失效都继续 HOLD。
6. **Shadow 前治理收口**：完成 Phase 1a 真实 endpoint sign-off、publication trusted head、model registry、lockbox 和晋级门。
7. **Shadow/Paper**：先只读展示目标仓位，再接 Paper；只有账户、订单、费用、T+1 和对账语义全部通过后才讨论 P2 Broker Gateway 与 LIVE。

当前 Strategy Fast Lane 的 S1–S5 与 S6 时间稳定性报告已完成，但整个 Quant Core v3 尚未完成；未完成项主要是更长历史下的策略有效性、Shadow/Paper 治理和后续实盘适配。

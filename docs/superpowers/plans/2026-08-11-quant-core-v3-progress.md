# Quant Core v3 当前进度（2026-08-11）

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
- 当前阶段：多标的通路已经证明可用；下一策略节点应验证更长历史和跨市场状态稳定性，并改善模型信号，而不是通过降低 0.5 阈值放大这次微弱收益。

## 延后而非删除

- Phase 1b publication trusted head、Merkle、防回滚与完整故障注入。
- 完整 research registry/lockbox/UI。
- 上述内容在模型准备进入 Shadow/Paper 前恢复，不阻塞当前策略效果研究。

## 下一结果

扩大时间跨度并增加不同市场状态，重点验证 Logistic Regression 的微弱优势能否跨时期复现；只有净收益、回撤和成交分散性同时稳定后，才冻结候选并恢复 publication/model registry。

## 后续任务顺序

1. **S6 更长历史与更多标的**：继续通过真实 API 扩大分钟数据的时间跨度和市场状态，不改变本轮 `0.5` 阈值后重跑统一 panel。
2. **S7 策略信号改进**：在相同 folds、费用和资金约束下研究跨标的排序、行业/风格中性与 Qlib 候选模型；以可执行净收益、回撤和成交分散性选择候选，不以单一 AUC 选择。
3. **S8 稳健性压力测试**：固定候选后运行更高费率、滑点、延迟、容量与分市场状态报告；任何主要场景失效都继续 HOLD。
4. **Shadow 前治理收口**：完成 Phase 1a 真实 endpoint sign-off、publication trusted head、model registry、lockbox 和晋级门。
5. **Shadow/Paper**：先只读展示目标仓位，再接 Paper；只有账户、订单、费用、T+1 和对账语义全部通过后才讨论 LIVE。

当前 Strategy Fast Lane 的 S1–S5 已完成，但整个 Quant Core v3 尚未完成；未完成项主要是更长历史下的策略有效性、Shadow/Paper 治理和后续实盘适配。

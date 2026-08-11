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
- 当前阶段：到达策略研究重新梳理节点；目标执行语义已经具备，下一步应优先扩大真实交易机会与 OOS 样本，再决定候选模型和 Shadow/Paper 晋级，不继续在 1–2 笔成交上堆执行功能。

## 延后而非删除

- Phase 1b publication trusted head、Merkle、防回滚与完整故障注入。
- 完整 research registry/lockbox/UI。
- 上述内容在模型准备进入 Shadow/Paper 前恢复，不阻塞当前策略效果研究。

## 下一结果

扩大真实标的、时间跨度和可交易机会，先让统一成本口径下的 OOS 成交数达到证据门槛；随后冻结候选模型、恢复 publication/model registry，并接入 Shadow/Paper 只读目标展示。

# Strategy Effect First Design

**目标：** 用真实东方财富数据尽快回答“什么模型和策略真的更有效”，而不是继续扩张与当前收益无关的基础设施。

## 设计决定

1. 已完成的数据能力作为研究地基：真实 Eastmoney API、质量检查、时间可见性、snapshot v2 和原子发布继续保留。
2. publication ledger、Merkle trusted head、完整数据库治理和 UI 延后到模型准备晋级 Shadow/Paper 时。
3. 第一轮固定比较 `NO_SKILL`、`LOGISTIC_REGRESSION`、`LIGHTGBM`。它们读取同一训练行、同一 walk-forward folds、同一交易阈值和费率，输出逐 fold 与汇总结果。
4. 模型标签与收益使用同一持有区间，禁止“用五根 bar 标签、却用下一根 bar 收益计分”。每个 fold 只用过去训练、未来测试。
5. 第一轮只选择研究 challenger，不发布实盘模型。LightGBM 基线稳定后接 Qlib Alpha158/LightGBM，再比较是否有增益。

## 用户可见结果

每次矩阵报告直接展示：模型名称、OOS AUC、交易次数、毛收益、扣费净收益、正收益 fold 数和最佳 challenger。若所有模型净收益都不为正，程序明确返回 `NO_EDGE`，不美化结果。

## 开发顺序

`公平收益口径 → walk-forward 基线矩阵 → 真实 Eastmoney CLI → Qlib 对照 → A 股费率/T+1 回测 → 目标仓位与做 T`。

## 验收

- 同一输入与 seed 的报告完全一致。
- 所有模型使用完全相同的测试样本和交易成本。
- 测试 fold 严格晚于训练 fold。
- 真实运行只读取 Eastmoney 生成的数据集；fixture 只用于单元测试。
- 不以完成审计设施作为策略阶段完成标准。

# 目标仓位、T+1 可达性与底仓做 T 设计

## 目标

把模型 forecast 转换成明确、可解释的目标持仓，并在发出任何订单前回答三个问题：

1. 模型证据是否足以改变仓位；
2. 目标在现金、整数手、活动委托和 T+1 可卖量下能执行到多少；
3. 底仓做 T 最多能计划多少，两腿分别是什么。

本阶段生成 `BaseTarget`、`TargetReconciliation` 和 `TPlanDraft`，不自行撮合、不伪造成交，也不替代后续完整 OMS/journal。

## 方案选择

考虑过三种方案：

1. **Quant 层纯计划器（采用）**：forecast→target→reachable intent→TPlan draft 都是确定性纯函数，Paper/Replay/未来 execution core 共用。它能先把策略行为说清楚，不与旧即时成交账本耦合。
2. **直接改 `PaperStrategyService` 自动下单**：界面上最快看到交易，但当前模型只有 1–2 笔可执行 OOS 证据，且旧 Paper 账本仍是整单即时成交，容易把研究结果误当生产批准。
3. **先建设完整 lot journal/OMS**：长期最完整，但会重新把策略主线拖回庞大执行基础设施。

采用方案 1，并只在 API 层增加只读计划投影；自动执行继续受现有发布状态限制。

## Forecast 到 BaseTarget

`ForecastInput` 至少包含：

- `probability_up`、`expected_return`、`evidence_status`；
- model/source identity 与预测有效期；
- 当前 `base_target_quantity`，用于无交易带内保持目标。

规则：

- `evidence_status != VALIDATED` 时保持当前 BaseTarget，原因 `INSUFFICIENT_EVIDENCE`。
- `expected_return <= estimated_round_trip_cost_rate` 时保持当前 BaseTarget，原因 `NO_NET_EDGE`。
- `probability_up >= enter_probability` 时，按 `(p - 0.5) / 0.5` 得到 long-only 强度，再乘风险上限资金，按 lot size 向下取整。
- `probability_up <= exit_probability` 时目标为 0。
- 两阈值之间属于 no-trade band，保持当前 BaseTarget，避免概率在 0.5 附近反复买卖。
- `BaseTarget` 是一次决策的不可变结果；日内 overlay 不得改写它。

当前 S3 的 ASTRA10/Alpha158 都因可执行交易数不足而输出 `INSUFFICIENT_EVIDENCE`，因此真实运行结果应为 HOLD，而不是挑一条短样本曲线当 champion。

## TargetReconciler

输入：

- `actual_quantity`、`rule_sellable_quantity`、`reserved_sell_quantity`；
- `working_buy_quantity`、`working_sell_quantity`；
- `cash_available`、参考价格、买入成本缓冲、lot size；
- `target_quantity` 和 intent kind（`BASE` 或 `RISK_REDUCTION`）。

先计算：

```text
projected_quantity = actual_quantity
                   + working_buy_quantity
                   - working_sell_quantity
available_to_new_sell = rule_sellable_quantity - reserved_sell_quantity
```

活动委托已经进入 projected quantity，不能因尚未成交而重复发单。

- 买入：新委托数量受目标差额、可用现金和 lot size 限制。
- 卖出：新委托数量受目标差额、`available_to_new_sell` 和 lot size 限制。
- `target=0` 不代表能卖掉当日冻结仓；昨仓 1000 + 今买 1000 时，最多新卖 1000，reachable target 为 1000，剩余原因 `T1_FROZEN`。
- 风险减仓可以抢占 forecast 方向，但同样不能绕过 T+1；输出 `RISK_REDUCTION_PARTIAL`，不谎称已清仓。
- 所有结果同时给出 requested target、projected quantity、proposed side/quantity、reachable quantity、unreachable quantity 和结构化原因。

## 底仓做 T

`TPlanDraft` 支持两种计划：

- `SELL_THEN_BUYBACK`：先卖开盘已可卖底仓，再计划买回；最大数量受 `opening_sellable - active_reservations` 限制。
- `BUY_THEN_SELL_BASE`：先买临时仓，再卖同量已预留的开盘底仓；最大数量还受现金限制，不能把当日新买数量当成第二腿可卖量。

共同规则：

- forecast evidence 必须 `VALIDATED` 且 `expected_incremental_return > estimated_round_trip_cost_rate`；否则 HOLD。
- `planned_quantity` 按 lot size 向下取整，且不超过用户 overlay 上限、可用开盘底仓和现金/容量约束。
- `BUY_THEN_SELL_BASE` 的 `reserved_opening_quantity == planned_quantity`；第二腿上限始终来自开盘可卖底仓。
- Draft 只描述 first/second side、计划量、预留量和原因；订单、partial fill、取消、恢复和 reservation transfer 留给 execution core。
- BaseTarget 保持不变。若未来第一腿已成交而第二腿未完成，必须由 execution core 形成 residual，不得由本计划器伪报完成。

## 可见结果

新增一个研究 CLI，读取 S3 可执行报告并输出：

- 每个模型的 evidence status；
- forecast→BaseTarget 的 HOLD/目标理由；
- canonical T+1 场景（昨 1000 + 今买 1000 → 目标 0）的 proposed sell、reachable 和 frozen 数量；
- 两种底仓做 T 的最大计划数量及阻塞原因。

用户看到的是“程序准备持有多少、现在能做到多少、为什么做不到”，而不是底层状态机日志。

## 测试与验收

- 证据不足、净优势不足、no-trade band 都保持当前 BaseTarget。
- validated 高概率 forecast 按风险预算和 100 股整数手生成目标；低概率 forecast 目标为 0。
- 昨 1000 + 今买 1000、目标 0：只卖 1000，reachable=1000，unreachable=1000，原因 T1。
- 已有 working sell 覆盖目标时不重复发卖单；reservation 从可用新卖量中扣除。
- 现金不足买满目标时输出 cash-limited reachable target。
- 两种 TPlan 都不超过未预占开盘可卖底仓；buy-first 还受现金限制。
- S3 真实报告因交易数不足输出 HOLD；canonical validated forecast 能生成目标和 TPlan。
- 相同输入两次 CLI 报告 SHA-256 一致。


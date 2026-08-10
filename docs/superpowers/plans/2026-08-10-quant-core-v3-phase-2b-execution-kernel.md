# Quant Core v3 Phase 2b Unified Execution Kernel Stage Roadmap

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 在 Phase 2a 的冻结契约上实现 A 股 lots、交收、可卖、预占、现金、真实费用、公司行动税、OMS、保守 matcher、TPlan、估值和硬风控。

**Architecture:** 所有 command 只经 `ExecutionEngine` 产生事件，所有投影只从 journal 派生。RuleBook/Session/Fee/Tax/Valuation policies 是 exact sealed inputs；状态缺失或不一致时 fail closed。模块可以分文件，但不能各自维护现金/持仓副本。

**Tech Stack:** Python 3.12、Decimal、pytest/Hypothesis、Phase 1 snapshot/policies、Phase 2a event journal。

---

## Task 1: 实现 RuleBook resolver 与账户生命周期

**Files:**

- Create: `packages/execution/src/astraquant_execution/rulebook.py`
- Create: `packages/execution/src/astraquant_execution/lifecycle.py`
- Test: `tests/execution/test_rulebook.py`
- Test: `tests/execution/test_lifecycle.py`

- [ ] 先测试 market/instrument/session 只能解析到唯一 RuleBook+InstrumentSession；缺失、冲突、暂缓、revoked source、日期不覆盖全部拒绝新单。
- [ ] 先测试开日加载/结算使用已批准 calendar；周末/节假日不解冻，开日步骤失败账户不进入 READY。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 resolver/readiness command handlers，保存 exact policy/session digests 到 run/journal。
- [ ] 风险收缩是否允许只能由冻结 `SafeActionPolicy` 判定，不能在异常处理里自动猜测。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(execution): 实现规则解析与账户生命周期"`

## Task 2: 实现 lots、sellability、reservations 与证券交收

**Files:**

- Create: `packages/execution/src/astraquant_execution/lots.py`
- Create: `packages/execution/src/astraquant_execution/reservations.py`
- Create: `packages/execution/src/astraquant_execution/settlement.py`
- Test: `tests/execution/test_lots.py`
- Test: `tests/execution/test_reservations.py`
- Test: `tests/execution/test_settlement.py`

- [ ] 先用 property tests 固化三轴：settled/unsettled，sellable/non-sellable，reserved/unreserved；`security_reserved_qty = Σ all active SecurityReservation`，订单子投影另算。
- [ ] 测试昨 1000+今买 1000 只可卖 1000，目标 1000/0 输出明确 unreachable；合格 T+0 买入 lot 未交收但可卖。
- [ ] 测试 T+0 买 100→卖 100 至零库存，RECEIVE/DELIVER obligations 或合规 netting lineage 保存到结算，结算后无幽灵持仓。
- [ ] 测试 TPLAN/ORDER/RISK/CORPORATE_ACTION reservation owner 与原子 transfer；cancel pending 不提前释放，公司行动/Broker lock 后不再供新单。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 lot disposition、orthogonal projections、security obligations 与 versioned netting rule；任何 double reservation 原子拒绝。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(execution): 实现批次交收与证券预占"`

## Task 3: 实现 cash settlement 与双边 accounting

**Files:**

- Create: `packages/execution/src/astraquant_execution/cash.py`
- Modify: `packages/execution/src/astraquant_execution/accounting.py`
- Test: `tests/execution/test_cash_accounting.py`

- [ ] 先测试 eligible trade cash、withdrawable cash、receivable/payable、buy principal reserve、fee/tax cash reserve 分项守恒，任何分支不产生负 available cash。
- [ ] 测试卖出所得当日可交易、下一合格结算日可取，覆盖周末/节假日和 Broker override。
- [ ] 测试并发 buy reservations 使用 journal tail CAS，不能分别通过检查后合计超用。
- [ ] 运行目标 test，确认红灯。
- [ ] 实现 journal-derived cash projections 和 settlement handlers；worst-case principal 与 fee reserve 是否包含彼此必须由字段/公式显式区分。
- [ ] 重跑 test，期望全绿。
- [ ] 提交：`git commit -m "feat(execution): 实现可交易与可取现金语义"`

## Task 4: 实现 FeeChargeUnit 和真实分项费用

**Files:**

- Create: `packages/execution/src/astraquant_execution/fees.py`
- Test: `tests/execution/test_fee_charge_unit.py`

- [ ] 先测试 provisional unit 在 submit 前绑定 `client_order_id/broker_child_id`，Accepted 后幂等绑定 venue id，不重建 accumulator。
- [ ] 测试一个 BrokerOrder 三次 fills 只累计/补足一次最低佣金；strategy parent 拆两 broker orders 各自计费；partial cancel、zero-fill cancel、replace 的 charge unit scope 由 policy 决定。
- [ ] 测试股票/ETF、沪/深、生效日期、side、印花税、过户费、规费、minimum/rounding 的 exact Decimal 结果和 Broker actual reconciliation。
- [ ] 运行目标 test，确认红灯。
- [ ] 实现 FeeAccumulator/estimate/reserve/actual/reversal journal；不从 symbol 前缀猜 ETF 或税收豁免。
- [ ] 重跑 test，期望全绿。
- [ ] 提交：`git commit -m "feat(execution): 实现订单级真实费用累计"`

## Task 5: 实现公司行动、分红税与 unknown opening lots

**Files:**

- Create: `packages/execution/src/astraquant_execution/corporate_actions.py`
- Test: `tests/execution/test_corporate_actions.py`
- Test: `tests/execution/test_dividend_tax.py`

- [ ] 先测试 entitlement、record/ex/pay、持有期、账户级 FIFO/日终净增减、派息与卖出补扣 lifecycle，满足 `tax_outstanding = reserved + unpaid`。
- [ ] 测试聚合 opening 无 execution/acquisition history 创建 `OPENING_BALANCE_LOT + UNKNOWN_TAX_LOT`，不伪造成交/日期/成本；若 entitlement/交割证据能给出有限税基上界，同时创建带 `tax_base_amount_or_bound/base_method/evidence_ids/max_applicable_rate/amount_bound/collection_source/fidelity` 的 `ConservativeDividendTaxExposure`；能导入交割历史时只 append `LotReconstructionEvent`。
- [ ] 测试卖单提交阶段精确使用 `projected_paid_from_proceeds_bound=min(projected_gross_proceeds, contingent_tax_exposure_bound)`、`projected_net_receivable=projected_gross_proceeds-projected_paid_from_proceeds_bound>=0`、`projected_contingent_shortfall_bound=contingent_tax_exposure_bound-projected_paid_from_proceeds_bound>=0`；`FROM_SELL_PROCEEDS` 的 shortfall 只进风险/压力披露，不形成提交前 current-cash 门槛。
- [ ] 测试 `contingent_tax_receivable_haircut` 只降低该卖单 projected receivable，不进 `base_trade_cash`也不与 `contingent_tax_cash_reserved` 重复扣减；只有 Broker/账户证据明确要求当前现金预覆盖时才进 cash reserve。
- [ ] 测试 `FROM_SELL_PROCEEDS`：cash=0 有限 tax exposure 仍可风险卖出；fill 时 `paid_from_proceeds=min(gross_receivable,assessment_amount)`、`net_receivable>=0`，残余再按 policy 扣 current cash/进入 `unpaid_tax_liability` 并冻结买入出金。
- [ ] 测试 tax base 无有限证据上界时标记 `TAX_BASE_UNKNOWN`：Formal REPLAY/PAPER/MIRROR 单值虚拟卖出 fail closed，exploratory 只输出带上界未知标记的不完整区间，不伪造 haircut/reserve 或税后 PnL。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 TaxHoldingLot/Exposure/Assessment/collection/reversal；有限 exposure 按 `collection_source` 二选一形成 receivable haircut 或 current-cash reserve，`TAX_BASE_UNKNOWN` 在 Formal 单值路径 fail closed；MIRROR simulation fork 使用上述虚拟语义，Broker observed/LIVE 只使用实际回报对账。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(execution): 实现公司行动与分红税账本"`

## Task 6: 实现 OMS 三正交轴、report inbox 与 reconciliation

**Files:**

- Create: `packages/execution/src/astraquant_execution/orders.py`
- Create: `packages/execution/src/astraquant_execution/reconciliation.py`
- Test: `tests/execution/test_order_state_machine.py`
- Test: `tests/execution/test_execution_report_inbox.py`
- Test: `tests/execution/test_reconciliation.py`

- [ ] 先测试 `OrderLifecycle=CREATED|SUBMITTING|ACK_PENDING|WORKING|PARTIALLY_FILLED|FILLED|CANCELED|EXPIRED|REJECTED|REPLACED|UNKNOWN`、`PendingAction=NONE|CANCEL_PENDING|REPLACE_PENDING`、`OrderSyncState=IN_SYNC|RECONCILING|DISCREPANT` 的合法组合；`AccountReadiness=BOOTSTRAPPING|RECONCILING|READY|DEGRADED_READ_ONLY|HALTED` 独立验证。
- [ ] 测试 fill→late ACK：raw report 先存 Pending 并保持预占，权威 order/fill/watermark 证据闭合后补 Accepted→Fill 因果过账；同 execution id 恰好一次。
- [ ] 测试 cancel pending fill、重复/迟到 ACK、UNKNOWN 不盲重发、无法归属 report 保持 DISCREPANT/HALTED。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 OMS handlers、report inbox、four-table reconciliation 和 `ReadinessEvidence`；terminal 且证据闭合前不释放资源。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(execution): 实现三轴OMS与成交对账"`

## Task 7: 实现 hard risk gate 与安全动作

**Files:**

- Create: `packages/execution/src/astraquant_execution/risk_gate.py`
- Test: `tests/execution/test_risk_gate.py`

- [ ] 先测试价格/数量/lot/tick/涨跌停/停牌、cash/security reservations、readiness、single-name/portfolio/sleeve/turnover/capacity/loss/drawdown limits。
- [ ] 测试 policy/session/data stale/reconciliation failure 时 HOLD/no-new-orders；撤活动单或风险收缩只在明确 safe action policy 和可卖/现金事实允许时执行。
- [ ] 测试 optimizer/模型输出不能绕过 hard gate，API 也不能直接写 accepted order。
- [ ] 运行目标 test，确认红灯。
- [ ] 实现 deterministic `RiskDecision`/reasons/actions；不在线训练、不改阈值、不自动选未批准 fallback。
- [ ] 重跑 test，期望全绿。
- [ ] 提交：`git commit -m "feat(execution): 建立确定性交易硬风控"`

## Task 8: 实现 Bar/Quote/Depth matcher 与共享流动性

**Files:**

- Create: `packages/execution/src/astraquant_execution/matchers/__init__.py`
- Create: `packages/execution/src/astraquant_execution/matchers/base.py`
- Create: `packages/execution/src/astraquant_execution/matchers/bar.py`
- Create: `packages/execution/src/astraquant_execution/matchers/quote.py`
- Create: `packages/execution/src/astraquant_execution/matchers/depth.py`
- Test: `tests/execution/matchers/test_bar.py`
- Test: `tests/execution/matchers/test_quote.py`
- Test: `tests/execution/matchers/test_depth.py`
- Test: `tests/execution/matchers/test_shared_liquidity.py`

- [ ] 先测试 submit time>=decision+latency、Accepted 先于 fill、market event sequence 晚于 accepted；same-bar close、停牌、无 bar、锁板、limit 未 touch 均不成交。
- [ ] 测试 BarOpen 只能用当时可证明 opening capacity；full-bar volume 只在 BarClose 阶段约束剩余成交，不能回写 open execution time/price。
- [ ] 测试 `BAR_CONSERVATIVE` 对每个 OHLCV-only run 同时产出 base/stress scenario；无 intrabar path/VWAP 证据时只能给保守路径或成交/PnL 区间，报告和 API 不得标记“精确成交”，不得用 OHLC 极值推断先后路径。
- [ ] 测试 `QUOTE_TOUCH` 在 quote 超过冻结 max age、spread 超限、价格未 touch 或 visible quantity=0 时不成交；同一 `instrument+quote event+scenario` 的 visible quantity 是全账户一次性共享 budget，未变更快照不得被多订单/多策略重复消耗。
- [ ] 测试同 instrument/event 全账户共享 volume/depth budget、price-time allocation、partial/TIF、撤单交叉和不利 slippage；limit 不因 OHLC 极值获得虚构改善。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 matcher interface、market liquidity ledger 与明确 FillPrice/Slippage policy；formal 禁止 last fallback。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(execution): 实现保守分阶段撮合器"`

## Task 9: 实现 TPlan、sleeve attribution 与 valuation

**Files:**

- Create: `packages/execution/src/astraquant_execution/tplan.py`
- Create: `packages/execution/src/astraquant_execution/attribution.py`
- Create: `packages/execution/src/astraquant_execution/valuation.py`
- Create: `tests/execution/test_tplan.py`
- Test: `tests/execution/test_attribution.py`
- Test: `tests/execution/test_valuation.py`

- [ ] 先测试 SELL→BUYBACK 与 BUY→SELL 在 decision 时显式建 plan；leg1 实际成交数量限制 leg2，TPLAN→ORDER reservation transfer 原子。
- [ ] 用 property/canonical tests 始终断言 `0 <= leg2_filled_qty <= leg1_filled_qty <= planned_qty`、`residual_qty=leg1_filled_qty-leg2_filled_qty`；`T_BUY_THEN_SELL_BASE` 还要求 `leg2_filled_qty<=reserved_opening_qty` 且第二腿上限精确为 `min(leg1_filled_qty,reserved_opening_qty)`。
- [ ] 测试 partial/cancel/retry/restart/cross-day/company-action lock；任一活动/UNKNOWN 子单或 reservation 存在时 plan 必须是非终态 `RECOVERING`，对账闭合后才回原态或进入终态。
- [ ] 测试三个 terminal state 互斥：`COMPLETED` 要求 residual=0/全子单终态/reservation=0；`ABORTED` 还要求 residual=0 或同一事务已全量 `AttributionTransfer` 到 Base/Risk；未转移的正 residual 只能是 `RESIDUAL_OVERNIGHT`，不靠事后相邻交易猜 T。
- [ ] 测试 hard-risk takeover 在中止 TPlan/撤冲突余单前，必须在同一 journal 事务中把对应 `SecurityReservation` 从 TPLAN/ORDER 原子转给 RISK；不得先释放再新建、双重预占或绕过现有 owner 下单。
- [ ] 测试 Base/T/Risk 内部净额、跨 lots、partial、fee/slippage/rounding 后 `Σ sleeve journal/PnL = account journal/PnL`。
- [ ] 用 canonical case 固定 `LotDispositionPolicy` 的 lot 选择与 `PnLAttributionPolicy` 的 Base/T/Risk claims/priority/非线性费用/残差顺序；两个 policy id/hash 写入 RunManifest 和每个相关 journal batch。
- [ ] 测试停牌/陈旧价/公司行动日 mark policy；无信号仍盯市，期末默认 mark-to-market 且未卖仓位不变 cash。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 TPlan/attribution/valuation handlers，所有 policy/hash 写 manifest/journal。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(execution): 实现TPlan归因与可追溯估值"`

## Task 10: Phase 2b canonical execution gate

**Files:**

- Create: `tests/execution/test_canonical_scenarios.py`
- Create: `tools/verification/verify_phase_2b.py`
- Create: `docs/verification/quant-core-v3/phase-2b-signoff.md`

- [ ] 对 Phase 2a 全部 fixtures 执行 reducer，精确比较 events、orders、fills、cash、lots、reservations、obligations、fees/tax、valuation 和 final digest。
- [ ] 运行：

```powershell
uv run pytest tests/execution -q
uv run ruff check packages/domain/src packages/execution/src tests/domain tests/execution tools/verification
uv run ruff format --check packages/domain/src packages/execution/src tests/domain tests/execution tools/verification
uv run mypy packages/domain/src packages/execution/src tests/domain tests/execution tools/verification
```

- [ ] verifier 必须为每个 canonical scenario 输出符合 `contracts/execution-oracle/v1/trace.schema.json` 的 normalized execution trace 和总 manifest，trace 写入与 verification JSON 的成功必须是同一次不可部分签核的 verifier run。
- [ ] 在干净实现 commit 上创建 must-not-exist 的 UUID 目录，运行 `uv run python tools/verification/verify_phase_2b.py --scenarios tests/fixtures/execution/canonical --trace-output artifacts/verification/phase-2b/{run_id}/execution-traces --output artifacts/verification/phase-2b/{run_id}/verification.json`，机器复核全部 expected events/journal/invariants，并在 verification manifest 中记录 Phase 3 Task 4 的精确 trace 路径/digest。

- [ ] 核对退出门：T+1/T+0/做 T/费用/税/partial/limit/suspension/bar causality/共享流动性 scenarios=100%；journal 不变量=100%；terminal reservation leakage=0；负 cash/receivable=0。
- [ ] sign-off 固定 scenario/run digests；尚未完成 runtime persistence/parity 时只签 Phase 2b，不签完整 Phase 2。
- [ ] 提交：`git commit -m "test(execution): 完成统一执行语义验收"`

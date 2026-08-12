# Quant Core v3 Phase 5 Daily Target and Release Stage Roadmap

> **生产训练硬约束：** 本阶段负责[长期训练架构](../specs/2026-08-12-production-training-architecture-design.md)的组合与上线反馈闭环：不同任务和模型输出必须先按声明语义校准、路由和冲突消解，再形成目标仓位；单模型不得直接控制订单或独占 champion。

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 在 Phase 4 公平基线与预冻结 ReleasePolicy 之上评估成熟日线 challenger，把批准的 AlphaForecast 转成可审计 BaseTarget/OrderIntent，并通过 Shadow 和 Paper canary 决定是否产生 Paper/Mirror champion。

**Architecture:** 模型研究仍在 isolated runners；产品 quant 层只消费不可变 AlphaForecast。Portfolio constructors 先比较 Top-K/风险预算/Qlib enhanced indexing/CVXPY cost-aware optimizer，再由 TargetReconciler 投影 working orders 与 T+1 可达性。ModelVersion 状态机与 champion alias append-only；无人过门时系统保持 HOLD。

**Tech Stack:** `astraquant_research`、Qlib model zoo、PyTorch runner、CVXPY/cvxportfolio-style optimizer、NumPy/Pandas、`astraquant_quant`、`astraquant_execution`、Alembic/FastAPI/React。

---

## Task 1: 锁定并消费 Phase 4 ReleasePolicy 机器契约

**Files:**

- Modify: `packages/domain/src/astraquant_domain/release.py`
- Modify: `packages/research/src/astraquant_research/release_policy.py`
- Create: `packages/research/src/astraquant_research/promotion.py`
- Test: `tests/domain/test_release_policy.py`
- Test: `tests/research/test_release_policy.py`

- [ ] 先测试 tournament 只能消费 Phase 4 在首次结果前 SEALED 的 exact ReleasePolicy digest；它固定 incumbent、planned folds/failed-fold rules、family denominator、bootstrap block/repetitions/seed、RegimeSpec/min counts、PBO/SPA denominator、return/drawdown/capacity/risk thresholds 和 missing-result handling，任一缺失或事后修改 fail closed。
- [ ] 验证预冻结机器门至少包含：OOS total/median fold net>0、positive folds>=70%、paired block-bootstrap 95% lower bound>0、PSR/Deflated Sharpe probability>=0.95、PBO<=0.20、White RC/SPA p<=0.05、base/adverse 过收益风险门、severe 不破硬风险；Phase 5 不根据候选结果补写这些字段。
- [ ] 样本不足返回 `INSUFFICIENT_EVIDENCE`，不能从 denominator 删除 regime/fold/trial 或降低阈值救特定模型；若业务确需新 policy，必须先创建 version+ADR+新 experiment family+未来 lockbox，已消费的 Phase 4 lockbox 永不复用。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 deterministic evaluator 和 reason codes；Phase 4 gate 只能产 OFFLINE_VALIDATED evidence，不能直接写 champion。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 锁定模型发布策略消费边界"`

## Task 2: 建立日线 challenger tournament

**Files:**

- Create: `runners/qlib/src/astraquant_qlib_runner/daily_models.py`
- Create: `runners/qlib/src/astraquant_qlib_runner/tournament.py`
- Create: `packages/research/src/astraquant_research/tournament.py`
- Test: `tests/research/test_daily_tournament.py`
- Test: `tests/research/test_budget_fairness.py`

- [ ] 先测试所有 challenger 使用 Phase 4 同一 exact data/feature/label/splits/cost/ReleasePolicy，开发至少 5 seeds，决赛随机模型 20 seeds，同类相同 HPO/wall-clock/GPU budget。
- [ ] 按阶段注册 DoubleEnsemble、GRU、TCN、TRA、HIST、MASTER；只有上一 complexity tier 对 frozen baselines 产生有效证据后才运行下一 tier，跳过也记录 reason。
- [ ] 预训练/外部 checkpoint 必须记录 training cutoff/release time，并保留晚于它的 post-release holdout；无法证明训练污染边界的 candidate 不进决赛。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 runner registry/tournament scheduler，把成功、失败、取消全部写 Trial Ledger；模型源码/commit/config/env/artifact hashes 完整。
- [ ] 重跑 synthetic contract tests；真实矩阵运行留到 Task 10。
- [ ] 提交：`git commit -m "feat(research): 建立日线模型公平竞赛"`

## Task 3: 在 Trial Ledger 后接入受限 RD-Agent 提案层

**Files:**

- Create: `packages/research/src/astraquant_research/automation.py`
- Create: `runners/rd-agent/pyproject.toml`
- Create: `runners/rd-agent/uv.lock`
- Create: `runners/rd-agent/.python-version`
- Create: `runners/rd-agent/runner-manifest.json`
- Create: `runners/rd-agent/src/astraquant_rd_agent_runner/__main__.py`
- Test: `tests/research/test_research_automation.py`
- Test: `tests/research/test_rd_agent_manifest.py`

- [ ] 先测试每个自动提案在生成前申请 family trial budget，成功/失败/拒绝/取消都计入多重比较 denominator；超预算立即拒绝。
- [ ] runner 只能读取脱敏 research schema、批准的 feature/model search space 和 exact export；不能看到 lockbox labels、修改 ReleasePolicy、调用 promotion/portfolio/execution/gateway 或继承 secrets/network credentials。
- [ ] 生成代码/config 先在隔离环境通过 schema/static/security/tests 和人工 review，之后才成为普通 TrialRecord；RD-Agent 不能自动发布。
- [ ] 实施时重新核查 RD-Agent 官方仓库并固定 full commit、Python/uv lock、patch/env hash；manifest 禁止 default branch/latest/空 hash。
- [ ] 运行目标 tests 确认红灯，再实现 proposal adapter/sandbox contract 并运行 `uv lock --project runners/rd-agent`。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 接入受限自动研究提案层"`

## Task 4: 实现风险输入和组合构建基线

**Files:**

- Create: `packages/quant/src/astraquant_quant/risk_model.py`
- Create: `packages/quant/src/astraquant_quant/portfolio_constraints.py`
- Create: `packages/quant/src/astraquant_quant/base_optimizer.py`
- Create: `packages/quant/src/astraquant_quant/cost_model.py`
- Modify: `packages/quant/pyproject.toml`
- Test: `tests/quant/test_risk_model.py`
- Test: `tests/quant/test_base_optimizer.py`
- Test: `tests/quant/test_cost_model.py`

- [ ] 先测试等权/Top-K/Top-K Dropout、波动率目标/风险预算、Qlib EnhancedIndexing export 和 CVXPY cost-aware formulation 使用相同 forecast/risk/cost/constraints。
- [ ] 只有 rank score 时用 ranking portfolio，不伪造 expected-return scale；概率/quantile forecast 未校准时不进入 mean-variance objective。
- [ ] 测试 objective/constraints 至少含 forecast、factor/covariance risk、single/industry/sector exposure、真实 estimated cost、turnover、liquidity/participation、min lot、cash buffer 和 user risk budget。
- [ ] 测试优化不可行时保留上一安全 BaseTarget，允许独立 hard risk layer 减少可卖风险；禁止随机放松约束。
- [ ] 运行目标 tests，确认红灯。
- [ ] 在 quant package 固定 CVXPY/solver dependency 并运行 `uv lock`；实现可审计 risk/cost/optimizer adapters，记录 solver/version/status/tolerance/input hashes；确定性 rounding 不使用未来成交价/volume。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(quant): 建立日线组合优化基线"`

## Task 5: 实现 BaseTarget、TargetReconciler 与 OrderIntent

**Files:**

- Create: `packages/quant/src/astraquant_quant/targets.py`
- Create: `packages/quant/src/astraquant_quant/target_reconciler.py`
- Create: `packages/quant/src/astraquant_quant/order_intents.py`
- Modify: `packages/quant/src/astraquant_quant/strategy_layer.py`
- Test: `tests/quant/test_targets.py`
- Test: `tests/quant/test_target_reconciler.py`
- Test: `tests/quant/test_order_intents.py`

- [ ] 先测试权重转 quantity 使用 decision-time ValuationPolicy price、equity、lot/odd-lot rule 与 deterministic rounding；不用未来 fill price。
- [ ] 测试 projection=`current lots + working buys - working sells`，其中 working 由 `open_remaining_qty` 与活动 reservation 投影，覆盖 `WORKING/CANCEL_PENDING/REPLACE_PENDING/UNKNOWN/RECONCILING`；在 Broker 终态证据/对账闭合前不得释放资源或重发同一 delta。Base/T/Risk 相反 claims 先内部净额，不能重复下单/自成交。
- [ ] 测试 T+1 frozen、cash/lot/capacity 导致的 reachable/unreachable quantities 与 reason；目标 0 不等于强制卖掉不可卖今仓。
- [ ] OrderIntent 固定 target delta、sleeve allocation claim、risk decision、lot disposition/PnL attribution/Fee/RuleBook lineage。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现四步目标链中的 BaseTarget→ReconciledTarget→RiskAdjustedExecutableTarget→OrderIntent；旧 strategy layer 只做 compatibility facade。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(quant): 建立目标仓位与委托意图"`

## Task 6: 实现 sleeve attribution 与日线端到端执行

**Files:**

- Create: `packages/quant/src/astraquant_quant/attribution.py`
- Create: `tests/quant/test_attribution.py`
- Create: `tests/integration/test_daily_target_execution.py`

- [ ] 先测试 Base/T/Risk claims 内部净额后，净 broker order partial fills 跨 lots 且产生 minimum fee/slippage/rounding residual；每一时点 sleeve quantity/cost/PnL 总和精确等于 account。
- [ ] 测试 policy 在 OrderIntent 前冻结，fill 后不能追溯改 attribution 美化某 sleeve；residual transfer 只能 append event。
- [ ] 端到端用 approved AlphaForecast→BaseTarget→risk→OrderIntent→execution core，重放 digest 相同，HOLD forecast 不制造 order。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 attribution claims/report projection 与 integration wiring。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(quant): 建立分袖归因与日线执行链"`

## Task 7: 建立 ModelVersion registry 与 champion alias

**Files:**

- Create: `packages/api/migrations/versions/0015_model_release_targets.py`
- Create: `packages/api/src/astraquant_api/model_release_repository.py`
- Create: `packages/api/src/astraquant_api/model_release_service.py`
- Modify: `packages/api/src/astraquant_api/schema_registry.py`
- Test: `tests/api/test_model_release_repository.py`
- Test: `tests/api/test_model_release_service.py`
- Modify: `tests/api/test_schema_registry.py`

- [ ] 先测试 immutable ModelVersion 固定 artifact/processor/code/lock/env/hardware、all input IDs、trials/seeds/fold predictions/reports/approvals、serving schema/latency/universe/sleeve/risk policy 和 predecessor lineage。
- [ ] 状态只允许 DRAFT→OFFLINE_VALIDATED→SHADOW→PAPER_CANARY→CHAMPION 或 QUARANTINED/RETIRED；champion 是 atomic alias，至少保留前两版可回滚。
- [ ] 测试无 candidate 过 ReleasePolicy 时 service 返回 HOLD/“暂无可发布模型”，不复用 legacy 或降低门。
- [ ] 运行目标 tests，确认红灯。
- [ ] 在 0015 建 model versions/evidence/promotion decisions/champion alias/targets/intents 表，`down_revision="0014_research_v3"`；同步更新 schema registry 与真实 0014→head parity test；实现 optimistic alias swap/audit/replay。
- [ ] 重跑 tests/migration smoke，期望全绿。
- [ ] 提交：`git commit -m "feat(api): 建立不可变模型发布注册表"`

## Task 8: 实现 Shadow 与 Paper canary gates

**Files:**

- Create: `packages/api/src/astraquant_api/shadow_service.py`
- Create: `packages/api/src/astraquant_api/promotion_service.py`
- Test: `tests/api/test_shadow_service.py`
- Test: `tests/api/test_promotion_service.py`
- Create: `tests/integration/test_shadow_event_parity.py`

- [ ] 先测试 candidate/champion 消费相同 live event IDs；Shadow 只写 forecast/target/simulated orders，不改 Paper/Mirror account journal。
- [ ] 编码初始门：>=20 sessions、>=200 executable opportunities 或更长 MinTRL；inference success>=99.9%；feature/forecast/target/state replay digest=100%；future/stale/rule violations=0。
- [ ] 日线在 next-session cutoff 前完成；Paper canary=10% planned scale、>=10 sessions 且>=100 opportunities；model/feature/threshold/rule/fee 改变重置观察。
- [ ] 测试 quarantine/rollback triggers：hash/schema/rule/fee mismatch、leakage/same-bar/T+1 violation、journal/reconciliation failure、stale/drift、severe slippage、两个成熟窗口退化、risk/capacity breach。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 background shadow/promotion evaluator；正确动作 HOLD/no-new-orders/cancel approved active orders/atomic alias rollback，不现场训练或换 fallback。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(api): 建立Shadow与Paper晋级门"`

## Task 9: 暴露目标、发布和解释 API/UI

**Files:**

- Create: `packages/api/src/astraquant_api/target_schemas.py`
- Create: `packages/api/src/astraquant_api/target_routes.py`
- Create: `packages/api/src/astraquant_api/model_release_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Modify: `apps/desktop/src/api/research-contracts.ts`
- Modify: `apps/desktop/src/api/queries.ts`
- Create: `apps/desktop/src/components/ModelPromotionPanel.tsx`
- Create: `apps/desktop/src/components/ModelPromotionPanel.test.tsx`
- Create: `apps/desktop/src/components/TargetExplanationPanel.tsx`
- Create: `apps/desktop/src/components/TargetExplanationPanel.test.tsx`
- Modify: `apps/desktop/src/pages/StrategyLabPage.tsx`

- [ ] 先测试 API 返回 forecast→optimizer/constraints→target→risk→intent lineage、reachable/unreachable、incumbent/candidate gates、forward evidence 和 rollback history。
- [ ] UI 不只显示 SHAP，还显示为何目标是该数、每个约束裁掉多少、为何不可卖/未成交、预期/实际成本差。
- [ ] promotion/rollback 需要 authenticated idempotent command 和 evidence digest；前端不能修改 gate/alias row。
- [ ] 运行 API/frontend tests，确认红灯。
- [ ] 实现 routes/contracts/components；CHAMPION 明确标“Paper/Mirror champion，不代表实盘授权”。
- [ ] 重跑 desktop test/check/build 与 API tests。
- [ ] 提交：`git commit -m "feat(ui): 展示目标仓位与模型晋级证据"`

## Task 10: Phase 5 真实 tournament 与 sign-off

**Files:**

- Create: `tools/research/run_daily_tournament.py`
- Create: `tools/verification/verify_phase_5.py`
- Create: `docs/verification/quant-core-v3/phase-5-signoff.md`

- [ ] 解析并锁定 Phase 4 已 SEALED 的 ReleasePolicy v1 artifact/incumbent，再以 exact snapshots 与新 experiment family 运行 challenger tournament；不得复用 Phase 4 已消费 lockbox 做调参，也不得在看到候选结果后改 policy。
- [ ] 对通过 offline 的候选运行 Shadow/Paper 门；保留所有失败/取消/insufficient evidence 结果，实际数据/模型 artifacts 不提交 Git。
- [ ] 用 SEALED request manifest 实际运行 tournament/verifier；缺 exact Phase 4/ReleasePolicy/target/execution/forward IDs 时立即失败：

```powershell
$phase5RequestManifest = $env:ASTRAQUANT_PHASE5_REQUEST_MANIFEST
if ([string]::IsNullOrWhiteSpace($phase5RequestManifest)) { throw 'ASTRAQUANT_PHASE5_REQUEST_MANIFEST is required' }
$phase5RunId = [guid]::NewGuid().ToString('n')
$phase5ResultRoot = "artifacts/research/phase-5/$phase5RunId"
uv run python tools/research/run_daily_tournament.py --request-manifest $phase5RequestManifest --output-root $phase5ResultRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python tools/verification/verify_phase_5.py --request-manifest $phase5RequestManifest --results-root $phase5ResultRoot --output "artifacts/verification/phase-5/$phase5RunId/verification.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```
- [ ] 运行：

```powershell
uv run pytest tests/domain/test_release_policy.py tests/research/test_release_policy.py tests/research/test_daily_tournament.py tests/research/test_budget_fairness.py tests/research/test_research_automation.py tests/research/test_rd_agent_manifest.py tests/quant/test_risk_model.py tests/quant/test_base_optimizer.py tests/quant/test_cost_model.py tests/quant/test_targets.py tests/quant/test_target_reconciler.py tests/quant/test_order_intents.py tests/quant/test_attribution.py tests/api/test_schema_registry.py tests/api/test_model_release_repository.py tests/api/test_model_release_service.py tests/api/test_shadow_service.py tests/api/test_promotion_service.py tests/integration/test_daily_target_execution.py tests/integration/test_shadow_event_parity.py -q
uv run ruff check packages tools tests
uv run ruff format --check packages tools tests
uv run mypy
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

- [ ] 退出结论只能二选一：某 ModelVersion 满足全部 offline+forward gates 并晋级 Paper/Mirror champion；或明确“暂无可发布模型”并保持 HOLD。两者都算诚实完成 Phase 5 研究，只有前者解锁 Phase 6 产品叠加实验。
- [ ] sign-off 固定 tournament/ReleasePolicy/target/execution/Shadow/Paper digests 与风险 limits。
- [ ] 提交：`git commit -m "test(quant): 完成日线冠军与目标组合验收"`

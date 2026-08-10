# Quant Core v3 Phase 6 Intraday T Overlay Stage Roadmap

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 在已批准 BaseTarget 周围建立分钟级 Intraday T Overlay，用真实分钟 API 数据公平评估基线、序列模型和 TSFM challengers，并证明两种做 T 顺序在 T+1、费用、延迟、容量与故障压力后的净增量价值。

**Architecture:** 分钟 forecast 不改写 BaseTarget，只产生有期限的 OverlayTarget；TPlanPlanner 在决策时明确 sleeve/type 并调用 Phase 2 TPlan/OMS。研究采用 Phase 4 Trial Ledger/lockbox，产品采用 Phase 5 Release/Shadow/Paper gates；L2 特征与 DeepLOB 类模型严格留到 Phase 7。

**Tech Stack:** Python 3.12、LightGBM/XGBoost/CatBoost、PyTorch GRU/TCN/N-HiTS/TSMixer/PatchTST/iTransformer isolated runners、TTM/Chronos-2/TimesFM 2.5/Moirai 2 isolated runners、Astra execution core、FastAPI/React。

---

## Task 1: 建立分钟数据成熟度与 SplitPolicy gate

**Files:**

- Create: `packages/research/src/astraquant_research/intraday_readiness.py`
- Create: `packages/research/src/astraquant_research/intraday_splits.py`
- Test: `tests/research/test_intraday_readiness.py`
- Test: `tests/research/test_intraday_splits.py`

- [ ] 先测试 coverage 连续性、session gaps、instrument/regime/liquidity breadth、PIT fidelity、independent session count 和 MinTRL；分钟 bar 数不能当独立样本夸大显著性。
- [ ] 编码 SplitPolicy v1：成熟轨 train=120 sessions、inner valid=20、outer OOS=next 5–20 sessions；当前不足时只允许 25/5/5 preliminary+Shadow，报告状态 `INSUFFICIENT_HISTORY_FOR_PRODUCTION`。
- [ ] 任何 split 修改创建新 experiment family，历史 attempts 仍计入多重检验；不能等看到收益后选择窗口。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 readiness report/split builder，与 Phase 1 minute snapshot/coverage/vintage identities 绑定。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 建立分钟数据成熟度门"`

## Task 2: 冻结 Intraday FeatureGraph/LabelSpec 与无技能基线

**Files:**

- Create: `packages/research/src/astraquant_research/intraday_features.py`
- Create: `packages/research/src/astraquant_research/intraday_labels.py`
- Create: `packages/research/src/astraquant_research/baselines/intraday.py`
- Test: `tests/research/test_intraday_features.py`
- Test: `tests/research/test_intraday_labels.py`
- Test: `tests/research/test_intraday_baselines.py`

- [ ] 先测试 feature 按交易日/session reset，所有滚动窗口只消费 decision-time visible minute observations；缺 bar/午休/跨日不 forward-fill 成未来信息。
- [ ] LabelSpec 以两种 TPlan 的合法下一可执行 entry/exit、matcher/latency/cost/RuleBook 计算净增量 outcome；不以同 bar close 或事后最低/最高价标注。
- [ ] 基线固定 no-trade、hold、intraday seasonality mean、VWAP/mean reversion、linear model；所有复杂模型必须相对 no-T Base champion 报 incremental metrics。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 feature/label/materialization 和 baseline adapters，输出 Phase 4 immutable snapshots/forecast contract。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 建立分钟特征标签与基线"`

## Task 3: 运行树模型与序列模型公平矩阵

**Files:**

- Create: `packages/research/src/astraquant_research/intraday_tournament.py`
- Create: `runners/intraday-sequence/pyproject.toml`
- Create: `runners/intraday-sequence/uv.lock`
- Create: `runners/intraday-sequence/.python-version`
- Create: `runners/intraday-sequence/runner-manifest.json`
- Create: `runners/intraday-sequence/src/astraquant_intraday_sequence_runner/__main__.py`
- Create: `runners/intraday-sequence/src/astraquant_intraday_sequence_runner/models.py`
- Test: `tests/research/test_intraday_tournament.py`
- Test: `tests/research/test_intraday_sequence_runner.py`

- [ ] 第一 tier 比较 linear、LightGBM、XGBoost/CatBoost；数据成熟且 tier 过冻结门后，第二 tier 比较 GRU/TCN、N-HiTS/TSMixer、PatchTST/iTransformer。
- [ ] 所有模型使用同一 exact feature/label/folds/cost/latency/capacity/seeds/HPO/wall-clock/GPU budgets；development>=5 seeds，final random models=20 seeds。
- [ ] 先测试 runner contract/env/lock、failure accounting、deterministic export/order 和 post-release contamination fields。
- [ ] 在编码 Runner 前重新核查各官方 repo 的维护版本，并在 `runner-manifest.json` 写 full upstream commit；manifest test 禁止 default branch/latest/空 hash。
- [ ] 实现 tournament/isolated runner，运行 `uv lock --project runners/intraday-sequence`；主 workspace 不安装深度模型依赖。
- [ ] 重跑 contract/synthetic tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 建立分钟序列模型竞赛"`

## Task 4: 分轨评估 TTM/Chronos-2/TimesFM/Moirai challengers

**Files:**

- Create: `runners/tsfm/ttm/pyproject.toml`
- Create: `runners/tsfm/ttm/uv.lock`
- Create: `runners/tsfm/ttm/.python-version`
- Create: `runners/tsfm/ttm/runner-manifest.json`
- Create: `runners/tsfm/ttm/src/astraquant_ttm_runner/__main__.py`
- Create: `runners/tsfm/chronos2/pyproject.toml`
- Create: `runners/tsfm/chronos2/uv.lock`
- Create: `runners/tsfm/chronos2/.python-version`
- Create: `runners/tsfm/chronos2/runner-manifest.json`
- Create: `runners/tsfm/chronos2/src/astraquant_chronos2_runner/__main__.py`
- Create: `runners/tsfm/timesfm25/pyproject.toml`
- Create: `runners/tsfm/timesfm25/uv.lock`
- Create: `runners/tsfm/timesfm25/.python-version`
- Create: `runners/tsfm/timesfm25/runner-manifest.json`
- Create: `runners/tsfm/timesfm25/src/astraquant_timesfm25_runner/__main__.py`
- Create: `runners/tsfm/moirai2/pyproject.toml`
- Create: `runners/tsfm/moirai2/uv.lock`
- Create: `runners/tsfm/moirai2/.python-version`
- Create: `runners/tsfm/moirai2/runner-manifest.json`
- Create: `runners/tsfm/moirai2/src/astraquant_moirai2_runner/__main__.py`
- Create: `packages/research/src/astraquant_research/tsfm_tournament.py`
- Test: `tests/research/test_tsfm_manifests.py`
- Test: `tests/research/test_tsfm_tournament.py`

- [ ] 先按官方仓库重新核查并固定 full commit、checkpoint hash、training/release cutoff、license-independent runtime、Python/dependency lock、hardware/precision；每个模型单独环境，禁止运行时隐式下载 latest。
- [ ] 分开报告 zero-shot、frozen backbone/linear head、LoRA 和 full fine-tune；不具备某赛道的模型标 capability absence，不伪造公平比较。
- [ ] post-release holdout 必须晚于可证明 checkpoint training/release cutoff；无法证明时 candidate 不进入 formal final。
- [ ] TSFM 只在树/序列 tier 与数据/预算门通过后运行；通用 forecasting score 不代替净增量 T PnL。
- [ ] 实现四个隔离 runner manifests/tournament adapter，并记录所有 failed/cancelled trials。生成锁文件：

```powershell
uv lock --project runners/tsfm/ttm
uv lock --project runners/tsfm/chronos2
uv lock --project runners/tsfm/timesfm25
uv lock --project runners/tsfm/moirai2
```
- [ ] 运行目标 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 接入受控时序预训练挑战组"`

## Task 5: 实现 Intraday Overlay 与 TPlanPlanner

**Files:**

- Create: `packages/quant/src/astraquant_quant/intraday_overlay.py`
- Create: `packages/quant/src/astraquant_quant/tplan_planner.py`
- Test: `tests/quant/test_intraday_overlay.py`
- Test: `tests/quant/test_tplan_planner.py`

- [ ] 先测试 overlay 有 valid-until/decay/uncertainty/cost threshold，BaseTarget immutable；forecast 无净成本后优势时 HOLD。
- [ ] Planner 在 decision 时选择 `T_SELL_THEN_BUYBACK` 或 `T_BUY_THEN_SELL_BASE`，固定 planned qty、两腿 policy、opening lot reservations、sleeve/budget/lineage；不靠后续成交猜 type。
- [ ] 最大 sell/buyback 受 opening sellable lots+active reservations、cash、BaseTarget bounds、lot/tick、decision-time liquidity forecast、participation/capacity、risk/close cutoff 约束。
- [ ] 测试 working orders projection 与其他 Base/T/Risk intents 内部净额；目标不可达输出 reason，不反复追单。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 overlay/planner，只生成 Target/TPlan commands，不自行制造 fill 或持仓。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(quant): 建立分钟覆盖层与做T规划"`

## Task 6: 完成 TPlan end-to-end、恢复与 attribution

**Files:**

- Modify: `tests/execution/test_tplan.py`
- Modify: `tests/quant/test_attribution.py`
- Create: `tests/integration/test_tplan_end_to_end.py`
- Create: `tests/integration/test_tplan_recovery.py`

- [ ] 覆盖两种顺序、leg1 partial→leg2 cap、cancel/retry、两腿之间重启、UNKNOWN report、cross-day、公司行动 lock、涨跌停/停牌、close cutoff。
- [ ] 验证 TPlan reservation→Order 原子 transfer，任何活动/UNKNOWN/reservation 存在时不能标 completed/aborted。
- [ ] 未回补必须是 `RESIDUAL_OVERNIGHT`、正式 Base/Risk attribution transfer 或明确 aborted zero residual；不为完成报表追价。
- [ ] Base/T/Risk PnL/cost/slippage/opportunity/overnight deviation 汇总精确等于 account journal。
- [ ] 先运行新增 tests 确认红灯，再补 integration wiring，最终全绿。
- [ ] 提交：`git commit -m "test(quant): 完成做T状态恢复与归因"`

## Task 7: 建立 Intraday release/Shadow/Paper evidence

**Files:**

- Create: `packages/api/migrations/versions/0016_intraday_t.py`
- Create: `packages/api/src/astraquant_api/intraday_strategy_service.py`
- Create: `packages/api/src/astraquant_api/intraday_schemas.py`
- Create: `packages/api/src/astraquant_api/intraday_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Modify: `packages/api/src/astraquant_api/schema_registry.py`
- Test: `tests/api/test_intraday_strategy_service.py`
- Test: `tests/api/test_intraday_routes.py`
- Modify: `tests/api/test_schema_registry.py`

- [ ] 0016 保存 immutable intraday model versions、overlay targets、TPlan run references、forward metrics/promotion decisions，`down_revision="0015_model_release_targets"`；同步更新 schema registry 与真实 0015→head parity test；不复制 execution journal。
- [ ] 先测试 Shadow/Paper candidate 使用同一 event IDs/Phase 2 core，Shadow 不改正式 account；1-minute p99 initial latency 必须小于 5s、inference success>=99.9%、replay digest=100%、violations=0。
- [ ] forward gate 至少满足 ReleasePolicy/MinTRL/预声明 regimes；历史不足时即使短期收益好也保持 Shadow/INSUFFICIENT_EVIDENCE。
- [ ] 所有 feature/model/threshold/RuleBook/FeeProfile/TPlan policy 改变创建新 version 并重置观察。
- [ ] 实现 cancellable/idempotent services/routes；无 daily Base champion 时返回 HOLD。
- [ ] 重跑 API/migration tests，期望全绿。
- [ ] 提交：`git commit -m "feat(api): 管理分钟做T运行与晋级"`

## Task 8: 展示 TPlan 和真实增量归因

**Files:**

- Modify: `apps/desktop/src/api/research-contracts.ts`
- Modify: `apps/desktop/src/api/paper-contracts.ts`
- Modify: `apps/desktop/src/api/queries.ts`
- Create: `apps/desktop/src/components/IntradayTPlanPanel.tsx`
- Create: `apps/desktop/src/components/IntradayTPlanPanel.test.tsx`
- Modify: `apps/desktop/src/pages/PaperPage.tsx`
- Modify: `apps/desktop/src/pages/StrategyLabPage.tsx`

- [ ] 先测试 UI 显示 T type、planned/leg/residual qty、reservations/working orders、state/recovery、base/T/risk attribution、gross→fee/slippage/opportunity→net incremental PnL。
- [ ] 历史不足/Shadow/Residual/Halted 明确 badge；不把两笔相邻交易自动标做 T，不用全期曲线掩盖 regime/fold failure。
- [ ] command 只调用 API，不在前端计算回补量/可卖量/费用。
- [ ] 运行 frontend tests，确认红灯。
- [ ] 实现 panel/contracts/queries，运行 test/check/build 全绿。
- [ ] 提交：`git commit -m "feat(ui): 展示做T计划与增量收益归因"`

## Task 9: 成本/延迟/容量 forward gate 与 Phase 6 sign-off

**Files:**

- Create: `packages/research/src/astraquant_research/intraday_stress.py`
- Create: `tools/research/run_intraday_tournament.py`
- Create: `tools/verification/verify_phase_6.py`
- Create: `docs/verification/quant-core-v3/phase-6-signoff.md`
- Test: `tests/research/test_intraday_stress.py`

- [ ] 固定并测试真实 BrokerFeeProfile、法定费用、base/adverse/severe 1x/1.5x/2x 不确定组件、额外 0/1/2 bar latency、参与率/容量、涨跌停/停牌/缺 bar/断线/revision。
- [ ] sizing 只用 decision-time completed historical minute volume 或 frozen forecast；initial P95 order<=5% 该量且<=1% ADV20，压力到 10%/5%；未来 bar volume 只能限制 matcher fill，不能反推 sizing。
- [ ] 真实 API minute snapshots 上运行同 folds/budget tournament 与 forward Paper；报告 Base-only vs Base+T paired incremental distribution、两种顺序、residual/overnight risks。
- [ ] 用 SEALED request manifest 调用真实 tournament/verifier；缺 minute/feature/label/BaseTarget/Fee/RuleBook/matcher/forward IDs 时立即失败：

```powershell
$phase6RequestManifest = $env:ASTRAQUANT_PHASE6_REQUEST_MANIFEST
if ([string]::IsNullOrWhiteSpace($phase6RequestManifest)) { throw 'ASTRAQUANT_PHASE6_REQUEST_MANIFEST is required' }
$phase6RunId = [guid]::NewGuid().ToString('n')
$phase6ResultRoot = "artifacts/research/phase-6/$phase6RunId"
uv run python tools/research/run_intraday_tournament.py --request-manifest $phase6RequestManifest --output-root $phase6ResultRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python tools/verification/verify_phase_6.py --request-manifest $phase6RequestManifest --results-root $phase6ResultRoot --output "artifacts/verification/phase-6/$phase6RunId/verification.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```
- [ ] 运行：

```powershell
uv run pytest tests/research/test_intraday_readiness.py tests/research/test_intraday_splits.py tests/research/test_intraday_features.py tests/research/test_intraday_labels.py tests/research/test_intraday_baselines.py tests/research/test_intraday_tournament.py tests/research/test_intraday_sequence_runner.py tests/research/test_tsfm_manifests.py tests/research/test_tsfm_tournament.py tests/research/test_intraday_stress.py tests/quant/test_intraday_overlay.py tests/quant/test_tplan_planner.py tests/quant/test_attribution.py tests/execution/test_tplan.py tests/integration/test_tplan_end_to_end.py tests/integration/test_tplan_recovery.py tests/api/test_schema_registry.py tests/api/test_intraday_strategy_service.py tests/api/test_intraday_routes.py -q
uv run ruff check packages tools tests
uv run ruff format --check packages tools tests
uv run mypy
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

- [ ] 只有足够独立真实历史+forward Paper、成本/延迟压力后 paired net incremental advantage、全部 T+1/TPlan/risk gates 同时通过才签可发布；否则保持 research/Shadow 并明确不足。
- [ ] 提交：`git commit -m "test(quant): 完成分钟做T正式验收"`

# Quant Core v3 Phase 3 Open-Source Differential Oracles Stage Roadmap

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 在 Phase 2 状态转换前冻结 RQAlpha/官方/Broker golden，内核完成后再做主差分与 WonderTrader/Hikyuu/vn.py 有限交叉，确保所有资金、持仓、可卖量和订单差异都可机器复现和解释。

**Architecture:** Tasks 1–3 是 Phase 2a Task 1 之后、任何 reducer 之前的强制 bootstrap；Tasks 4–8 在 Phase 2 完成后执行。每个 oracle 在独立环境读取同一 versioned scenario request，输出 normalized JSON trace；main pytest 只读取已记录 fixture，不联网、不导入外部框架、不自动改 golden。

**Tech Stack:** Python/uv isolated projects、JSON Schema、SHA-256 traces、RQAlpha `3503ab57932540cd36bf8375134e52c6923bf0d2`、WonderTrader `70feef13ef7cbc6d4c3333a6158a92b919311d48`、Hikyuu `7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95`、vn.py `fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09`。

---

## Task 1: 冻结 oracle request/trace/diff contract

**Files:**

- Create: `contracts/execution-oracle/v1/request.schema.json`
- Create: `contracts/execution-oracle/v1/trace.schema.json`
- Create: `tools/oracles/contracts.py`
- Create: `tools/oracles/diff_runner.py`
- Create: `tools/oracles/record_trace.py`
- Create: `tools/oracles/approve_trace.py`
- Create: `tools/oracles/seal_bootstrap.py`
- Test: `tests/differential/test_contracts.py`
- Test: `tests/differential/test_diff_runner.py`
- Create: `tests/differential/test_record_trace.py`
- Create: `tests/differential/test_approve_trace.py`
- Create: `tests/differential/test_bootstrap_lock.py`

- [ ] 先测试 contract version、scenario/input/policy/upstream/env/patch digests 必需；unknown fields/version、float cash、unordered trace、missing source mapping 全部拒绝。
- [ ] 先测试 EXACT 比较离散事件/Decimal，INVARIANT 运行命名公式，NOT_JUDGED 必须给 scope reason，EXPLAINED_DIVERGENCE 必须引用 ADR id。
- [ ] 运行目标 tests，确认模块/schema 缺失红灯。
- [ ] 实现 canonical JSON loader/validator、normalizer、non-mutating candidate diff、独立人工批准、must-not-exist/supersedes record 与 bootstrap seal commands；pytest 无 update-golden 参数。`record_trace` 必须消费已签 approval manifest，不能自己充当 reviewer 或覆盖既有 golden。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "test(differential): 冻结开源差分契约"`

## Task 2: 建立 RQAlpha 6.3.0 隔离 Runner

**Files:**

- Create: `runners/oracles/rqalpha/pyproject.toml`
- Create: `runners/oracles/rqalpha/uv.lock`
- Create: `runners/oracles/rqalpha/.python-version`
- Create: `runners/oracles/rqalpha/src/astraquant_rqalpha_oracle/__init__.py`
- Create: `runners/oracles/rqalpha/src/astraquant_rqalpha_oracle/__main__.py`
- Create: `runners/oracles/rqalpha/README.md`
- Create: `tests/differential/test_rqalpha_runner_contract.py`

- [ ] 先测试 Runner `--version-manifest` 精确输出 upstream commit、Python、lock digest、patch list 和 supported judgment matrix；commit 不是 `3503ab5...` 即拒绝。
- [ ] Runner 禁止下载/使用开源 bundle 或样例行情；Astra scenario 显式注入 instrument、bars、rules、fees/opening state。
- [ ] 运行 contract test，确认 Runner 缺失红灯。
- [ ] 实现 adapter，输出 RQAlpha Accepted/fill/cash/position/sellable/fee/matcher observations；未能从 API/source 直接证明的字段不伪造。
- [ ] 运行 `uv lock --project runners/oracles/rqalpha`，lockfile 单独保存且不加入 root workspace。
- [ ] 运行 `uv run --project runners/oracles/rqalpha --frozen python -m astraquant_rqalpha_oracle --version-manifest`，期望 manifest 验证通过。
- [ ] 提交：`git commit -m "build(oracle): 固定RQAlpha差分运行环境"`

## Task 3: 在内核前记录并封存 RQAlpha golden traces

**Files:**

- Create: `tests/fixtures/execution/oracles/rqalpha/manifest.json`
- Create: `tests/fixtures/execution/oracles/rqalpha/approval.json`
- Create: `tests/fixtures/execution/oracles/rqalpha/t1_and_t0.trace.json`
- Create: `tests/fixtures/execution/oracles/rqalpha/cash_fees_tax.trace.json`
- Create: `tests/fixtures/execution/oracles/rqalpha/oms_matching.trace.json`
- Create: `tests/fixtures/execution/oracles/rqalpha/tplan_mirror.trace.json`
- Create: `tests/differential/test_rqalpha_golden.py`
- Create: `tests/differential/test_trace_hashes.py`
- Create: `tests/fixtures/execution/oracles/bootstrap-lock.json`
- Create: `tools/verification/verify_phase_3_bootstrap.py`
- Create: `docs/verification/quant-core-v3/phase-3-bootstrap-signoff.md`

- [ ] 对 T+1 sellable、target unreachable、volume partial、停牌/涨跌停、parent-order minimum commission 等已核查行为定义 EXACT/INVARIANT judgment；RQAlpha 缺少的过户费、完整税务/Broker rounding 标 NOT_JUDGED。
- [ ] 保持 `tests/fixtures/execution/canonical/evidence-manifest.json` 永久只描述 official/Broker/source inputs，禁止写入 trace、verifier 或 sign-off digest。按 candidate→非变更校验→人工批准→record→hash verify→seal 的单向顺序显式运行：

```powershell
$bootstrapRunId = [guid]::NewGuid().ToString('n')
$bootstrapStage = "artifacts/oracles/rqalpha/$bootstrapRunId"
$bootstrapVerification = "artifacts/verification/phase-3-bootstrap/$bootstrapRunId/verification.json"
uv run --project runners/oracles/rqalpha --frozen python -m astraquant_rqalpha_oracle --scenarios tests/fixtures/execution/canonical --output $bootstrapStage
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python -m tools.oracles.diff_runner --scenarios tests/fixtures/execution/canonical --candidate $bootstrapStage --validate-only
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python -m tools.oracles.approve_trace --candidate $bootstrapStage --evidence-manifest tests/fixtures/execution/canonical/evidence-manifest.json --reviewer-manifest $env:ASTRAQUANT_ORACLE_REVIEWER_MANIFEST --output "$bootstrapStage/approval.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python -m tools.oracles.record_trace --scenarios tests/fixtures/execution/canonical --candidate $bootstrapStage --approval-manifest "$bootstrapStage/approval.json" --destination tests/fixtures/execution/oracles/rqalpha --must-not-exist
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python tools/verification/verify_phase_3_bootstrap.py --scenarios tests/fixtures/execution/canonical --recorded tests/fixtures/execution/oracles/rqalpha --output $bootstrapVerification
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python -m tools.oracles.seal_bootstrap --source-evidence tests/fixtures/execution/canonical/evidence-manifest.json --recorded tests/fixtures/execution/oracles/rqalpha --approval tests/fixtures/execution/oracles/rqalpha/approval.json --verification $bootstrapVerification --output tests/fixtures/execution/oracles/bootstrap-lock.json --must-not-exist
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

- [ ] `approve_trace` 前人工检查 normalized candidate 不含用户数据/路径/上游 bundle；approval 固定 reviewer/candidate/source evidence digests。record destination 已存在时必须拒绝，升级只能创建 superseding version。
- [ ] 运行 `uv run pytest tests/differential/test_rqalpha_golden.py tests/differential/test_trace_hashes.py tests/differential/test_bootstrap_lock.py -q`，期望 hash 与 judgment coverage 全绿；独立 `bootstrap-lock.json` 单向引用 scenario bundle、immutable source evidence、approval、recorded trace 与 verifier digests，Phase 2 reducer 同时验证 source manifest 与该 lock 才解锁，绝不回写任何被 trace 哈希的输入。
- [ ] 提交：`git commit -m "test(differential): 冻结内核前RQAlpha裁判"`

## Task 4: 对 Phase 2 内核运行 RQAlpha 主差分

**Files:**

- Create: `tests/differential/test_rqalpha.py`
- Modify: `tools/oracles/diff_runner.py`

- [ ] 先测试 Phase 2 实际 trace 必须引用与 golden 完全相同的 scenario/rule/fee/matcher inputs；任一 identity 不同返回 incomparable，不能做容差 diff。
- [ ] 对 sellable/target unreachable/partial/停牌/涨跌停/minimum commission 运行 EXACT/INVARIANT；Astra 扩展费用/税务字段只能按预声明 NOT_JUDGED，不能从总 cash 差异中隐藏。
- [ ] 从 Phase 2b verification manifest 解析其唯一 `{run_id}/execution-traces`（每个 scenario 的 normalized trace + manifest），运行 `uv run python -m tools.oracles.diff_runner --scenarios tests/fixtures/execution/canonical --actual artifacts/verification/phase-2b/{run_id}/execution-traces --recorded tests/fixtures/execution/oracles/rqalpha --check`，期望无 unexplained cash/position/sellable difference；禁止猜测固定 `local` 目录。
- [ ] 运行 `uv run pytest tests/differential/test_rqalpha.py -q`，确认 recorded golden 未被测试改写。
- [ ] 提交：`git commit -m "test(differential): 对统一内核运行RQAlpha主差分"`

## Task 5: 增加 WonderTrader/Hikyuu 局部交叉

**Files:**

- Create: `runners/oracles/wondertrader/runner-manifest.json`
- Create: `runners/oracles/wondertrader/run.ps1`
- Create: `runners/oracles/hikyuu/runner-manifest.json`
- Create: `runners/oracles/hikyuu/run.ps1`
- Create: `tests/fixtures/execution/oracles/wondertrader/manifest.json`
- Create: `tests/fixtures/execution/oracles/hikyuu/manifest.json`
- Create: `tests/differential/test_local_cross_checks.py`

- [ ] 固定源码 commit/compiler/runtime/build/patch digests；脚本从本地 pinned checkout/container 运行，不追随 default branch/latest binary。
- [ ] WonderTrader 只判断 target>=frozen、T1 frozen 与目标执行架构不变量；其挂单并发预占、费用与 HFT depth 缺口不能作为正确 oracle。
- [ ] Hikyuu 只判断明确核查的组合/费用构件；其 aggregate position/T+1 缺口记 explained divergence。
- [ ] 先写 recorded trace/hash tests，显式生成并人工批准 fixtures；main pytest 不要求安装两项目。
- [ ] 运行 `uv run pytest tests/differential/test_local_cross_checks.py -q`，期望全绿。
- [ ] 提交：`git commit -m "test(differential): 接入局部开源语义交叉"`

## Task 6: 建立 vn.py gateway report 与 Broker fixture 回放

**Files:**

- Create: `runners/oracles/vnpy/pyproject.toml`
- Create: `runners/oracles/vnpy/uv.lock`
- Create: `runners/oracles/vnpy/.python-version`
- Create: `runners/oracles/vnpy/src/astraquant_vnpy_oracle/__main__.py`
- Create: `tests/fixtures/execution/oracles/vnpy/manifest.json`
- Modify: `tests/fixtures/broker_reports/fill_before_ack.json`
- Modify: `tests/fixtures/broker_reports/reconnect_four_tables.json`
- Modify: `tests/fixtures/broker_reports/cancel_fill_race.json`
- Create: `tests/differential/test_broker_report_replay.py`

- [ ] 固定 vn.py commit `fa5206f...`；只映射 OrderData/TradeData/PositionData/AccountData/gateway callback，不使用其 Paper/portfolio backtester 做账本真相。
- [ ] 先测试 raw arrival fill→ACK、reconnect only fill、duplicate trade、cancel/fill race、same-watermark four tables；Astra 因果补录/恰好一次/对账结果固定。
- [ ] fixture 只包含脱敏、synthetic account ids 和 protocol facts，不含真实账户/订单。
- [ ] 实现隔离 mapper，运行独立 lock；记录 trace manifest/hash。
- [ ] 运行 `uv run pytest tests/differential/test_broker_report_replay.py -q`，期望全绿。
- [ ] 提交：`git commit -m "test(differential): 固定Broker回报与vn.py映射"`

## Task 7: 记录差异 ADR 与升级协议

**Files:**

- Create: `docs/architecture/adr/0004-execution-semantic-differences.md`
- Create: `docs/architecture/oracle-upgrade-runbook.md`
- Test: `tests/repository/test_oracle_manifests.py`

- [ ] 先测试每个 oracle manifest upstream full commit、env/lock/patch/trace hashes 完整，所有 explained divergence 引用 ADR 中存在的稳定 id。
- [ ] ADR 逐项说明 market/Broker facts、Astra 选择、RQAlpha/其他框架行为、comparison class 和 canonical trace；不为 diff 变绿复制 QUANTAXIS 费用/取消、Hikyuu T+1 或 vn.py 全量成交等缺陷。
- [ ] upgrade runbook 要求新 version 并存、全量 scenarios 重跑、diff review/ADR；禁止覆盖旧 trace 或只改 hash expectation。
- [ ] 运行 repository test，期望全绿。
- [ ] 提交：`git commit -m "docs(architecture): 记录交易语义差异与升级门"`

## Task 8: Phase 3 sign-off

**Files:**

- Create: `tools/verification/verify_phase_3.py`
- Create: `docs/verification/quant-core-v3/phase-3-signoff.md`

- [ ] 运行：

```powershell
uv run python -m tools.oracles.diff_runner --scenarios tests/fixtures/execution/canonical --recorded tests/fixtures/execution/oracles --check-recorded
uv run pytest tests/differential tests/repository/test_oracle_manifests.py -q
uv run ruff check tools/oracles tests/differential tests/repository
uv run ruff format --check tools/oracles tests/differential tests/repository
uv run mypy tools/oracles tests/differential tests/repository
```

- [ ] 在干净实现 commit 上以新 UUID 运行 `uv run python tools/verification/verify_phase_3.py --scenarios tests/fixtures/execution/canonical --recorded tests/fixtures/execution/oracles --actual artifacts/oracles --output artifacts/verification/phase-3/{run_id}/verification.json`；输出目录 must-not-exist，缺任一 required Runner 的当次 env/trace evidence 时不得只靠旧 fixture 签核新版本。

- [ ] 核对退出门：RQAlpha trace hashes=100% fixed；资金/持仓/可卖量 unexplained difference=0；其他差异都有机器报告+ADR；Broker report fixtures 全部 exactly-once/reconciliation 通过。
- [ ] sign-off 固定每个 oracle commit/lock/env/patch/trace digest 和 judgment coverage；缺本地外部 Runner 重跑证据时不能只凭 recorded fixture 声称新版本通过。
- [ ] 提交：`git commit -m "test(differential): 完成开源执行语义差分验收"`

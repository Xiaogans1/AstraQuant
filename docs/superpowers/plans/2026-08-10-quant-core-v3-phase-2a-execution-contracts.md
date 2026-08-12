# Quant Core v3 Phase 2a Execution Contracts and Golden Scenarios Stage Roadmap

> **生产训练硬约束：** 本阶段冻结的成交、费用和账户语义是[所有训练任务](../specs/2026-08-12-production-training-architecture-design.md)的统一可执行评价标准；任何模型不得使用更宽松的自定义成交语义获得优势。

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 在写交易状态转换前，先冻结 A 股 canonical scenarios、稳定领域契约、事件因果顺序和确定性双边 journal，为统一内核建立不可随实现结果修改的裁判基座。

**Architecture:** `astraquant_domain` 保存 immutable contracts；新的 `astraquant_execution` 只依赖 domain。命令产生原子 EventBatch，纯 reducer 派生账户投影；event id、source arrival、causal apply、journal tail 和 run manifest 共同决定精确重放。

**Tech Stack:** Python 3.12、Decimal、dataclasses/Enum、JSON Schema、pytest/Hypothesis、SHA-256、uv workspace。

---

## Task 1: 冻结 canonical scenario schema 与测试夹具

**Files:**

- Create: `tests/fixtures/execution/scenario.schema.json`
- Create: `tests/fixtures/execution/canonical/t1_and_t0.json`
- Create: `tests/fixtures/execution/canonical/cash_fees_tax.json`
- Create: `tests/fixtures/execution/canonical/oms_matching.json`
- Create: `tests/fixtures/execution/canonical/tplan_mirror.json`
- Create: `tests/fixtures/execution/canonical/evidence-manifest.json`
- Create: `tests/fixtures/broker_reports/fill_before_ack.json`
- Create: `tests/fixtures/broker_reports/reconnect_four_tables.json`
- Create: `tests/fixtures/broker_reports/cancel_fill_race.json`
- Create: `tests/execution/scenario_loader.py`
- Create: `tests/execution/test_scenario_contracts.py`
- Modify: `tests/domain/test_orders.py`

- [ ] 把 v3 设计 §17 每个 execution case 编码为 sealed inputs、commands/events、expected events/journal/invariants；金额用 decimal string，quantity 整数，时间带时区，source/causal sequence 明示；每个期望引用官方规则/Broker contract/source digest，不允许实现代码反推 expected。
- [ ] 覆盖昨 1000→今买 1000→卖 1000/再卖 1、目标 1000/0、ETF T+0 obligation、现金 trade/withdraw availability、三 fills minimum commission、拆单、partial/cancel/fill-before-ACK、BarOpen capacity=0、共享量、税务、两种 TPlan、MIRROR 分账。
- [ ] 将旧“源码不得出现 LIVE”测试改为 capability test：默认 build 没有可实例化真实下单 gateway；`RunMode.LIVE` 契约本身不授予发送能力。
- [ ] 运行 `uv run pytest tests/execution/test_scenario_contracts.py tests/domain/test_orders.py -q`，确认 loader/schema 尚不存在红灯。
- [ ] 实现只读 loader/schema validation；golden fixture 更新必须单独 code review，测试运行不能回写 expected values。
- [ ] 提交：`git commit -m "test(execution): 冻结A股统一内核场景契约"`

### Cross-plan prerequisite: 冻结外部 golden 后再写状态转换

- [ ] 立即执行 `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-3-open-source-oracles.md` 的 Tasks 1–3，生成已人工审阅且 hash 固定的 RQAlpha golden traces/runner manifest。
- [ ] 保持 `tests/fixtures/execution/canonical/evidence-manifest.json` 为 immutable source-input manifest；验证 Phase 3 生成的独立 `tests/fixtures/execution/oracles/bootstrap-lock.json`，它单向引用 scenario/source evidence/approval/RQAlpha trace/verifier digests，绝不把下游 digest 写回 source manifest。
- [ ] 在 bootstrap lock 与 source manifest 同时验证通过前，禁止开始本文件 Task 2 或 `astraquant_execution` reducer；RQAlpha 与官方/Broker 证据冲突时先写 ADR/修订并重新版本化 scenario/golden，不得让 Astra 实现结果决定 golden。

## Task 2: 新建 domain v3 execution contracts

**Files:**

- Create: `packages/domain/src/astraquant_domain/accounts.py`
- Create: `packages/domain/src/astraquant_domain/lots.py`
- Create: `packages/domain/src/astraquant_domain/attribution.py`
- Create: `packages/domain/src/astraquant_domain/targets.py`
- Create: `packages/domain/src/astraquant_domain/risk.py`
- Create: `packages/domain/src/astraquant_domain/reconciliation.py`
- Modify: `packages/domain/src/astraquant_domain/events.py`
- Modify: `packages/domain/src/astraquant_domain/orders.py`
- Modify: `packages/domain/src/astraquant_domain/fees.py`
- Modify: `packages/domain/src/astraquant_domain/corporate_actions.py`
- Modify: `packages/domain/src/astraquant_domain/valuation.py`
- Test: `tests/domain/test_execution_contracts.py`
- Create: `tests/domain/test_attribution_policies.py`

- [ ] 先测试事件同时保留 `raw_received_sequence` 与 `causal_apply_sequence`；order 的三个正交轴精确为 `OrderLifecycle`、`PendingAction`、`OrderSyncState`，`AccountReadiness` 是独立账户轴；Accepted 是领域事件而非第四状态轴，Fill 引用 accepted/market sequence。
- [ ] 先测试 settlement、sellability、reservation 正交；`OPENING_BALANCE_LOT` 可无 acquisition fill/time，明确 cost/PnL fidelity；security obligations 不因 inventory=0 消失。
- [ ] 先测试 cash、fee charge unit、tax exposure、TPlan、policy、readiness/reconciliation 全有 source/version/hash/lineage。
- [ ] 先测试 `LotDispositionPolicy` 固定 lot selection/partial disposition，`PnLAttributionPolicy` 固定 sleeve claims/priority/fee/slippage/rounding/remainder/residual allocation，`AttributionTransfer` 只能 append；成交后换 policy 不得改写历史 realized PnL。
- [ ] 运行目标 test，确认红灯。
- [ ] 实现 immutable value objects 与构造期不变量；domain 不 import database/UI/Qlib/vn.py。
- [ ] 保留现有 `portfolio.py`/`PaperOrder` DTO 作为 legacy projection，不再扩展为状态真相。
- [ ] 重跑 `uv run pytest tests/domain -q`，期望全绿。
- [ ] 提交：`git commit -m "feat(domain): 建立v3交易账户与审计契约"`

## Task 3: 创建 astraquant_execution workspace package

**Files:**

- Create: `packages/execution/pyproject.toml`
- Create: `packages/execution/src/astraquant_execution/__init__.py`
- Create: `packages/execution/src/astraquant_execution/py.typed`
- Modify: `pyproject.toml`
- Modify: `packages/api/pyproject.toml`
- Modify: `apps/desktop/src-tauri/src/runtime.rs`
- Modify: `tests/integration/test_runtime_round_trip.py`
- Create: `tests/execution/test_package.py`

- [ ] 先测试 main Python、API worker、Tauri Windows managed runtime 和 integration subprocess 都能 import `astraquant_execution`；package 依赖只含 `astraquant-domain`。
- [ ] 运行目标 tests，确认 package 缺失红灯。
- [ ] 更新 root dependencies、`[tool.uv.sources]`、workspace members、Ruff src/first-party、mypy files，API dependency 和动态 PYTHONPATH discovery；在 dev group 加固定范围 Hypothesis。
- [ ] 运行 `uv lock`，确保 lockfile 只新增计划内依赖且没有 Qlib/vn.py/RQAlpha。
- [ ] 在 PowerShell 中分开运行以下命令；每条命令立即检查退出码，前一条失败时不得继续或被后一条成功掩盖：

```powershell
uv run pytest tests/execution/test_package.py tests/integration/test_runtime_round_trip.py -q
if ($LASTEXITCODE -ne 0) { throw "execution package tests failed: $LASTEXITCODE" }
uv run mypy packages/execution/src
if ($LASTEXITCODE -ne 0) { throw "execution package mypy failed: $LASTEXITCODE" }
```
- [ ] 提交：`git commit -m "build: 注册统一交易内核包"`

## Task 4: 实现确定性 event journal 与 reducer 基座

**Files:**

- Create: `packages/execution/src/astraquant_execution/journal.py`
- Create: `packages/execution/src/astraquant_execution/engine.py`
- Create: `packages/execution/src/astraquant_execution/accounting.py`
- Test: `tests/execution/test_journal.py`
- Test: `tests/execution/test_determinism.py`

- [ ] 先测试同 timestamp 的 event priority/source sequence、event idempotency、execution id exactly-once、batch debit/credit 平衡、tail CAS、补偿事件、重放 projection 和 digest 相等。

```python
first = replay(sealed_commands, manifest=manifest)
second = replay(sealed_commands, manifest=manifest)
assert first.journal_digest == second.journal_digest
assert first.account_projection == second.account_projection
assert sum(e.base_amount for e in first.batch("fill-1")) == Decimal("0")
```

- [ ] 运行目标 tests，确认缺 journal/reducer 红灯。
- [ ] 实现 `ExecutionEngine.handle(command) -> EventBatch` 和纯 `reduce(state, event)`；repository 禁止直接 set cash/position/order state。
- [ ] canonical serialization 包含 manifest/policy/input hashes；相同 id 不同 payload、sequence rollback、unbalanced batch 均 fail closed。
- [ ] 固定 seed 重跑 determinism test 100 次，精确 digest 不漂移。
- [ ] 提交：`git commit -m "feat(execution): 建立确定性事件账本"`

## Task 5: 固化账本不变量与 Phase 2a sign-off

**Files:**

- Create: `tests/execution/test_account_invariants.py`
- Create: `tools/verification/verify_phase_2a.py`
- Create: `docs/verification/quant-core-v3/phase-2a-signoff.md`

- [ ] 用 Hypothesis 生成 command/event permutation，检查 cash/quantity/reservation/tax/fee/security obligations 守恒、terminal resources 归零、invalid transition 不改变 tail。
- [ ] 验证相同 sealed inputs/code/env/policies/randomness/event-order 的 run digest 精确重现；修改任一 identity 必须改变 manifest/run digest。
- [ ] 运行：

```powershell
uv run pytest tests/domain tests/execution/test_scenario_contracts.py tests/execution/test_journal.py tests/execution/test_determinism.py tests/execution/test_account_invariants.py -q
uv run ruff check packages/domain/src packages/execution/src tests/domain tests/execution tools/verification
uv run ruff format --check packages/domain/src packages/execution/src tests/domain tests/execution tools/verification
uv run mypy packages/domain/src packages/execution/src tests/domain tests/execution tools/verification
```

- [ ] 在干净实现 commit 上以 must-not-exist UUID 输出目录运行 `uv run python tools/verification/verify_phase_2a.py --scenarios tests/fixtures/execution/canonical --bootstrap-lock tests/fixtures/execution/oracles/bootstrap-lock.json --output artifacts/verification/phase-2a/{run_id}/verification.json`，由 verifier 重放 scenario/journal/determinism/property checks并固定 digests。

- [ ] sign-off 记录 contract/schema/scenario digests；实现尚未覆盖的 scenario 状态明确为 NOT_EXECUTED，不能提前声称 Phase 2 完成。
- [ ] 提交：`git commit -m "test(execution): 固化统一账本不变量"`

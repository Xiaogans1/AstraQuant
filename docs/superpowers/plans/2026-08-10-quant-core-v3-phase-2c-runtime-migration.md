# Quant Core v3 Phase 2c Runtime Migration Stage Roadmap

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 将 execution journal 原子持久化，并把 REPLAY/PAPER/MIRROR 的写入路径切换到同一内核，同时安全封存旧账、导入可验证 opening balance 和保持现有 UI 查询兼容。

**Architecture:** SQLite store 只 append event/journal batches 并用 expected-tail CAS 保证并发；projection 可删后重建但 journal 不可改写。`PaperLedger` 与旧 replay 变成兼容门面。MIRROR 维护 BrokerObservedAccount、MirrorSimulationFork 和派生 ProjectedAccount 三个边界，虚拟单永不进入真实 Broker 表。

**Tech Stack:** Python 3.12、SQLite/Alembic、FastAPI、React/TypeScript、pytest crash/concurrency tests、Phase 2b execution core。

---

## Task 1: 用 0013 建立 execution persistence schema

**Files:**

- Create: `packages/api/migrations/versions/0013_execution_journal.py`
- Create: `packages/paper/src/astraquant_paper/sqlite_store.py`
- Modify: `packages/api/src/astraquant_api/schema_registry.py`
- Test: `tests/paper/test_sqlite_store.py`
- Test: `tests/api/test_migration_config.py`
- Modify: `tests/api/test_schema_registry.py`

- [ ] 先测试 0012→0013 原地升级保留 legacy/data/rule tables；新建 execution events、journal entries、snapshots、report inbox、idempotency、account/fork anchors、immutable lot-disposition/PnL-attribution policy versions/transfer lineage 和 projection tables。
- [ ] 先测试 `BEGIN IMMEDIATE + expected_tail_sequence`：并发 writers 只有一个成功；进程在 batch/cursor/projection 任一点崩溃后恢复到完整事务边界。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 migration（`down_revision="0012_rulebook_reference_data"`）和 store 的 atomic append、read tail、snapshot+tail replay、digest verification；同步更新 schema registry 与真实 0012→head parity test；repository 不提供 update/delete journal API。
- [ ] snapshot 只是加速缓存，hash/tail 不匹配时丢弃并从 journal 重建。
- [ ] 重跑 tests 和 migration smoke，期望全绿。
- [ ] 提交：`git commit -m "feat(paper): 持久化统一交易事件账本"`

## Task 2: 建立 Paper runtime 与兼容 projections

**Files:**

- Create: `packages/paper/src/astraquant_paper/runtime.py`
- Create: `packages/paper/src/astraquant_paper/projections.py`
- Modify: `packages/paper/pyproject.toml`
- Modify: `packages/paper/src/astraquant_paper/ledger.py`
- Modify: `packages/paper/src/astraquant_paper/fees.py`
- Test: `tests/paper/test_runtime.py`
- Modify: `tests/paper/test_ledger.py`
- Modify: `tests/paper/test_fees.py`

- [ ] 先测试 Paper market feed→Accepted/matcher→execution engine→store；旧 DTO 由 v3 projection 生成，不再在 ledger 中即时整单成交或按日期变化解冻。
- [ ] 测试 quote/depth 缺失时 formal 不使用 last fallback；费用只来自 sealed FeeProfile/FeeChargeUnit。
- [ ] 运行目标 tests，确认旧行为与新期望冲突红灯。
- [ ] 让 `astraquant-paper` 显式依赖 `astraquant-execution` 并运行 `uv lock`；实现 runtime/projections，把 `ledger.py`/`fees.py` 改为 legacy/compatibility facade；删除内部第二套状态转换调用，但不删除用户历史数据。
- [ ] 重跑全部 `tests/paper`，期望全绿。
- [ ] 提交：`git commit -m "refactor(paper): 切换统一交易内核运行时"`

## Task 3: 将 Replay 改为 execution feed adapter

**Files:**

- Create: `packages/quant/src/astraquant_quant/replay_adapter.py`
- Modify: `packages/quant/pyproject.toml`
- Modify: `packages/quant/src/astraquant_quant/replay.py`
- Modify: `packages/data/src/astraquant_data/adapters/replay.py`
- Modify: `tests/quant/test_replay.py`
- Create: `tests/integration/test_execution_mode_parity.py`

- [ ] 先测试 replay feed 对相同时间以 event priority/source sequence 稳定排序，并产生分开的 BarOpen/BarClose events。
- [ ] 测试 signal at close 只能在下一可执行事件 Accepted/fill；`proba=None` 仍逐事件 valuation；期末持仓只 mark，不加入 cash/虚构清仓。
- [ ] 用相同 sealed market/command stream 在 REPLAY 与 PAPER simulated feed 比较离散 orders/fills/journal digest。
- [ ] 先测试从单独 wheel/隔离 subprocess 导入 `astraquant_quant.replay_adapter`，确认 `astraquant-quant` 的自身 metadata 声明 `astraquant-execution` 依赖，不依赖 root workspace 隐式 PYTHONPATH 或 API 包间接拉入。
- [ ] 运行目标 tests，确认旧 replay same-close/日期解冻/终值逻辑导致红灯。
- [ ] 在 `packages/quant/pyproject.toml` 的 `dependencies` 和 `[tool.uv.sources]` 分别加入 `astraquant-execution`/workspace source，运行 `uv lock` 并检查 lock diff；然后实现 adapter，把旧 `replay.py` 只保留 API compatibility/report projection，不再计算现金/T+1/费用。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "refactor(replay): 复用统一交易状态转换"`

## Task 4: 安全导入 legacy Paper opening balance

**Files:**

- Create: `packages/paper/src/astraquant_paper/legacy_import.py`
- Create: `tests/paper/test_legacy_import.py`
- Modify: `packages/api/src/astraquant_api/paper_repository.py`

- [ ] 先测试导入前必须对现金、持仓、活动单、成交四表与用户/Broker 证据核对；无法闭合时保持 legacy read-only。
- [ ] 测试聚合持仓创建 `OPENING_BALANCE_LOT(source_snapshot_id, acquisition_fill_id=None, acquisition_time=None, broker_reported_cost?, pnl_fidelity=INCOMPLETE) + UNKNOWN_TAX_LOT(acquisition_time=None,evidence_ids,unknown_reason)`，绝不伪造成交/取得日期或精确 realized PnL。
- [ ] 若历史 entitlement/分红/交割证据可证明有限税基上界，测试 import 只登记 `ConservativeDividendTaxExposure` 或有税基证据，不在 opening 确认 `tax_outstanding`；无有限上界时显式标记 `TAX_BASE_UNKNOWN`。
- [ ] 测试一次性 import idempotency、legacy seal、new run boundary 和 old/new performance segmentation。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 explicit preview→approve→atomic import commands；后续合格成交历史只能 append reconstruction event supersede projection。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(paper): 安全迁移旧账开盘余额"`

## Task 5: 分离 MIRROR observed/fork/projected 账本

**Files:**

- Create: `packages/paper/src/astraquant_paper/mirror.py`
- Create: `packages/execution/src/astraquant_execution/runtime.py`
- Test: `tests/integration/test_mirror_isolation.py`
- Test: `tests/integration/test_mirror_reanchor.py`

- [ ] 先测试 Broker opening 1000、虚拟卖 100：observed/Broker 仍 1000，simulation/projected 900；虚拟 Accepted/partial/fill 不写 broker order/fill 表。
- [ ] 先测试 READY 证据是 observed 四表同 Broker watermark + overlay anchor/event/matcher/journal 可重放，不要求反事实 projected 等于 Broker。
- [ ] 测试 anchor 后外部交易默认 `SEAL_AND_REANCHOR`；只有完整因果/预占处理可证明时才 `INJECT_AS_USER_EVENT`，否则 halt/seal，不静默覆盖。
- [ ] 测试 opening unknown-acquisition lot 但存在有限 `ConservativeDividendTaxExposure.amount_bound` 时，MIRROR fork 按冻结 `collection_source` 二选一形成 sell-receivable haircut 或 `contingent_tax_cash_reserved`，不得同时形成两者；`FROM_SELL_PROCEEDS` 在 current cash=0 时仍可提交风险卖单，observed 始终不变。
- [ ] 测试 opening lot 无法形成有限税基上界时为 `TAX_BASE_UNKNOWN`：Formal MIRROR simulation fork 单值虚拟卖出 fail closed，不伪造 haircut/reserve；exploratory 只输出不完整区间，Broker observed 不变。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现三账边界、readiness/reanchor state machine；MIRROR runtime 不持有可发送真实委托的 gateway capability。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(paper): 建立Mirror分账与重锚语义"`

## Task 6: 建立 execution API service 与幂等后台运行

**Files:**

- Create: `packages/api/src/astraquant_api/execution_service.py`
- Create: `packages/api/src/astraquant_api/execution_schemas.py`
- Create: `packages/api/src/astraquant_api/execution_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Modify: `packages/api/src/astraquant_api/paper_service.py`
- Modify: `packages/api/src/astraquant_api/paper_strategy_service.py`
- Test: `tests/api/test_execution_service.py`
- Test: `tests/api/test_execution_routes.py`
- Create: `tests/api/test_live_capability_boundary.py`
- Modify: `tests/api/test_paper_strategy_service.py`

- [ ] 先测试所有 start/cancel/recover/import/reanchor command 认证、idempotency、expected tail 和 exact policy/snapshot IDs；API/strategy service 不直接 signal→market order 或修改 projection rows。
- [ ] 先测试任何 `run_mode=LIVE` 的 start/recover/order command 在当前 build 都返回 `live_capability_unavailable/NOT_READY`，service container 中不存在 send/cancel gateway capability；只有 REPLAY/PAPER/MIRROR 可启动，MIRROR 也绝不发送真实委托。
- [ ] 测试 background run 可取消/恢复；Worker/feed adapter 不写 SQLite，API single writer 原子 ingest EventBatch。
- [ ] 测试无 READY/RuleBook/FeeProfile/approved model 时返回 HOLD/reason，不 fallback 到旧 model/replay。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 command/query separation、service/app wiring 和 legacy route adapters。
- [ ] 重跑 API tests，期望全绿。
- [ ] 提交：`git commit -m "feat(api): 暴露统一交易运行控制"`

## Task 7: 展示 lots/reservations/fees/tax/reconciliation

**Files:**

- Modify: `apps/desktop/src/api/paper-contracts.ts`
- Modify: `apps/desktop/src/api/queries.ts`
- Modify: `apps/desktop/src/pages/PaperPage.tsx`
- Modify: `apps/desktop/src/pages/PaperPage.test.tsx`
- Create: `apps/desktop/src/components/ExecutionAuditPanel.tsx`
- Create: `apps/desktop/src/components/ExecutionAuditPanel.test.tsx`

- [ ] 先测试 UI 显示 settled/sellable/reserved、trade/withdraw cash、FeeChargeUnit、tax outstanding/unpaid、readiness/watermarks、unreachable target reasons 和 raw→journal lineage。
- [ ] 测试 MIRROR observed 与 projected 分栏，不把虚拟成交标为 Broker 成交；legacy period 与 v3 period 不合并收益。
- [ ] 测试 command 按钮调用 API，不在前端推算可卖量/费用或直接修改本地账本。
- [ ] 运行 `pnpm --dir apps/desktop test`，确认红灯。
- [ ] 实现 contracts/query/components，并把大页面拆出审计面板，保持 accessibility/test ids。
- [ ] 运行 desktop test/check/build，期望全绿。
- [ ] 提交：`git commit -m "feat(ui): 展示统一交易账本与对账证据"`

## Task 8: Phase 2 runtime recovery/parity sign-off

**Files:**

- Create: `tests/integration/test_execution_recovery.py`
- Create: `tests/integration/test_execution_concurrency.py`
- Create: `tools/verification/verify_phase_2.py`
- Create: `docs/verification/quant-core-v3/phase-2-signoff.md`
- Modify: `docs/architecture/paper-trading-ledger.md`

- [ ] 故障注入进程终止、duplicate report、fill-before-ACK、cancel pending fill、writer race、projection corruption、MIRROR external trade；重启后重放不重复过账且 readiness 正确。
- [ ] 对全部 canonical scenarios 比较 REPLAY/PAPER/MIRROR simulation fork 的离散 state/journal digest；差异只能来自 manifest 中允许的 feed/report policy。
- [ ] 运行：

```powershell
uv run pytest tests/domain tests/execution tests/paper tests/quant tests/api/test_schema_registry.py tests/api/test_execution_service.py tests/api/test_execution_routes.py tests/api/test_live_capability_boundary.py tests/integration/test_execution_mode_parity.py tests/integration/test_execution_recovery.py tests/integration/test_execution_concurrency.py tests/integration/test_mirror_isolation.py tests/integration/test_mirror_reanchor.py -q
uv run ruff check packages tests tools
uv run ruff format --check packages tests tools
uv run mypy
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

- [ ] 在干净实现 commit 上创建 must-not-exist UUID 目录，运行 `uv run python tools/verification/verify_phase_2.py --scenarios tests/fixtures/execution/canonical --database artifacts/verification/phase-2/{run_id}/runtime-smoke.sqlite3 --output artifacts/verification/phase-2/{run_id}/verification.json`，重新执行 crash/concurrency/parity/MIRROR probes；数据库只存本地 synthetic evidence。

- [ ] 更新 ledger 文档：execution journal 为真相，legacy scalar ledger 只读；记录 opening import 与 Mirror 三账图。
- [ ] 核对完整 Phase 2 退出门：canonical semantics、journal invariants、crash recovery、concurrency、mode parity、MIRROR isolation 全绿；旧写路径=0。
- [ ] 提交：`git commit -m "test(runtime): 完成统一交易内核切换验收"`

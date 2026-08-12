# Quant Core v3 Phase 1b Canonical, Vintage, and Snapshot Stage Roadmap

> **生产训练硬约束：** canonical/snapshot 契约必须支撑[多任务、多周期、动态全市场训练](../specs/2026-08-12-production-training-architecture-design.md)，并为行业、概念、市场状态和后续关系模型保留可追溯输入；不得按当前十只或某个固定样本设计存储边界。

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 把合格 L0 capture 规范化为保留修订与可见性证据的 canonical observations，并通过质量/覆盖门发布为可递归验真的 immutable snapshot v2。

**Architecture:** `source_available_time`、本机 `observed_received_time` 和 `vintage_proven_time` 分开保存；运行模式派生 visible time。Stable content digest 与 publication identity 分离，formal read 每次重验 manifest、全部 files、祖先和 append-only publication chain，禁止按目录/hash 排序猜 latest。

**Tech Stack:** Python 3.12、PyArrow、Parquet、DuckDB、SHA-256、SQLite/Alembic、pytest property/fault tests。

---

## Task 1: 冻结 canonical observation 和时间契约

**Files:**

- Create: `packages/data/src/astraquant_data/canonical.py`
- Create: `packages/data/src/astraquant_data/canonical_schema.py`
- Modify: `packages/domain/src/astraquant_domain/market_data.py`
- Modify: `packages/data/src/astraquant_data/arrow_schema.py`
- Test: `tests/data/test_canonical_schema.py`
- Test: `tests/domain/test_market_data.py`

- [x] 先写 typed schema tests：interval start/end、source available、observed received、recorded、source revision/id、vintage id/value hash/supersedes/first received/proven、vintage kind、availability basis、capture row lineage 全部必需或有明确 nullable rule。
- [x] 先测试 raw OHLCV 只能是 `Adjustment.NONE`；API 请求 `adjust=1` 却标 NONE、未知单位/时区、重复 canonical key 不同 value 均 quarantine。
- [x] 先测试 bar 的 nominal `event_time/interval_end` 来自对应交易 session/bar close，不能由 source/receive/recorded time 代替；跨午休、半日市与时区转换均引用 exact calendar snapshot。
- [x] 运行目标 tests，确认字段/模块缺失红灯。
- [x] 实现 immutable domain/canonical records、Arrow schema metadata/version 和 normalization validators；价格用 Decimal-compatible integer scale 或声明的精确 Arrow decimal。
- [x] 不把 observed receive time 强行要求早于/等于 source available time；历史回补的两者可以相差多年。
- [x] 重跑 tests，期望全绿。
- [x] 提交：`git commit -m "feat(data): 建立规范市场数据契约"`

## Task 2: 实现 AS_DELIVERED/PIT_STRICT/online 可见性

**Files:**

- Create: `packages/data/src/astraquant_data/temporal.py`
- Test: `tests/data/test_temporal_visibility.py`

- [x] 先编码 2010 bar 在 2026 首次抓取、随后修订的 scenario：

```python
assert visible_at(old_bar, ReplayAsDelivered()) == old_bar.source_available_time
assert not is_visible(old_bar, ReplayPitStrict(), decision_time=datetime(2015, 1, 1, tzinfo=UTC))
assert not is_visible(
    old_bar, PaperOnline(), decision_time=old_bar.observed_received_time - EPSILON
)
assert revised_bar.vintage_id != old_bar.vintage_id
```

- [x] 测试 REPLAY_AS_DELIVERED 报告必须披露 data vintage cutoff/占比且不能标 PIT_STRICT；PIT_STRICT 只能在 proven+available 后消费 exact version；PAPER/MIRROR 使用 max(source available, observed receive, source revision)。
- [x] 覆盖 LIVE 与 PAPER/MIRROR 同一 online visibility contract；按 `vintage_kind` 推导/验证 `vintage_proven_time`：source-certified/versioned 使用权威 revision proof，locally-observed 使用首次观测证据，unversioned 不得伪造严格 PIT proof。
- [x] 运行 `uv run pytest tests/data/test_temporal_visibility.py -q`，确认红灯。
- [x] 实现 `VisibilityPolicy`、`RevisionPolicy`、`VintageMode` 和 reasoned rejection；旧 decision 不被新 revision 回写。
- [x] 重跑 tests，期望全绿。
- [x] 提交：`git commit -m "feat(data): 实现版本化时间可见性"`

## Task 3: 建立 coverage 与正式质量门

**Files:**

- Create: `packages/data/src/astraquant_data/coverage.py`
- Modify: `packages/data/src/astraquant_data/quality.py`
- Modify: `packages/data/src/astraquant_data/calendars.py`
- Test: `tests/data/test_coverage.py`
- Test: `tests/data/test_quality.py`
- Test: `tests/data/test_calendars.py`

- [x] 先测试 schema/单位/OHLCV/session/duplicate/pagination/aggregation、分钟缺段、公司行动断点、universe/status gap、修订冲突和日线覆盖。
- [x] 先测试 coverage denominator 来自历史 instrument lifecycle/calendar，不用今天仍上市的 universe 反推过去；listing 前/delisting 后不算缺口。
- [x] 运行目标 tests，确认红灯。
- [x] 实现 role-aware quality policy、coverage bitmap/summary 和 quarantine reason；每个 threshold 有版本/source/hash，不能把 warning 当 PASS。
- [x] 日线与分钟质量报告分轨，分钟按 session segment/expected bar count 计算，静默 5000 条截断必须被发现。
- [x] 重跑 tests，期望全绿。
- [x] 提交：`git commit -m "feat(data): 建立历史覆盖与正式质量门"`

## Task 4: 升级 Manifest/ParquetStore 为 snapshot v2

**Files:**

- Modify: `packages/data/src/astraquant_data/manifests.py`
- Modify: `packages/data/src/astraquant_data/parquet_store.py`
- Create: `tests/data/test_snapshot_v2.py`
- Modify: `tests/data/test_parquet_store.py`

- [x] 先测试同一 canonical rows/code/config 在不同重抓中 `content_digest` 相同，但 capture/publication lineage 不同使 `snapshot_id` 不同；任一 cutoff/policy/parent/file byte 改变都会改变相应 digest。
- [x] 先测试 manifest v2 固定 captures/raw/file hashes、parents/supersedes、evidence、vintage/PIT/revision/availability、coverage、quality 和 environment/code identities。
- [x] 运行目标 tests，确认红灯。
- [x] 实现 canonical serialization、stable content digest 和 publication id；v1 仍可读取但返回 legacy evidence。
- [x] Parquet writer 使用 temp materialization 与 fsync/atomic rename；未 seal 目录不对 query 可见。
- [x] 重跑 tests，期望全绿。
- [x] 提交：`git commit -m "feat(data): 升级不可变数据快照契约"`

## Task 5: 建立 publication ledger 与 formal read verifier

> **2026-08-11 priority:** 延后到模型晋级 Shadow/Paper 前。当前 snapshot v2 的内容身份、来源身份和原子发布已足够支撑策略研究；本 Task 的防回滚 trusted head 不再阻塞基线模型、Qlib 与回测开发。

**Files:**

- Create: `packages/data/src/astraquant_data/publication_ledger.py`
- Create: `packages/data/src/astraquant_data/publication_anchor.py`
- Modify: `packages/data/src/astraquant_data/query.py`
- Create: `packages/api/migrations/versions/0011_snapshot_v2.py`
- Create: `packages/api/src/astraquant_api/publication_anchor_service.py`
- Modify: `packages/api/src/astraquant_api/secret_store.py`
- Modify: `packages/api/src/astraquant_api/schema_registry.py`
- Test: `tests/data/test_publication_ledger.py`
- Test: `tests/data/test_publication_anchor.py`
- Modify: `tests/data/test_query.py`
- Modify: `tests/api/test_secret_store.py`
- Create: `tests/api/test_publication_anchor_service.py`
- Modify: `tests/api/test_schema_registry.py`
- Test: `tests/api/test_data_repository.py`

- [ ] 先测试 append-only hash chain、atomic catalog commit、batch Merkle root、Ed25519 checkpoint signature、trusted-head monotonic sequence、rollback/truncation detection 和 identical retry idempotency。攻击者同时截断/改写 files、SQLite catalog 与 ledger 时，受保护 trusted head 仍必须发现回滚。
- [ ] 先测试 formal query 只接 exact snapshot id；按 hash 字典序/mtime/目录排序选 latest、manifest-only 校验、跳过 parent recursion 均被测试捕获。
- [ ] 先测试 signing key/key-version 和 latest trusted `(sequence, merkle_root, checkpoint_digest)` 由 OS SecretStore/受保护介质持有，不与 mutable catalog/ledger 共存；key rotation 保留旧 public verification chain，SecretStore 不可用时 formal publication/read fail closed。
- [ ] 先测试 approval 按 capture time 选择当时有效的 immutable approval：普通 `SUPERSEDED`/`REVOKED` 只阻止 effective time 后的新 capture，不使旧 sealed snapshot 改写；仅显式 `RETROACTIVE_COMPROMISE` 隔离受影响的历史 evidence。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 ledger chain、Merkle proof/checkpoint signer 与 reader 的 manifest+all files+parents+publication proof+trusted head 全校验；cycle、missing ancestor、retroactive compromise、content collision 统一 fail closed。更正只能发布新 vintage/checkpoint，不能重写旧 ledger。
- [ ] 在 0011 创建 snapshot v2/catalog/publication chain/checkpoint/quality/coverage tables，`down_revision="0010_provider_qualification_capture"`；从 0009 legacy 行不自动转 formal；同步更新 schema registry 与真实 0010→head parity test。
- [ ] 重跑 tests 和 migration smoke，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 发布可递归验证的不可变快照"`

## Task 6: 编排 normalize/quality/publish 管线

**Files:**

- Create: `packages/api/src/astraquant_api/snapshot_publication_service.py`
- Modify: `packages/api/src/astraquant_api/formal_data_worker.py`
- Modify: `packages/api/src/astraquant_api/formal_data_routes.py`
- Create: `tests/api/test_snapshot_publication_service.py`
- Modify: `tests/api/test_formal_data_routes.py`

- [ ] 先测试 worker 产出 canonical temp artifact/result digest，API 单写者重新校验 capture/qualification/coverage/quality 后才 publish；取消/崩溃不能暴露半成品。
- [ ] 先测试相同 idempotency key 解析到同一 sealed input/result；运行期间 parent 改变、capture time 无有效 approval 或发生 `RETROACTIVE_COMPROMISE` 时拒绝 commit。普通事后 supersede/revoke 不能反向改变已 sealed capture 的资格事实。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现两段式 worker→API publish command；长任务有 progress、cancel、resume token 和 audit event。
- [ ] route 的 query 返回 vintage/pit/coverage/evidence 状态，不给 UI 提供“重命名为 formal”的 mutation。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(api): 编排规范数据快照发布"`

## Task 7: Phase 1b lineage 与故障注入验收

**Files:**

- Create: `tests/integration/test_formal_data_lineage.py`
- Create: `tools/verification/verify_phase_1b.py`
- Create: `docs/verification/quant-core-v3/phase-1b-signoff.md`

- [ ] pytest 中的脱敏 capture fixture 始终标 `TEST_ONLY`：允许验证 EXPLORATORY normalize→quality→publication，但 FORMAL admission 必须拒绝；再逐一篡改 raw、file、manifest、ancestor、ledger tail、approval 与 revision proof，全部被拒绝。
- [ ] 在受控环境由 verification CLI 读取 Phase 1a 已实际批准且位于 formal capture store 的 exact `capture_id`，执行 formal normalize→quality→publication→read；对同一真实 API 日线/分钟 capture 重跑两次，验证 stable content digest、明确 publication identities 和可重复 rows，只保存 digest/脱敏摘要到 sign-off。
- [ ] 运行：

```powershell
uv run pytest tests/data/test_canonical_schema.py tests/data/test_temporal_visibility.py tests/data/test_coverage.py tests/data/test_quality.py tests/data/test_snapshot_v2.py tests/data/test_parquet_store.py tests/data/test_publication_ledger.py tests/data/test_publication_anchor.py tests/data/test_query.py tests/api/test_schema_registry.py tests/api/test_publication_anchor_service.py tests/api/test_snapshot_publication_service.py tests/integration/test_formal_data_lineage.py -q
uv run ruff check packages/domain/src packages/data/src packages/api/src tools/verification tests/domain tests/data tests/api tests/integration
uv run ruff format --check packages/domain/src packages/data/src packages/api/src tools/verification tests/domain tests/data tests/api tests/integration
uv run mypy packages/domain/src packages/data/src packages/api/src tools/verification tests/domain tests/data tests/api tests/integration
```

- [ ] 调用真实证据 verifier；缺环境变量必须立即失败，不能降级使用 fixture：

```powershell
$phase1bCaptureId = $env:ASTRAQUANT_PHASE1B_CAPTURE_ID
if ([string]::IsNullOrWhiteSpace($phase1bCaptureId)) { throw 'ASTRAQUANT_PHASE1B_CAPTURE_ID is required' }
$phase1bRunId = [guid]::NewGuid().ToString('n')
uv run python tools/verification/verify_phase_1b.py --capture-id $phase1bCaptureId --output "artifacts/verification/phase-1b/$phase1bRunId/verification.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

- [ ] 核对退出门：formal read hash/ancestor/ledger/Merkle/trusted-head 校验=100%；整体 catalog+ledger+files 回滚检出率=100%；AS_DELIVERED 冒充 PIT_STRICT=0；今天抓取的旧历史被伪造为当年 vintage=0；schema/截断/修订故障全部 quarantine 或新 vintage。
- [ ] 提交：`git commit -m "test(data): 完成版本快照证据链验收"`

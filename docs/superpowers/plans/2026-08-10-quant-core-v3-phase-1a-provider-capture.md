# Quant Core v3 Phase 1a Provider Qualification and Capture Stage Roadmap

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 对每个真实 API endpoint 独立证明身份、权限、schema、范围和修订行为，并把每次请求/原始响应保存为不可变、可审计的 L0 Capture。

**Architecture:** Provider identity 由 vendor/product/endpoint/interface build/permission/schema fingerprint 构成；资格只批准具体 capability，不批准一个模糊“供应商”。Eastmoney 是当前 bootstrap provider，`gm_python_sdk` 是 interface，NDJSON 是 transport。正式 Worker 只消费已批准 qualification 并产出 sealed capture，不直接发布 canonical snapshot。

**Tech Stack:** Python 3.12、Eastmoney bridge、NDJSON、SHA-256、SQLite/Alembic、FastAPI background tasks、pytest fault injection。

---

## Task 1: 冻结 ProviderIdentity 与 QualificationReport

**Files:**

- Create: `packages/data/src/astraquant_data/provider_identity.py`
- Create: `packages/data/src/astraquant_data/provider_qualification.py`
- Test: `tests/data/test_provider_qualification.py`

- [x] 先写测试：同 vendor 的日线、分钟、公司行动、历史状态和 L2 是不同 endpoint/capability；interface build、permission tier 或 schema fingerprint 改变后旧 approval 不再适用。
- [x] 测试 approval 必须引用 probe request/raw response digests、coverage、退市标的、adjust/units、pagination/truncation、revision、rate limit、schema evolution 和 reviewer/policy version。
- [x] 运行 `uv run pytest tests/data/test_provider_qualification.py -q`，确认缺模块红灯。
- [x] 实现 immutable identity、capability result、qualification state machine 与 stable report digest；默认 `UNQUALIFIED`，一次成功请求不能自动审批。撤销类型至少区分 `SUPERSEDED`、普通 `REVOKED` 与会隔离历史证据的 `RETROACTIVE_COMPROMISE`，并固定 effective time。
- [x] 对 `vendor="eastmoney"`、`interface="gm_python_sdk"`、`transport="ndjson_bridge"` 分字段建模，禁止 `Eastmoney/GM` 合并字符串作为身份。
- [x] 重跑测试，期望全绿。
- [x] 提交：`git commit -m "feat(data): 建立真实数据源资格契约"`

## Task 2: 扩展 bridge/client 的原始证据与分页协议

**Files:**

- Modify: `tools/eastmoney_bridge.py`
- Modify: `tools/eastmoney_probe.py`
- Modify: `packages/data/src/astraquant_data/eastmoney_protocol.py`
- Modify: `packages/data/src/astraquant_data/eastmoney_client.py`
- Test: `tests/repository/test_eastmoney_bridge.py`
- Test: `tests/repository/test_eastmoney_probe.py`
- Test: `tests/data/test_eastmoney_protocol.py`
- Test: `tests/data/test_eastmoney_client.py`

- [ ] 先测试 response 保留 canonical request、SDK/terminal build、permission、request/received timestamps、page cursor/count/declared total、retry lineage 和 observed schema；`response_representation` 明确为 `PROVIDER_RAW_BYTES` 或 `SDK_OBJECT_CANONICAL`。SDK 不暴露 HTTP bytes 时，保存带 serialization version、dtype/schema 的 canonical SDK object，禁止把 bridge JSON 冒充 provider raw bytes；secret 永不进入 stdout/report/hash input。
- [ ] 先故障注入：重复页、遗漏页、静默截断、success code+空数据、日期越界、schema/单位/adjust drift 和 out-of-order chunk 全部返回 typed failure。
- [ ] 运行四组 tests，确认新增字段/错误尚不存在而失败。
- [ ] 扩展 NDJSON request/response contract；每行有 contract version 和 correlation id，未知 contract/schema fail closed。
- [ ] client 支持显式 date range/pagination，不能以“最后一页少于 limit”作为唯一 completeness 证明。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 固化Eastmoney原始调用证据"`

## Task 3: 实现 qualification CLI 与人工批准记录

**Files:**

- Create: `tools/data/qualify_eastmoney.py`
- Create: `packages/api/migrations/versions/0010_provider_qualification_capture.py`
- Create: `packages/api/src/astraquant_api/capture_repository.py`
- Create: `packages/api/src/astraquant_api/provider_qualification_schemas.py`
- Create: `packages/api/src/astraquant_api/provider_qualification_service.py`
- Create: `packages/api/src/astraquant_api/provider_qualification_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Modify: `packages/api/src/astraquant_api/schema_registry.py`
- Test: `tests/api/test_capture_repository.py`
- Test: `tests/api/test_provider_qualification_routes.py`
- Modify: `tests/api/test_schema_registry.py`
- Test: `tests/research/test_eastmoney_qualification_cli.py`

- [ ] 先测试 CLI 只执行/保存 probe，不因结果全绿自动 APPROVED；批准/撤销必须通过 authenticated API command 和 API 单写者事务，带 reviewer、policy version、report digest、revocation kind 与 effective interval。CLI 不得绕过 route 直接写 repository。
- [ ] 先测试 report/approval append-only；revocation 新增记录，不更新历史行；permission/schema/build 变化使旧 approval lookup 失败。普通 supersede/revoke 只阻止 effective time 后的新 capture，`RETROACTIVE_COMPROMISE` 才隔离历史 lineage。
- [ ] 运行目标 tests，确认红灯。
- [ ] 在 0010 创建 provider identity、qualification report、approval/revocation 和 capture index 表，`down_revision="0009_v3_legacy_evidence"`；不保存 token/cookie/raw payload；同步更新 schema registry 与真实 0009→head parity test。
- [ ] 实现 repository compare-and-append、identity uniqueness、authenticated approve/revoke schema/service/routes 与 audit events；API 是唯一 approval writer。
- [ ] 实现 CLI 的日线/分钟/退市标的/修订 probe 矩阵，正文写入 Phase 0 `RuntimeConfig.formal_qualification_root`，CLI 经 authenticated API 提交审批命令；不得使用硬编码 `.astraquant/qualification` 或输出正文到 Git。
- [ ] 重跑 tests 和 migration smoke，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 持久化数据源资格与审批"`

## Task 4: 建立不可变 CaptureEnvelope/Store

**Files:**

- Create: `packages/data/src/astraquant_data/capture.py`
- Create: `packages/data/src/astraquant_data/capture_store.py`
- Test: `tests/data/test_capture_store.py`

- [ ] 先写 tests 覆盖 request canonical bytes、response representation/canonical bytes/hash、requested/received/recorded、serialization version/dtype/schema/units/adjust、pages/retries、qualification id、chunk parent seal 和 idempotent duplicate。
- [ ] 先测试已经 seal 的 capture 发生一字节变化、parent 缺 chunk、相同 id 不同 payload、secret-like field 未 redact 均拒绝。
- [ ] 运行 `uv run pytest tests/data/test_capture_store.py -q`，确认红灯。
- [ ] 实现 append-only chunks 与 atomic parent seal；seal 前可继续追加已验证 chunk，seal 后只能读取或创建 superseding capture。
- [ ] object layout 由 digest 派生，不以“最新目录”决定身份；request identity 排除 secret 值但保留 permission/endpoint 语义。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 持久化不可变原始采集证据"`

## Task 5: 实现 Eastmoney batch adapter

**Files:**

- Create: `packages/data/src/astraquant_data/adapters/eastmoney_batch.py`
- Test: `tests/data/test_eastmoney_batch.py`
- Modify: `packages/data/src/astraquant_data/adapters/eastmoney.py`

- [ ] 先测试日线按 instrument lifecycle/明确区间覆盖；分钟按交易日和时间段切 chunk，不假定一次 5000 条响应足够约 51 个交易日数据。
- [ ] 先测试 chunk overlap reconciliation、expected sessions、分页 completeness 和 capture seal；任何缺口返回 incomplete report，不发布“尽力而为”结果。
- [ ] 运行 `uv run pytest tests/data/test_eastmoney_batch.py tests/data/test_eastmoney_provider.py -q`，确认红灯。
- [ ] 实现专用 batch adapter；现有 `eastmoney.py` 保留 live/UI legacy，不把两条路径混成同一 evidence class。
- [ ] adapter 只输出 CaptureEnvelope，不直接构造 formal Bar/Parquet。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 实现Eastmoney分块采集适配器"`

## Task 6: 编排 formal capture background tasks

**Files:**

- Create: `packages/api/src/astraquant_api/formal_data_worker.py`
- Create: `packages/api/src/astraquant_api/formal_data_schemas.py`
- Create: `packages/api/src/astraquant_api/formal_data_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Create: `tools/data/backfill_eastmoney.py`
- Create: `tools/data/increment_eastmoney.py`
- Create: `tools/data/reconcile_eastmoney.py`
- Test: `tests/api/test_formal_data_worker.py`
- Create: `tests/api/test_formal_data_routes.py`

- [ ] 先测试 command 在创建时解析并固定 qualification id、provider identity、instrument/date range、expected coverage 和 policy digest；API 重试同 idempotency key 得到同一 task。
- [ ] 先测试 Worker 无 SQLite write capability，只返回 sealed capture digest/result message；取消保留完整 chunks，但不伪造 parent seal。
- [ ] 先测试 route 需要本地认证，不回显 token/raw payload/path；旧 `data_worker.py`、AKShare、CSV 不能被 formal route 选择。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 worker/route/app wiring 与 backfill/increment/reconcile CLI；所有长任务可取消、可恢复且 audit trail 完整。
- [ ] 重跑 tests 与 `tests/integration/test_runtime_round_trip.py`。
- [ ] 提交：`git commit -m "feat(api): 编排正式真实接口采集任务"`

## Task 7: Phase 1a endpoint 实证验收

**Files:**

- Create: `tools/verification/verify_phase_1a.py`
- Create: `docs/verification/quant-core-v3/phase-1a-signoff.md`

- [ ] 运行单元/故障注入门：

```powershell
uv run pytest tests/data/test_provider_qualification.py tests/data/test_eastmoney_protocol.py tests/data/test_eastmoney_client.py tests/data/test_capture_store.py tests/data/test_eastmoney_batch.py tests/api/test_capture_repository.py tests/api/test_provider_qualification_routes.py tests/api/test_formal_data_worker.py tests/api/test_formal_data_routes.py tests/api/test_schema_registry.py -q
uv run ruff check packages/data/src packages/api/src tools/data tests/data tests/api
uv run ruff format --check packages/data/src packages/api/src tools/data tests/data tests/api
uv run mypy packages/data/src packages/api/src tools/data tests/data tests/api
```

- [ ] 调用 verifier 复核受控环境产生的 exact qualification/capture IDs；缺真实 evidence manifest 时立即失败：

```powershell
$phase1aEvidenceManifest = $env:ASTRAQUANT_PHASE1A_EVIDENCE_MANIFEST
if ([string]::IsNullOrWhiteSpace($phase1aEvidenceManifest)) { throw 'ASTRAQUANT_PHASE1A_EVIDENCE_MANIFEST is required' }
$phase1aRunId = [guid]::NewGuid().ToString('n')
uv run python tools/verification/verify_phase_1a.py --evidence-manifest $phase1aEvidenceManifest --output "artifacts/verification/phase-1a/$phase1aRunId/verification.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

- [ ] 在有真实权限的受控环境分别 probe 日线、分钟、公司行动/历史状态 endpoint；未实际 probe 的 capability 保持 UNQUALIFIED，测试 fixture 不能代替。
- [ ] 对重复/遗漏分页、静默截断、schema/adjust/units drift、permission/build change 做真实或录制故障回放，100% 阻止 seal/admission。
- [ ] 在干净实现 commit 上验证；sign-off 以独立 docs-only commit 固定该 commit、qualification report/approval/capture digests、覆盖范围和未批准能力；原始数据与凭据不提交 Git。
- [ ] 提交：`git commit -m "test(data): 完成真实数据源采集资格验收"`

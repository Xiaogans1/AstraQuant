# Phase 1a Task 6 Formal Capture Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立只接受服务器端冻结命令、只调用已批准 Eastmoney identity、只产出 sealed CaptureEnvelope 的正式采集 API/worker/CLI，并与 legacy fixture/AKShare/CSV 路径物理隔离。

**Architecture:** API 单写者先用 exact approval timeline 与受信 coverage resolver 生成 `ResolvedFormalCaptureCommand`；客户端不能提交 session 列表或自报 coverage。子进程只读取已冻结命令、凭据和 formal capture root，不导入 SQLAlchemy/repository；它逐 chunk 调 bridge、写 CaptureStore、检查取消，只有完整 coverage 才 seal 并回传 digest。Phase 1c 的官方 calendar/status adapter 尚未注入时 route fail closed 为 unavailable，不能用 weekday/current-universe 猜测替代。

**Tech Stack:** Python 3.12、Pydantic v2、FastAPI、multiprocessing worker messages、Eastmoney NDJSON bridge、CaptureStore、pytest、Ruff、mypy。

---

### Task 1: 冻结 formal command 与服务端 admission

**Files:**
- Create: `packages/api/src/astraquant_api/formal_data_schemas.py`
- Create: `packages/api/src/astraquant_api/formal_data_service.py`
- Test: `tests/api/test_formal_data_worker.py`

- [x] **Step 1: 写命令冻结红灯**：测试 inbound request 只能包含 `approval_id/instrument_id/frequency/start/end/adjustment`；`TrustedCoverageResolver.resolve()` 返回 exact sessions、`coverage_membership_digest`、`policy_digest`；service 从 `QualificationRepository.get_timeline_for_approval()` 固定 identity/report/approval，并拒绝 report/identity drift、未生效/已撤销 approval、空 coverage、未知 adjustment。

```python
command = service.resolve(request, created_at=NOW)
assert command.approval_id == approval.approval_id
assert command.identity == timeline.identity.to_dict()
assert command.sessions == (date(2026, 8, 10), date(2026, 8, 11))
assert command.command_digest.startswith("sha256:")
```

- [x] **Step 2: 运行红灯**：`uv run pytest tests/api/test_formal_data_worker.py -q`；期望 import `astraquant_api.formal_data_service` 失败。
- [x] **Step 3: 最小实现**：Pydantic schema `extra="forbid"`；`FormalCaptureAdmissionService.resolve()` 只接收 server-owned resolver 结果并构造 immutable command；command canonical digest 覆盖 exact identity/report/approval、sessions、rows-per-session、coverage/policy digest、created_at。
- [x] **Step 4: 运行绿灯与静态检查**：`uv run pytest tests/api/test_formal_data_worker.py -q`、Ruff、mypy 全绿。
- [x] **Step 5: 提交**：`git commit -m "feat(api): 冻结正式采集命令"`（`725cd9c`）。

### Task 2: 增加逐页 bridge 调用与可取消 CaptureSession

**Files:**
- Modify: `packages/data/src/astraquant_data/eastmoney_client.py`
- Modify: `packages/data/src/astraquant_data/adapters/eastmoney_batch.py`
- Modify: `packages/data/src/astraquant_data/capture_store.py`
- Test: `tests/data/test_eastmoney_client.py`
- Modify: `tests/data/test_eastmoney_batch.py`

- [x] **Step 1: 写逐页/取消红灯**：`history_page_with_evidence()` 每次只发一个 exact page；adapter 在每页前后调用 `should_cancel()`。第二页前取消时第一 chunk 保留、`seal.json` 不存在、读取 parent 返回 `IncompleteCaptureError`；恢复用同 plan/capture id 跳过已验证同正文 chunk并继续。

```python
with pytest.raises(CaptureCanceled):
    adapter.capture(request, plan=plan, recorded_at=NOW, should_cancel=cancel_after_first)
assert store.list_chunk_ids(plan.capture_id) == (first_chunk_id,)
with pytest.raises(IncompleteCaptureError):
    store.read(plan.capture_id)
```

- [x] **Step 2: 运行红灯**：运行上述两个 data test 文件，期望缺少逐页 API/cancel contract。
- [x] **Step 3: 最小实现**：`history_range_with_evidence()` 复用逐页 API；adapter 不直接访问 bridge 私有方法；已存在 chunk 必须重算并与新调用证据一致，任何不同正文冲突；取消永不创建 seal。
- [x] **Step 4: 回归**：`uv run pytest tests/data/test_eastmoney_client.py tests/data/test_capture_store.py tests/data/test_eastmoney_batch.py -q` 及 Ruff/mypy 全绿。
- [x] **Step 5: 提交**：`git commit -m "feat(data): 支持可恢复逐页正式采集"`（`be8ac41`）。

### Task 3: 实现无数据库能力的 worker

**Files:**
- Create: `packages/api/src/astraquant_api/formal_data_worker.py`
- Modify: `packages/api/src/astraquant_api/worker.py`
- Modify: `tests/api/test_formal_data_worker.py`

- [x] **Step 1: 写 worker 红灯**：用 fake bridge factory 执行 resolved command；成功 payload 只含 `command_digest/capture_id/seal_digest/chunk_count/row_count`，不含 token、raw bytes、object path；取消为 `CANCELED` 且 parent 未 seal；source test 禁止 `sqlalchemy`、`QualificationRepository`、legacy `data_worker`、AKShare、CSV。
- [x] **Step 2: 运行红灯**：`uv run pytest tests/api/test_formal_data_worker.py -q`，期望缺 worker/result type。
- [x] **Step 3: 最小实现**：增加 `FormalCaptureResult`；worker 从 JSON 重建 command/identity/request/plan，token 只传给 `EastmoneyBridgeClient.configure()`，异常只回传稳定 `error_type`，finally 停止 bridge。
- [x] **Step 4: 运行绿灯**：worker tests、Ruff、mypy 全绿。
- [x] **Step 5: 提交**：`git commit -m "feat(api): 增加正式采集子进程"`（`4410ff2`）。

### Task 4: Authenticated route 与幂等任务编排

**Files:**
- Create: `packages/api/src/astraquant_api/formal_data_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Create: `tests/api/test_formal_data_routes.py`

- [x] **Step 1: 写 route 红灯**：无/错 bearer 401；无 `Idempotency-Key` 400；同 key 返回同 task；route 在启动 worker 前已解析 immutable command；无 trusted coverage resolver/secret/SDK runtime 时 503；请求 schema 无 provider 字段，因此 fixture/AKShare/CSV 不可选；响应不含 token/raw/path。
- [x] **Step 2: 运行红灯**：`uv run pytest tests/api/test_formal_data_routes.py -q`，期望 route 404。
- [x] **Step 3: 最小实现**：`AppState` 增 optional formal capture dependencies；router 仅调用 admission service 和 supervisor；task type 固定 `data.formal_capture`；worker args 只用 resolved command JSON、formal root、SDK Python、bridge script 和内存 token。
- [x] **Step 4: API 回归**：route tests、`tests/api/test_app.py tests/api/test_data_routes.py tests/integration/test_runtime_round_trip.py` 全绿。
- [x] **Step 5: 提交**：`git commit -m "feat(api): 编排正式采集任务"`（`133e87a`）。

### Task 5: Backfill/increment/reconcile CLI 与阶段验收

**Files:**
- Create: `tools/data/formal_capture_cli.py`
- Create: `tools/data/backfill_eastmoney.py`
- Create: `tools/data/increment_eastmoney.py`
- Create: `tools/data/reconcile_eastmoney.py`
- Create: `tests/research/test_formal_capture_cli.py`
- Modify: `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-1a-provider-capture.md`

**Progress:** backfill authenticated client 已按红灯测试实现；increment/reconcile 不得只在客户端携带 capture id 后调用普通 backfill，必须先补 server-side sealed lineage lookup/reconciliation contract，因此尚未勾选本任务。

- [ ] **Step 1: 写 CLI 红灯**：三入口只向 authenticated formal route 发 request；token 仅从 `ASTRAQUANT_SESSION_TOKEN`；backfill 要 exact start/end，increment 要 exact last sealed capture，reconcile 要两个 exact capture ids；不得 import SDK/SQLAlchemy 或直写 capture root。
- [ ] **Step 2: 运行红灯**：`uv run pytest tests/research/test_formal_capture_cli.py -q`，期望 module 缺失。
- [ ] **Step 3: 最小实现**：共享 HTTP client 与安全 JSON 输出；API unavailable/non-2xx nonzero；不打印 token/raw/path。
- [ ] **Step 4: 全验收**：运行 Task 6 roadmap 指定 API/data/integration tests、Ruff format/check、mypy 和 `./scripts/verify.ps1 -Scope All`。
- [ ] **Step 5: 更新清单并提交**：勾选 roadmap Task 6，提交 `feat(api): 编排正式真实接口采集任务`；推送分支并确认远端 SHA/CI。

## Self-review

- Spec coverage：命令冻结、exact approval、可信 coverage、真实 bridge、取消/恢复、无 DB worker、认证/幂等、legacy 隔离、CLI 均有任务。
- Fail-closed gap：Phase 1c 官方 calendar/status resolver 未完成时 production route 明确 503；本计划不使用 weekday 猜测，也不把测试 resolver 注册到正式运行时。
- Type consistency：所有层统一使用 `ResolvedFormalCaptureCommand.command_digest`、`CapturePlan.coverage_proof_digest`、`FormalCaptureResult.capture_id/seal_digest`。

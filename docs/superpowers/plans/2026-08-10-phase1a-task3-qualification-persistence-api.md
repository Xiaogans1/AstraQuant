# Phase 1a Task 3 Qualification Persistence and Approval API 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development task-by-task.

**Goal:** 以 append-only SQLite/Alembic 表持久化 ProviderIdentity、QualificationReport、人工 approval/revocation 与 capture index，并让 authenticated API 成为唯一审批写入者。

**Architecture:** `capture_repository.py` 拥有独立 SQLAlchemy metadata 和 compare-and-append repository；同 digest 重放幂等，同 digest 不同正文冲突。report 全绿只可保存，不能自动 approval。service 从 repository 重建 exact timeline 并调用 Phase 1a Task 1 的 domain transition；routes 只接受认证后的 typed command。qualification CLI 只生成 probe/report artifact，并通过 HTTP API 提交，不直接打开数据库。

**Tech Stack:** Python 3.12、SQLAlchemy Core、Alembic、FastAPI/Pydantic v2、httpx/urllib、pytest、Ruff、mypy。

---

## Task 1: DDL、metadata parity 与 append-only repository

**Files:**

- Create: `packages/api/migrations/versions/0010_provider_qualification_capture.py`
- Create: `packages/api/src/astraquant_api/capture_repository.py`
- Modify: `packages/api/src/astraquant_api/schema_registry.py`
- Create: `tests/api/test_capture_repository.py`
- Modify: `tests/api/test_schema_registry.py`

- [x] 红灯：0009→0010 migration 创建 `provider_identities`、`provider_qualification_reports`、`provider_approvals`、`provider_revocations`、`capture_index`，named FK/unique/check/index 与 registered metadata 完全一致。
- [x] 红灯：append identity/report/approval/revocation 同正文幂等；同主 digest/ID 不同正文抛 `QualificationConflictError`；历史行无 update/delete API。
- [x] 红灯：approval exact 绑定 identity/report；report 不 approvable、identity drift、approval effective 前 capture 均 lookup false。普通 revoke 仅阻断 effective 后；retroactive compromise 阻断全部历史。
- [x] 最小实现五表、JSON canonical serializer、UTC conversion、compare-and-append transaction、timeline loader 与 `is_approved_for_capture()`。
- [x] migration/schema parity、repository tests、Ruff/mypy 全绿，提交 `feat(api): 持久化数据源资格时间线`。

## Task 2: Authenticated approval/revocation API

**Files:**

- Create: `packages/api/src/astraquant_api/provider_qualification_schemas.py`
- Create: `packages/api/src/astraquant_api/provider_qualification_service.py`
- Create: `packages/api/src/astraquant_api/provider_qualification_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Modify: `packages/api/src/astraquant_api/cli.py`
- Create: `tests/api/test_provider_qualification_routes.py`

- [x] 红灯：无/错 bearer token 为 401；report command 只能 append `UNQUALIFIED`；approve command 必须 reviewer/policy/effective/exact report digest；revoke command 必须 kind/reason digest/effective。
- [x] 红灯：重复同 command 幂等返回同 ID；不同正文冲突 409；FAIL/NOT_TESTED report approve 422；identity drift 404/409；所有 command 产生稳定 audit response。
- [x] `AppState` 增 optional qualification repository，CLI 正式启动时注入；router 仅在 repository 可用时注册，复用 app 的 authenticated dependency。
- [x] service 用 immutable timeline 计算 transition 后才 append；route 不暴露 token/raw response，错误映射稳定 code。
- [x] route/app tests、全 API 回归、Ruff/mypy 全绿，提交 `feat(api): 增加数据源资格审批接口`。

## Task 3: Eastmoney qualification probe CLI（无自动批准）

**Files:**

- Create: `tools/data/qualify_eastmoney.py`
- Create: `tools/data/__init__.py`
- Create: `tests/research/test_eastmoney_qualification_cli.py`

- [x] 红灯：CLI 读取 exact probe artifact/identity fields 生成 canonical report JSON，只输出 report digest/status；token/cookie/raw payload 不进入 stdout/Git。
- [x] 红灯：`probe` 子命令只 POST report；`approve/revoke` 子命令只调用 authenticated API，源码不得 import SQLAlchemy/repository 或写 sqlite；API 不可达时 nonzero/fail closed。
- [x] output root 必须显式路径或 Phase 0 `formal_qualification_root`，禁止硬编码 `.astraquant/qualification`；artifact atomic write、must-not-overwrite 不同正文。
- [x] CLI/API 合同测试全绿；提交 `feat(data): 增加Eastmoney资格探测命令`。

## Task 4: 阶段验证与交付

- [x] 运行 migration smoke：临时绝对 sqlite URL 从 worktree 临时目录生成，`uv run alembic ... -x database_url=... upgrade head`。
- [x] 运行 `tests/api/test_capture_repository.py tests/api/test_provider_qualification_routes.py tests/api/test_schema_registry.py tests/research/test_eastmoney_qualification_cli.py` 及 API 全回归。
- [x] 运行 Ruff format/check、mypy、repository policy；完成 Phase 1a roadmap Task 3 的持久化、审批与提交 CLI 部分。真实 probe 矩阵必须等 Task 4 CaptureStore 可复验原始正文后闭合，不能以调用者自报 PASS 代替。
- [ ] 推送 `codex/quant-core-v3-phase1a-task3`，确认远端 SHA、CI success/annotations=0；不创建/合并 PR。

## Acceptance

- report、approval、revocation 100% append-only；全绿 report 仍为 UNQUALIFIED。
- 任何 build/permission/schema/endpoint/capability drift 都不能命中旧 approval。
- ordinary revoke 的历史 lookup 依 capture time 可复现；只有 `RETROACTIVE_COMPROMISE` 追溯隔离。
- CLI 无数据库写路径；API 是唯一审批写者；所有 secret/raw payload 不出现在命令行、日志、审批表或 report stdout。

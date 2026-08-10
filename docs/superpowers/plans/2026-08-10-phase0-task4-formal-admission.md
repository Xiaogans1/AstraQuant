# Phase 0 Task 4 Formal Admission 微型实施计划

> **执行要求：** 使用 test-driven-development，逐项先观察红灯，再写最小实现；每个检查点独立提交。完整路线见 `2026-08-10-quant-core-v3-phase-0-repository-ci-legacy.md` Task 4。

**Goal:** 建立 API 内唯一的 `FormalAdmissionService`，让 sealed `RunManifest` 与递归证据图成为正式运行的唯一入口，并保证 Phase 0 没有任何 legacy model 能生成正式新订单。

**Architecture:** Service 只接受 typed `RunManifest`、typed `EvidenceRef` roots 与精确 root-id→digest 映射；它调用共享 `EvidenceGate`，不接受 dict、目录、path、instrument、dataset alias 或 `latest`。旧 research API 明确固定为 `EXPLORATORY/LEGACY_*`。正式模型 selector 在 Phase 5 前恒为 typed `HOLD/no-new-orders`，不读取 legacy `latest_approved_model()`。

**Tech Stack:** Python 3.12、Pydantic、FastAPI、SQLAlchemy、pytest、Ruff、mypy。

---

## Task 1: Typed FormalAdmissionService

**Files:**

- Create: `tests/api/test_formal_admission.py`
- Create: `packages/api/src/astraquant_api/formal_admission.py`

- [ ] **Step 1: 写 sealed manifest + exact evidence 成功红灯**

构造已批准 `REAL_API_MARKET` root 和 `RunClass.FORMAL` sealed manifest；断言返回 `manifest_digest`、精确 root IDs、root digests，且返回值不可变。

- [ ] **Step 2: 写 fail-closed 矩阵红灯**

覆盖 draft manifest、EXPLORATORY manifest、普通 dict、`latest`/缺 ID root、legacy root、未批准 authority、manifest input mapping 与 root 集合/摘要不一致。任何失败都不能返回部分 admission。

- [ ] **Step 3: 写 Phase 0 model HOLD 红灯**

即使传入 status=APPROVED、AUC=0.99、net>0 的 legacy model metadata，`select_formal_model()` 也返回 `HOLD`、`allow_new_orders=False`、`model_id=None`，且不调用 legacy repository selector。

- [ ] **Step 4: 实现唯一 service**

实现 `FormalRunAdmission`、`FormalModelSelection`、`FormalModelDecision`、`FormalAdmissionService.admit_run()` 与 `select_formal_model()`。`admit_run()` 顺序固定为 typed check → SEALED/FORMAL check → exact root mapping equality → `EvidenceGate.admit()`；错误统一为 `FormalAdmissionError` 或 shared manifest error，不接受 path-like 参数。

- [ ] **Step 5: 验证并提交**

Run: `uv run pytest tests/api/test_formal_admission.py -q`

Run: `uv run ruff check packages/api/src/astraquant_api/formal_admission.py tests/api/test_formal_admission.py`

Run: `uv run mypy packages/api/src/astraquant_api/formal_admission.py tests/api/test_formal_admission.py`

Commit: `git commit -m "feat(api): 建立唯一正式运行准入服务"`

## Task 2: Legacy research API classification boundary

**Files:**

- Modify: `packages/api/src/astraquant_api/research_schemas.py`
- Modify: `packages/api/src/astraquant_api/research_routes.py`
- Modify: `tests/api/test_research_routes.py`

- [ ] **Step 1: 写旧 API 固定 exploratory 红灯**

对 record/train/replay 请求显式传 `run_class=FORMAL`、`snapshot_id=latest`、`dataset_path` 等正式字段时必须 422/409；不传时保持旧功能，但响应与持久化记录固定 `LEGACY_SEMANTICS`、`LEGACY_UNVERIFIED`、`EXPLORATORY`。

- [ ] **Step 2: 实现 additive legacy contract**

旧 request schema 只允许 `run_class: Literal["EXPLORATORY"] = "EXPLORATORY"`，`extra="forbid"`，不新增 formal 参数。旧 response 增加 legacy classification；`_save_experiment()` 显式传 legacy fields，不依赖数据库默认值。

- [ ] **Step 3: 回归旧 UI/API 并提交**

Run: `uv run pytest tests/api/test_research_routes.py tests/api/test_model_registry.py -q`

Commit: `git commit -m "fix(api): 固定旧研究入口为探索语义"`

## Task 3: Isolate legacy model selectors and CLI force

**Files:**

- Modify: `packages/api/src/astraquant_api/paper_repository.py`
- Modify: `packages/api/src/astraquant_api/paper_strategy_service.py`
- Modify: `tools/research/publish_model.py`
- Modify: `tests/api/test_paper_strategy_service.py`
- Create: `tests/tools/test_publish_model.py`

- [ ] **Step 1: 写 selector isolation 红灯**

将 repository 方法重命名/包裹为 `latest_approved_legacy_model()`；策略服务的旧 Demo 路径必须显式调用 legacy selector。FormalAdmissionService 测试用 repository spy 证明永不调用该方法。

- [ ] **Step 2: 写 publish CLI classification 红灯**

`register_approved_model()` 无论指标或 `force=True` 都只写 `LEGACY_SEMANTICS/LEGACY_UNVERIFIED/EXPLORATORY`；任何 `run_class=FORMAL` 参数拒绝。`force` 只允许覆盖同一 legacy model，不改变 classification。

- [ ] **Step 3: 实现与回归**

Run: `uv run pytest tests/api/test_paper_strategy_service.py tests/tools/test_publish_model.py -q`

Run: `uv run ruff check packages/api/src/astraquant_api tools/research tests/api tests/tools`

Run: `uv run mypy packages/api/src/astraquant_api tools/research tests/api tests/tools`

Commit: `git commit -m "feat(api): 阻断旧模型进入正式运行"`

## Task 4: Verification and GitHub delivery

- [ ] **Step 1: 精确 Task 4 门禁**

Run: `uv run pytest tests/api/test_formal_admission.py tests/api/test_research_routes.py tests/api/test_model_registry.py tests/api/test_paper_strategy_service.py tests/tools/test_publish_model.py -q`

- [ ] **Step 2: 完整共享门**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Scope All`

- [ ] **Step 3: 范围核查、roadmap 勾选、提交并推送**

只允许 Task 4 service/schema/routes/legacy selector/tool/tests/docs；推送 `codex/quant-core-v3-phase0-task4`，不创建或合并 PR。

- [ ] **Step 4: 最终远端验收**

最终 HEAD 的 GitHub Actions 必须 `success`，verification logs artifact 存在，annotations=0，本地/远端 SHA 一致。

## Self-review

- Phase boundary: 不创建未来 `model_version_id`、release state 或 Phase 5 表。
- Single gate: 只有 `FormalAdmissionService` 组合 RunManifest/EvidenceGate；routes/CLI 不复制正式准入规则。
- Fail closed: typed sealed exact inputs 之外全部拒绝；legacy APPROVED 不是 formal approval。
- Compatibility: 旧研究/Paper Demo 保持可读可运行，但所有输出和 selector 名称明确 legacy/exploratory。

# Phase 0 Task 5 Formal Roots 与 API 单写者实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 legacy 数据与 formal 证据目录物理隔离，并让子进程 Worker 只产出不可变文件和 typed result，由 API 进程校验后原子写入 catalog/task。

**Architecture:** `RuntimeConfig` 是所有运行目录的唯一来源，formal roots 固定为 `state_dir/formal/{qualification,capture,publication,verification}`，legacy 数据固定为 `state_dir/data`。`run_data_import_worker` 不持有数据库信息，只发布 legacy v1 snapshot 文件并返回 frozen `DataImportResult`；`TaskRepository` 在 API 进程重新验证路径、manifest/file SHA-256 与分类，再用一个数据库事务同时写 catalog 和 task terminal state。`TaskSupervisor` 只编排消息，不复制验证规则。

**Tech Stack:** Python 3.12、pathlib、SQLAlchemy、Alembic、multiprocessing、pytest、Ruff、mypy。

---

## Task 1: Runtime roots 与路径逃逸防护

**Files:**

- Modify: `packages/api/src/astraquant_api/config.py`
- Modify: `tests/api/test_config.py`

- [x] **Step 1: 写 root layout 红灯**

断言 `legacy_data_root == state_dir/data`，formal roots 精确位于 `state_dir/formal/{qualification,capture,publication,verification}`，全部 resolved、两两不重叠；`.astraquant/qualification` 不创建。

- [x] **Step 2: 写 symlink/junction escape 红灯**

在支持符号链接的平台将 `formal/capture` 指向 state_dir 外部，`RuntimeConfig.from_environment()` 必须抛 `ValueError("escapes state directory")`；Windows 无符号链接权限时用 monkeypatch 的 `Path.resolve` 等价覆盖 canonical escape 判断。

- [x] **Step 3: 实现最小 root contract**

新增 `legacy_data_root`、`formal_root`、`formal_qualification_root`、`formal_capture_root`、`formal_publication_root`、`formal_verification_root`；`prepare_directories()` 先创建父目录，再逐项 resolve/relative-to 检查、拒绝相等或祖先/后代重叠，最后创建合法 roots。数据库与日志目录沿用现有路径。

- [x] **Step 4: 验证并提交**

Run: `uv run pytest tests/api/test_config.py -q`

Run: `uv run ruff check packages/api/src/astraquant_api/config.py tests/api/test_config.py`

Run: `uv run mypy packages/api/src/astraquant_api/config.py tests/api/test_config.py`

Commit: `git commit -m "feat(runtime): 隔离正式证据目录"`

## Task 2: Worker typed result 与真实 observed receive time

**Files:**

- Modify: `packages/api/src/astraquant_api/worker.py`
- Modify: `packages/api/src/astraquant_api/data_worker.py`
- Modify: `packages/api/src/astraquant_api/data_routes.py`
- Modify: `tests/api/test_data_worker.py`
- Modify: `tests/api/test_worker.py`
- Modify: `tests/repository/test_runtime_test_isolation.py`

- [ ] **Step 1: 写 Worker 无数据库能力红灯**

静态和运行时测试断言 `data_worker.py` 不 import `database`、`DataCatalogRepository`、SQLAlchemy，不接收 database URL/state dir，只接收精确 legacy data root；Worker 完成后 SQLite 仍无 catalog 行。

- [ ] **Step 2: 写 typed result 与时间红灯**

成功消息 payload 必须是 frozen `DataImportResult`，含 manifest path/digest、snapshot/dataset identity、classification、`observed_received_time`。注入固定 Clock，断言 manifest `source_fetched_at == observed_received_time`，且不等于 `max(available_time)+1 minute`。

- [ ] **Step 3: 实现 typed result**

在 `worker.py` 新增 frozen `DataImportResult`；`data_worker.py` 在 provider fetch 返回时读取 injected/default `SystemClock.now()`，发布到传入 legacy root，计算 manifest file SHA-256 后发送 result。删除所有 DB/catalog 调用；classification 固定 `LEGACY_SEMANTICS/LEGACY_UNVERIFIED/EXPLORATORY`。

- [ ] **Step 4: 调整 cancellation 语义**

取消发生在文件发布前则无 manifest；文件发布后取消允许留下未 catalog 的 immutable orphan，但不得产生 catalog row。后续 cleanup/reconcile 不把 orphan 自动追认为正式数据。

- [ ] **Step 5: 验证并提交**

Run: `uv run pytest tests/api/test_data_worker.py tests/api/test_worker.py tests/repository/test_runtime_test_isolation.py -q`

Commit: `git commit -m "refactor(worker): 仅返回类型化数据产物"`

## Task 3: API 原子校验与 catalog/task 单事务写入

**Files:**

- Modify: `packages/api/src/astraquant_api/data_repository.py`
- Modify: `packages/api/src/astraquant_api/repository.py`
- Modify: `packages/api/src/astraquant_api/supervisor.py`
- Modify: `packages/api/src/astraquant_api/cli.py`
- Modify: `tests/api/test_data_repository.py`
- Modify: `tests/api/test_supervisor.py`
- Modify: `tests/api/test_data_worker.py`

- [ ] **Step 1: 写成功 ingestion 红灯**

创建 RUNNING `data.import` task 和真实 Worker result；调用 API-side ingestion 后断言同一次完成产生 `PUBLISHED` legacy snapshot、SUCCEEDED task 与 terminal event，result JSON 只含可序列化 identity/classification。

- [ ] **Step 2: 写篡改/逃逸/原子回滚红灯**

逐一篡改 manifest digest、Parquet file、snapshot ID、classification、manifest path 越出 configured legacy root；全部抛 `WorkerResultValidationError`，catalog 无新增，task 保持 RUNNING。再注入 task revision 冲突，断言 catalog insert 回滚。

- [ ] **Step 3: 提取 connection-scoped catalog writer**

`DataCatalogRepository` 提供不自行开启事务的 `stage_and_publish_on(connection, snapshot, ...)`，复用现有 insert/quality 逻辑；公开 `stage_snapshot/mark_published` 行为保持兼容。

- [ ] **Step 4: 实现 TaskRepository ingestion**

`TaskRepository` 构造时接收 canonical `legacy_data_root`；`complete_worker_result()` 重新 resolve path、读取并 canonical 验证 manifest、重算 manifest/file SHA-256、校验 typed fields/classification/timezone，然后在一个 `engine.begin()` 内写 catalog 和 task/event。任何异常先回滚再抛。

- [ ] **Step 5: 接入 Supervisor/CLI**

`TaskSupervisor` 对 SUCCEEDED typed result 调用唯一 repository ingestion；generic Demo dict 仍走现有 update。CLI 用 `TaskRepository(engine, legacy_data_root=config.legacy_data_root)`；data route 只把 `config/state legacy_data_root` 作为 Worker 参数，不暴露 database URL。

- [ ] **Step 6: 验证并提交**

Run: `uv run pytest tests/api/test_data_repository.py tests/api/test_data_worker.py tests/api/test_supervisor.py tests/api/test_data_routes.py -q`

Commit: `git commit -m "refactor(runtime): 恢复API数据库单写者"`

## Task 4: 全量验收与 GitHub 交付

- [ ] **Step 1: 精确 Task 5 门禁**

Run: `uv run pytest tests/api/test_config.py tests/api/test_data_worker.py tests/api/test_worker.py tests/api/test_data_repository.py tests/api/test_supervisor.py tests/api/test_data_routes.py tests/repository/test_runtime_test_isolation.py -q`

- [ ] **Step 2: 静态与完整共享门**

Run: `uv run ruff check packages/api/src tests/api tests/repository`

Run: `uv run ruff format --check packages/api/src tests/api tests/repository`

Run: `uv run mypy packages/api/src tests/api tests/repository`

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Scope All`

- [ ] **Step 3: 更新 roadmap、提交并推送**

只允许 Task 5 roots/worker/ingestion/tests/docs；推送 `codex/quant-core-v3-phase0-task5`，不创建或合并 PR。

- [ ] **Step 4: 最终 GitHub Actions**

最终 HEAD 必须 `success`、verification artifact 存在、annotations=0、本地/远端 SHA 一致。

## Self-review

- No placeholders: 所有路径、API、错误与测试目标已命名。
- Scope: 不实现 Phase 1 qualification/capture/publication 内容，只预留并保护物理 roots。
- Safety: 不移动、不删除 legacy 文件；orphan 不自动追认；路径逃逸 fail closed。
- Single writer: Worker 无数据库能力；只有 API repository transaction 写 SQLite。
- Atomicity: catalog 与 task success 同事务；校验和 revision 失败均无部分 catalog 状态。

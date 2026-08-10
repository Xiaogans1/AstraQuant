# Quant Core v3 Phase 0 Repository, CI, and Legacy Quarantine Stage Roadmap

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 恢复可信的仓库验证基线，并确保现有 v1 snapshot、旧训练/回放、标量 Paper 账本和样例数据只能作为只读 legacy，绝不进入 v3 formal run。

**Architecture:** 先恢复本地与 CI 同源的验证脚本，再建立不可由调用方篡改的 Evidence/Run 分类和唯一 `FormalAdmissionService`。旧目录保持可读，新正式目录物理隔离；Worker 只产出文件/消息，SQLite 始终由 API 单写者提交。

**Tech Stack:** GitHub Actions、PowerShell、uv、pytest、Ruff、mypy、pnpm/Vitest/TypeScript、Cargo、Alembic/SQLite、Python 3.12。

---

## Task 1: 恢复可重复的仓库与 CI 门

**Files:**

- Create: `.github/workflows/ci.yml`
- Create: `scripts/verify.ps1`
- Create: `tests/repository/test_ci_workflow.py`
- Modify: `tests/repository/test_repository_policy.py`
- Modify: `tools/repository_policy.py`

- [ ] 先扩展 repository tests，要求 CI 只调用 `scripts/verify.ps1`，脚本固定 Python/frontend/Rust 命令，并为 pytest 传入仓库内唯一 `--basetemp .astraquant/test-tmp/{run_id}`；CI 不能另写一套漂移命令。
- [ ] 运行 `uv run pytest tests/repository/test_ci_workflow.py tests/repository/test_repository_policy.py -q`，确认因 workflow/script 缺失而失败。
- [ ] 实现 `scripts/verify.ps1 -Scope Python|Desktop|Rust|All`，每次 run 生成 UUID 临时目录并把该目录显式传给 `uv run pytest -q --basetemp .astraquant/test-tmp/{run_id}`；每条外部命令后检查 `$LASTEXITCODE`，随后运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy`、desktop test/check/build、`cargo fmt --check`/clippy/test。
- [ ] 恢复 GitHub Actions 的 Windows job，使用锁定 Node/pnpm/Rust/Python/uv 安装步骤并调用同一脚本；artifact 只上传 test logs，不上传 `.astraquant/` 数据或凭据。
- [ ] 扩展 repository policy，禁止 raw capture、行情、模型、SQLite/WAL、资格报告正文和 secrets 进入 Git，只允许 canonical TEST_ONLY fixture、schema、脱敏摘要与 digest。
- [ ] 运行 `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Scope All`，期望所有 job 退出码为 0。
- [ ] 提交：`git commit -m "ci: 恢复量化核心统一验证门"`

## Task 2: 建立 EvidenceClass/RunClass 递归门

**Files:**

- Create: `packages/data/src/astraquant_data/evidence.py`
- Create: `packages/domain/src/astraquant_domain/run_manifest.py`
- Modify: `packages/data/src/astraquant_data/manifests.py`
- Modify: `packages/domain/src/astraquant_domain/features.py`
- Test: `tests/data/test_evidence_gate.py`
- Create: `tests/domain/test_run_manifest.py`

- [ ] 先测试 manifest v1、fixture 改名、CSV、AKShare、未知祖先、混源与未 pin snapshot 对 `RunClass.FORMAL` 全部拒绝；所有祖先已批准且 exact pin 才通过。
- [ ] 先测试 `RunManifest` 在 SEALED 前不能启动 run；它固定 code/env/input/config/randomness/event-order/matcher/vintage/policy hashes 与 run class，canonical bytes/digest 可精确重现，seal 后任何字段不可改。

```python
def test_renaming_fixture_does_not_upgrade_evidence() -> None:
    disguised = EvidenceRef.fixture(path="renamed-real-api.parquet")
    with pytest.raises(FormalAdmissionError, match="TEST_ONLY"):
        EvidenceGate().admit(RunClass.FORMAL, roots=(disguised,))


def test_derived_real_api_requires_closed_ancestry() -> None:
    raw = EvidenceRef.real_api(approval_id="qa-1", digest="sha256:raw")
    feature = EvidenceRef.derived(digest="sha256:feature", parents=(raw,))
    EvidenceGate().admit(RunClass.FORMAL, roots=(feature,))
```

- [ ] 运行 `uv run pytest tests/data/test_evidence_gate.py -q`，确认缺模块红灯。
- [ ] 实现 shared immutable `RunManifest`/canonical serializer/seal validator，以及 typed `REAL_API_MARKET/REFERENCE/BROKER`、`OFFICIAL_RULE`、`DERIVED_REAL_API`、`TEST_ONLY/EXPLORATORY`、`LEGACY_UNVERIFIED` evidence enum/value objects、cycle detection、role-aware allowed ancestry 和 fail-closed default；名称、provider 字符串、复制路径、重算 hash 都不能升级分类。
- [ ] v1/缺 raw parent/unknown schema 固定映射 `LEGACY_UNVERIFIED`，保持读取兼容但 formal admission 永远失败。
- [ ] 运行 `uv run pytest tests/domain/test_run_manifest.py tests/data/test_evidence_gate.py tests/data/test_feature_snapshots.py -q`，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 建立正式证据递归准入门"`

## Task 3: 用 0009 迁移封存旧 snapshot/model/replay/Paper

**Files:**

- Create: `packages/api/migrations/versions/0009_v3_legacy_evidence.py`
- Create: `packages/api/src/astraquant_api/schema_registry.py`
- Modify: `packages/api/src/astraquant_api/database.py`
- Modify: `packages/api/src/astraquant_api/repository.py`
- Modify: `packages/api/src/astraquant_api/data_repository.py`
- Modify: `packages/api/src/astraquant_api/paper_repository.py`
- Create: `tests/api/test_schema_registry.py`
- Test: `tests/api/test_migration_config.py`
- Test: `tests/api/test_data_repository.py`
- Test: `tests/api/test_model_registry.py`
- Test: `tests/api/test_paper_repository.py`

- [ ] 先写 schema registry parity test，把 repository/data/paper 的全部 table metadata 注册给 Alembic，比较 migration head 的 table/column/index/constraint；缺任一 metadata 都失败，不能依赖不完整 autogenerate。
- [ ] 先写从真实 0008 schema 原地升级测试：现存 snapshots 回填 `LEGACY_UNVERIFIED`；model/replay/experiments/Paper ledger 回填 `LEGACY_SEMANTICS`；迁移不根据文件名、AUC 或当前可访问性追认来源。
- [ ] 运行定向 tests，确认 0009 缺失红灯。
- [ ] 建立统一 schema registry 并让 Alembic/tests 显式加载全部 metadata；在 migration 添加 `semantic_class/evidence_class/run_class/manifest_schema/content_digest`、legacy ledger seal 与 one-time opening import lineage；`down_revision = "0008_experiments"`。
- [ ] repository 显式读写新字段；旧账只能 seal/read，不允许继续用 delete-and-rewrite 更新为 v3 状态。
- [ ] 运行：

```powershell
$phase0RunId = [guid]::NewGuid().ToString('n')
$phase0MigrationDir = Join-Path (Get-Location).Path ".astraquant/test-tmp/phase0-$phase0RunId"
New-Item -ItemType Directory -Force -Path $phase0MigrationDir | Out-Null
$phase0MigrationDb = (Join-Path $phase0MigrationDir 'migration.sqlite3').Replace('\', '/')
uv run alembic -c packages/api/alembic.ini -x "database_url=sqlite:///$phase0MigrationDb" upgrade head
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run pytest tests/api/test_schema_registry.py tests/api/test_migration_config.py tests/api/test_data_repository.py tests/api/test_model_registry.py tests/api/test_paper_repository.py -q --basetemp (Join-Path $phase0MigrationDir 'pytest')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

- [ ] 提交：`git commit -m "feat(api): 封存旧量化证据与账本"`

## Task 4: 建立唯一 FormalAdmissionService

**Files:**

- Create: `packages/api/src/astraquant_api/formal_admission.py`
- Modify: `packages/api/src/astraquant_api/research_schemas.py`
- Modify: `packages/api/src/astraquant_api/research_routes.py`
- Modify: `packages/api/src/astraquant_api/paper_strategy_service.py`
- Modify: `tools/research/publish_model.py`
- Test: `tests/api/test_formal_admission.py`
- Test: `tests/api/test_research_routes.py`
- Test: `tests/api/test_paper_strategy_service.py`

- [ ] 先测试旧 `/v1/research/*` 固定创建 LEGACY/EXPLORATORY；FORMAL 拒绝 `instrument` 直拉、`latest`、任意 dataset path、未 pin model/snapshot 和 `--force` 晋级；即使 legacy `models` 中已有 `APPROVED` 行，Phase 0 的 formal model selection 仍必须返回 `HOLD/no-new-orders`。
- [ ] 先测试运行开始时 admission 只接受 Phase 0 shared contract 产生的 SEALED `RunManifest` 并返回 sealed IDs/digest；未 seal、自造 dict/schema 或后续目录增加更新文件都不能改变该 run 的 inputs。
- [ ] 运行目标 tests，确认 service 缺失红灯。
- [ ] 实现唯一 admission service；API、worker、CLI 不得复制 gate。旧 AUC>0.55/net>0 仅作为 legacy 展示字段，不能变成 v3 release 状态。
- [ ] 隔离 `latest_approved_model()`：它只服务 legacy 展示/EXPLORATORY，不得成为 FORMAL selector。Phase 0 尚无 v3 `model_version`/release gate（留到 Phase 5 的 `0015_model_release_targets`），因此所有 formal model 请求一律 `HOLD/no-new-orders`；本阶段禁止预建、猜测或引用未来 `model_version_id`。Phase 5 完成后再以新的 exact-ID selector 接入 `FormalAdmissionService`。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(api): 阻断旧模型进入正式运行"`

## Task 5: 物理隔离 formal roots 并保持 API 单写者

**Files:**

- Modify: `packages/api/src/astraquant_api/config.py`
- Modify: `packages/api/src/astraquant_api/data_worker.py`
- Modify: `packages/api/src/astraquant_api/worker.py`
- Modify: `packages/api/src/astraquant_api/repository.py`
- Test: `tests/api/test_config.py`
- Test: `tests/api/test_data_worker.py`
- Test: `tests/api/test_worker.py`
- Test: `tests/repository/test_runtime_test_isolation.py`

- [ ] 先测试 `state_dir/data` 只映射 legacy，formal roots 固定在 `state_dir/formal/{qualification,capture,publication,verification}`，其中 `RuntimeConfig.formal_qualification_root` 是资格报告正文与审批证据的唯一正式根；`.astraquant/qualification` 和 legacy data root 均不得承载 formal qualification。所有 resolved paths 不重叠且拒绝 symlink/junction escape。
- [ ] 先测试 Worker 不能持有数据库 URL/connection 或直接写 SQLite；它只返回 typed result message，API process 在一个事务内验证 digest 后写 catalog/task state。
- [ ] 先测试旧 `data_worker.py` 不能用 `max(available_time)+1 minute` 伪造 fetched time；其输出明确 legacy，时间字段只保存实际 observed received time。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 `formal_qualification_root`、`formal_capture_root`、`formal_publication_root`、`formal_verification_root` typed roots、boundary checks 和 single-writer result ingestion；不搬迁、不删除用户旧文件。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "refactor(runtime): 隔离正式目录并恢复API单写者"`

## Task 6: 同步 Python package discovery 与 legacy UI 标识

**Files:**

- Modify: `apps/desktop/src-tauri/src/runtime.rs`
- Modify: `tests/integration/test_runtime_round_trip.py`
- Modify: `start.ps1`
- Modify: `tests/repository/test_dev_launcher.py`
- Modify: `packages/api/src/astraquant_api/paper_schemas.py`
- Modify: `apps/desktop/src/api/paper-contracts.ts`
- Modify: `apps/desktop/src/pages/PaperPage.tsx`
- Modify: `apps/desktop/src/pages/PaperPage.test.tsx`

- [ ] 先测试 Windows managed runtime、integration subprocess 与 launcher 从 repository/worktree 动态发现 workspace packages；禁止硬编码某个旧 worktree 名称。
- [ ] 先测试旧 Paper/研究结果通过 OpenAPI/TypeScript 一致的 `evidence_class`/`semantic_class=LEGACY_*` 字段展示；若 UI adapter 使用 camelCase，必须有显式 alias contract test。UI 与 formal 结果分区并显示只读，不允许按钮直接“升级”。
- [ ] 运行 Python/Rust/frontend 定向 tests，确认红灯。
- [ ] 更新 package path builder，为后续 `packages/execution` 与 `packages/research` 使用同一 discovery 规则；不在 Rust 放量化逻辑，不因加法式 API 无故升级 handshake。
- [ ] 实现 UI legacy badge 与只读说明。
- [ ] 运行：

```powershell
uv run pytest tests/integration/test_runtime_round_trip.py tests/repository/test_dev_launcher.py -q
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
```

- [ ] 提交：`git commit -m "feat(ui): 明确展示旧量化结果隔离状态"`

## Task 7: Phase 0 sign-off

**Files:**

- Create: `tools/verification/verify_phase_0.py`
- Create: `docs/verification/quant-core-v3/phase-0-signoff.md`
- Modify: `docs/research/quant-core-learning-guide.md`

- [ ] verification CLI 注入 renamed fixture、unknown/mixed ancestor、legacy model、unsealed run 和 direct latest，逐项输出 PASS/FAIL 与 run manifest digest。
- [ ] 更新 learning guide，明确当前 LightGBM/回放成绩属于 demo/legacy，禁止作为 v3 alpha 或发布证据引用。
- [ ] 在 verifier/code 已提交且工作树干净后，创建 must-not-exist 的 UUID 输出目录并运行 `uv run python tools/verification/verify_phase_0.py --output artifacts/verification/phase-0/{run_id}/verification.json`；verifier 必须重新运行 admission/physical separation/repository-policy checks，而不是只汇总既有日志。
- [ ] 从最新 `origin/main` 的短生命周期实现分支运行 `scripts/verify.ps1 -Scope All`，并检查 `git diff origin/main...HEAD` 不含无关删除、README 回退、运行数据或用户文件。
- [ ] 核对退出门：旧/样例/AKShare/混源/未 pin 进入 formal=0；legacy `APPROVED` model 触发 formal order=0 且统一 HOLD；formal qualification 正文落入 legacy/旧 `.astraquant/qualification`=0；legacy UI 仍可读；旧 Paper 已 seal；API 单写者测试全绿；CI 与本地命令一致。
- [ ] sign-off 以独立 docs-only commit 引用机器 artifact digest 与被验证的实现 commit；任一检查失败则 Phase 0 保持未通过。
- [ ] 提交：`git commit -m "test(governance): 完成量化核心旧证据隔离验收"`

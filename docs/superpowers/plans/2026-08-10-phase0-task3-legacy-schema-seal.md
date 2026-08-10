# Phase 0 Task 3 Legacy Schema Seal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Alembic `0009` 原地封存所有 v2 snapshot/model/research/replay/Paper 证据，建立统一 schema registry，并保证升级前旧 Paper 账本只读、迁移后新 Demo 数据仍明确属于 legacy。

**Architecture:** repository/data tables 继续共享 core metadata，Paper tables 保持独立 metadata；`schema_registry.py` 显式加载两个 source metadata 并复制到 Alembic target metadata，避免依赖 import 顺序。`0009` 只追加分类字段、legacy ledger seal 和 one-time opening import lineage，不删除、不搬迁、不按 provider 名称/AUC/文件路径追认；对升级前账户按规范化表内容生成 SHA-256 seal，repository 在任何覆写或删除前检查 seal。

**Tech Stack:** Python 3.12、SQLAlchemy Core、Alembic、SQLite、canonical JSON/SHA-256、pytest、Ruff、mypy、PowerShell shared verifier。

---

## File map

- Create `packages/api/src/astraquant_api/schema_registry.py`: 汇总 core/data/Paper metadata，导出唯一 Alembic target。
- Modify `packages/api/migrations/env.py`: 只使用 registry metadata。
- Modify `packages/api/src/astraquant_api/database.py`: migration 后校验全部注册表存在。
- Modify `packages/api/src/astraquant_api/repository.py`: 补齐 core metadata 的 migration constraints/indexes。
- Modify `packages/api/src/astraquant_api/data_repository.py`: 补齐 data metadata，并显式读写 legacy 分类字段。
- Modify `packages/api/src/astraquant_api/paper_repository.py`: 补齐 Paper metadata、新分类字段、seal/opening import tables 与只读门。
- Create `packages/api/migrations/versions/0009_v3_legacy_evidence.py`: 原地升级、回填、seal 与 downgrade。
- Create `tests/api/test_schema_registry.py`: migration head 和 registry 的 table/column/index/FK/unique/check parity。
- Modify `tests/api/test_migration_config.py`: 从真实 `0008_experiments` seed 后升级 `head` 的验收。
- Modify `tests/api/test_data_repository.py`: snapshot legacy 字段 round-trip。
- Modify `tests/api/test_model_registry.py`: 高 AUC 旧模型仍为 legacy。
- Modify `tests/api/test_paper_repository.py`: pre-0009 ledger seal/read-only 与 one-time opening import。

## Task 1: Unified schema registry parity

**Files:**

- Create: `tests/api/test_schema_registry.py`
- Create: `packages/api/src/astraquant_api/schema_registry.py`
- Modify: `packages/api/migrations/env.py`
- Modify: `packages/api/src/astraquant_api/database.py`
- Modify: `packages/api/src/astraquant_api/repository.py`
- Modify: `packages/api/src/astraquant_api/data_repository.py`
- Modify: `packages/api/src/astraquant_api/paper_repository.py`

- [x] **Step 1: 写 registry completeness 与 autogenerate parity 红灯**

```python
def test_schema_registry_contains_every_repository_table() -> None:
    expected = set(core_metadata.tables) | set(paper_metadata.tables)
    assert set(schema_metadata.tables) == expected


def test_migration_head_matches_registered_metadata(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, schema_metadata) == []
```

另以 inspector 与 metadata 分别比较每张表的 column、index、foreign key、unique/check constraint 名称集合，避免 SQLite autogenerate 忽略 check constraint 时产生假绿。

- [x] **Step 2: 运行测试并确认 schema registry 缺失红灯**

Run: `uv run pytest tests/api/test_schema_registry.py -q`

Expected: collection FAIL，`ModuleNotFoundError: astraquant_api.schema_registry`。

- [x] **Step 3: 实现 registry 与 Alembic wiring**

```python
from astraquant_api import data_repository as _data_repository
from astraquant_api import paper_repository as _paper_repository
from astraquant_api.repository import metadata as core_metadata

metadata = sa.MetaData()
for source in (core_metadata, _paper_repository.metadata):
    for table in source.sorted_tables:
        table.to_metadata(metadata)
```

`migrations/env.py` 改为 `from astraquant_api.schema_registry import metadata`；`database.migrate_database()` 在 upgrade 后用 inspector 比较 registry table names，缺表立即抛错。

- [x] **Step 4: 补齐当前 0001–0008 metadata parity**

为 repository table declarations 增加迁移已存在的 `ForeignKey(ondelete="CASCADE")`、named indexes、unique/check constraints 与 composite primary keys；不生成新 migration，不改变数据库，只让代码 metadata 精确描述既有 schema。

- [x] **Step 5: 运行 registry tests、Ruff 与 mypy**

Run:

```powershell
uv run pytest tests/api/test_schema_registry.py tests/api/test_migration_config.py -q
uv run ruff check packages/api/src/astraquant_api/schema_registry.py packages/api/src/astraquant_api/database.py packages/api/src/astraquant_api/repository.py packages/api/src/astraquant_api/data_repository.py packages/api/src/astraquant_api/paper_repository.py packages/api/migrations/env.py tests/api/test_schema_registry.py
uv run ruff format --check packages/api/src/astraquant_api packages/api/migrations tests/api
uv run mypy packages/api/src/astraquant_api tests/api/test_schema_registry.py
```

Expected: 全部 exit 0。

- [x] **Step 6: 提交 registry**

```powershell
git add packages/api/src/astraquant_api/schema_registry.py packages/api/migrations/env.py packages/api/src/astraquant_api/database.py packages/api/src/astraquant_api/repository.py packages/api/src/astraquant_api/data_repository.py packages/api/src/astraquant_api/paper_repository.py tests/api/test_schema_registry.py
git commit -m "feat(api): 建立统一数据库schema registry"
```

## Task 2: 0009 in-place legacy classification and ledger seal

**Files:**

- Modify: `tests/api/test_migration_config.py`
- Create: `packages/api/migrations/versions/0009_v3_legacy_evidence.py`
- Modify: `packages/api/src/astraquant_api/data_repository.py`
- Modify: `packages/api/src/astraquant_api/paper_repository.py`

- [x] **Step 1: 写真实 0008→head 原地升级红灯**

```python
def test_0009_backfills_legacy_classes_and_seals_existing_paper(tmp_path: Path) -> None:
    config, engine = _upgrade_to_0008_and_seed(tmp_path)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        snapshot = connection.execute(sa.text("SELECT * FROM data_snapshots")).mappings().one()
        model = connection.execute(sa.text("SELECT * FROM model_registry")).mappings().one()
        experiment = (
            connection.execute(sa.text("SELECT * FROM research_experiments")).mappings().one()
        )
        seal = (
            connection.execute(sa.text("SELECT * FROM paper_legacy_ledger_seals")).mappings().one()
        )
    assert snapshot["evidence_class"] == "LEGACY_UNVERIFIED"
    assert model["semantic_class"] == "LEGACY_SEMANTICS"
    assert model["evidence_class"] == "LEGACY_UNVERIFIED"
    assert experiment["run_class"] == "EXPLORATORY"
    assert seal["ledger_content_digest"].startswith("sha256:")
    assert seal["seal_status"] == "SEALED_LEGACY"
```

Seed 中 model 使用 `provider=eastmoney` 风格 artifact path、AUC=0.99、net_return=9.0，仍必须 legacy；snapshot 名称含 `formal/real-api` 也不能升级。

- [x] **Step 2: 运行升级测试并确认 0009 缺失红灯**

Run: `uv run pytest tests/api/test_migration_config.py::test_0009_backfills_legacy_classes_and_seals_existing_paper -q`

Expected: FAIL，head 仍为 `0008_experiments` 或新 columns/tables 不存在。

- [x] **Step 3: 实现 0009 schema**

为 `data_snapshots`、`model_registry`、`research_experiments`、`paper_strategy_runs` 增加：

```python
sa.Column("semantic_class", sa.String(32), nullable=False, server_default="LEGACY_SEMANTICS")
sa.Column("evidence_class", sa.String(32), nullable=False, server_default="LEGACY_UNVERIFIED")
sa.Column("run_class", sa.String(32), nullable=False, server_default="EXPLORATORY")
sa.Column("manifest_schema", sa.String(64), nullable=False, server_default="1")
sa.Column("content_digest", sa.String(71))
```

为 `paper_accounts` 增加前三个分类字段；创建 `paper_legacy_ledger_seals(account_id PK/FK, source_revision, ledger_content_digest, seal_status, sealed_at)` 与 `paper_opening_imports(import_id PK, source_account_id UNIQUE/FK, source_ledger_seal_digest, target_account_id, reconciliation_digest, status, created_at)`。

- [x] **Step 4: 实现 deterministic legacy ledger sealing**

migration 对每个升级前 account 按固定 table 顺序和主键顺序读取 account/positions/orders/fills/equity/strategy runs/daily open，datetime/date/Decimal/bytes 转为稳定字符串，canonical JSON 后生成 `sha256:<hex>`；digest 不含迁移时间、数据库路径或 row insertion order。任何读取失败使 migration 回滚，不写伪 seal。

- [x] **Step 5: 实现可逆 downgrade**

downgrade 先删除 opening imports/seals，再按 SQLite batch alter 删除新增 columns；不删除 0008 原有业务行。

- [x] **Step 6: 运行 migration 与 parity tests**

Run:

```powershell
uv run pytest tests/api/test_migration_config.py tests/api/test_schema_registry.py -q
$runId = [guid]::NewGuid().ToString("n")
$root = ".astraquant/test-tmp/phase0-task3-$runId"
New-Item -ItemType Directory -Path $root | Out-Null
$db = (Join-Path (Resolve-Path $root) "migration.sqlite3").Replace("\", "/")
uv run alembic -c packages/api/alembic.ini -x "database_url=sqlite:///$db" upgrade head
```

Expected: tests 和 CLI migration 全部 exit 0，Alembic 输出 upgrade 到 `0009_v3_legacy_evidence`。

- [x] **Step 7: 提交 migration**

```powershell
git add packages/api/migrations/versions/0009_v3_legacy_evidence.py packages/api/src/astraquant_api/data_repository.py packages/api/src/astraquant_api/paper_repository.py tests/api/test_migration_config.py tests/api/test_schema_registry.py
git commit -m "feat(api): 迁移旧量化证据与账本封印"
```

## Task 3: Explicit repository lineage and sealed-ledger guard

**Files:**

- Modify: `tests/api/test_data_repository.py`
- Modify: `tests/api/test_model_registry.py`
- Modify: `tests/api/test_paper_repository.py`
- Modify: `packages/api/src/astraquant_api/data_repository.py`
- Modify: `packages/api/src/astraquant_api/paper_repository.py`

- [x] **Step 1: 写 repository round-trip 与 sealed mutation 红灯**

```python
def test_new_v1_snapshot_is_explicitly_legacy(tmp_path: Path) -> None:
    record = _stage_and_get(tmp_path)
    assert record.semantic_class == "LEGACY_SEMANTICS"
    assert record.evidence_class == "LEGACY_UNVERIFIED"
    assert record.run_class == "EXPLORATORY"
    assert record.manifest_schema == "1"
    assert record.content_digest is None


def test_pre_0009_paper_ledger_is_read_only_after_upgrade(tmp_path: Path) -> None:
    repository = _upgraded_seeded_paper_repository(tmp_path)
    with pytest.raises(LegacyLedgerSealedError, match="account-legacy"):
        repository.save_state(repository.load_state("account-legacy"))
    with pytest.raises(LegacyLedgerSealedError, match="account-legacy"):
        repository.delete_account("account-legacy")
```

- [x] **Step 2: 写 opening import exactly-once 红灯**

```python
def test_opening_import_lineage_is_exactly_once_per_legacy_account(tmp_path: Path) -> None:
    repository = _upgraded_seeded_paper_repository(tmp_path)
    repository.record_opening_import(_opening_import())
    with pytest.raises(OpeningImportAlreadyExistsError):
        repository.record_opening_import(_opening_import(import_id="second"))
    assert repository.get_opening_import("account-legacy").source_ledger_seal_digest.startswith(
        "sha256:"
    )
```

- [x] **Step 3: 实现 explicit records/read/write**

`DataSnapshotRecord`、`ModelRegistryRecord`、`ExperimentRecord`、`StrategyRunRecord` 增加分类字段并在所有 insert/update/row mapper 显式处理；旧 API 构造器使用安全 legacy defaults，不添加任何 FORMAL 默认值。

- [x] **Step 4: 实现 seal guard 与 opening import repository**

`get_legacy_ledger_seal(account_id)` 返回 frozen record；`save_state/delete_account` 在 transaction 首行查询 seal，存在即抛 `LegacyLedgerSealedError`。`record_opening_import` 必须引用同一 account 的 seal digest，依赖 database UNIQUE(source_account_id) 保证跨进程 exactly once，冲突转换为 `OpeningImportAlreadyExistsError`。

- [x] **Step 5: 运行 repository tests**

Run:

```powershell
uv run pytest tests/api/test_data_repository.py tests/api/test_model_registry.py tests/api/test_paper_repository.py -q
uv run ruff check packages/api/src/astraquant_api/data_repository.py packages/api/src/astraquant_api/paper_repository.py tests/api/test_data_repository.py tests/api/test_model_registry.py tests/api/test_paper_repository.py
uv run ruff format --check packages/api/src/astraquant_api tests/api
uv run mypy packages/api/src/astraquant_api tests/api
```

Expected: 全部 exit 0；现有 fresh database Paper round-trip tests 继续通过。

- [x] **Step 6: 提交 repository contracts**

```powershell
git add packages/api/src/astraquant_api/data_repository.py packages/api/src/astraquant_api/paper_repository.py tests/api/test_data_repository.py tests/api/test_model_registry.py tests/api/test_paper_repository.py
git commit -m "fix(api): 阻止旧账本覆写为v3状态"
```

## Task 4: Verification and GitHub delivery

**Files:**

- Modify: `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-0-repository-ci-legacy.md`
- Modify: `docs/superpowers/plans/2026-08-10-phase0-task3-legacy-schema-seal.md`

- [x] **Step 1: 运行 Task 3 精确迁移验收**

Run:

```powershell
$runId = [guid]::NewGuid().ToString("n")
$root = ".astraquant/test-tmp/phase0-task3-$runId"
New-Item -ItemType Directory -Path $root | Out-Null
$db = (Join-Path (Resolve-Path $root) "migration.sqlite3").Replace("\", "/")
uv run alembic -c packages/api/alembic.ini -x "database_url=sqlite:///$db" upgrade head
uv run pytest tests/api/test_schema_registry.py tests/api/test_migration_config.py tests/api/test_data_repository.py tests/api/test_model_registry.py tests/api/test_paper_repository.py -q --basetemp (Join-Path $root "pytest")
uv run ruff check packages/api/src packages/api/migrations tests/api
uv run ruff format --check packages/api/src packages/api/migrations tests/api
uv run mypy packages/api/src tests/api
```

Expected: 全部 exit 0。

- [x] **Step 2: 运行完整共享门**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Scope All`

Expected: Python、Desktop、Rust 与 repository policy 全部通过。

- [x] **Step 3: 核查范围、勾选 roadmap、提交并推送**

Run:

```powershell
git diff --check
git diff --name-status codex/quant-core-v3-phase0-task2...HEAD
git status --short
git push -u origin codex/quant-core-v3-phase0-task3
```

Expected: 只包含 Task 3 migration/registry/repository/tests/docs；远端 branch HEAD 与本地一致。

- [ ] **Step 4: 等待最终 HEAD GitHub Actions**

Expected: conclusion=`success`、verification logs artifact 存在、annotations=0；不创建或合并 PR。

## Self-review

- Spec coverage: 覆盖 Phase 0 roadmap Task 3、设计 §6.1 legacy evidence、§6.3 immutable lineage、§14 Run/Evidence identity，以及旧 Paper opening import 必须先对账的边界。
- Data safety: migration 只 add/backfill/create；不删除或移动用户数据，不依据名称、provider、指标或可访问性追认。
- Compatibility: 只有升级前存在且被 seal 的账户只读；迁移后当前 Demo/Paper 可继续使用，但所有 records 显式 legacy。
- Type consistency: DB classification 字段统一使用 `LEGACY_SEMANTICS`、`LEGACY_UNVERIFIED`、`EXPLORATORY`、manifest schema `"1"`；digest 为 nullable `sha256:<64 lowercase hex>`。
- Placeholder scan: 无待定实现、伪代码省略号或未定义 public API；每项 mutation 都有先行红灯与精确命令。

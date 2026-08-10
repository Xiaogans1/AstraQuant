# Phase 0 Task 6 Workspace Discovery 与 Legacy UI 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Windows managed runtime、integration subprocess 与根启动器动态发现当前 worktree 和全部 workspace Python packages，并通过一致的 API/TypeScript 契约把旧 Paper、策略运行和模型明确标记为只读 legacy。

**Architecture:** Rust 与 Python 测试启动器都从 `packages/*/src` 枚举实际存在的 workspace source roots，排序、去重后组装 `PYTHONPATH`，因此后续 `packages/execution`、`packages/research` 无需再修改启动逻辑。根 `start.ps1` 优先使用显式 `ASTRAQUANT_WORKTREE`，否则从 Git worktree registry 动态选择当前 repository 下可用的开发 worktree，绝不硬编码旧目录名。Paper API 在现有 snake_case contract 上透传 repository 已封存的 `semantic_class`、`evidence_class` 与 `run_class`；桌面端只将其用于分区和只读说明，不提供升级动作。

**Tech Stack:** Rust、PowerShell、Python 3.12、FastAPI/Pydantic、React/TypeScript、pytest、Vitest、Cargo。

---

## Task 1: 动态 workspace package discovery

**Files:**

- Modify: `apps/desktop/src-tauri/src/runtime.rs`
- Modify: `tests/integration/test_runtime_round_trip.py`
- Modify: `start.ps1`
- Modify: `tests/repository/test_dev_launcher.py`

- [ ] **Step 1: 写 Rust 红灯**

在 `runtime::tests::windows_runtime_discovers_new_workspace_python_packages` 的临时 project root 下创建 `packages/api/src`、`packages/execution/src`、`packages/research/src` 与一个无 `src` 的目录，断言 `workspace_python_source_paths()` 只返回三个已存在的 `src`，按路径排序且无硬编码 package 名称。

- [ ] **Step 2: 运行 Rust 红灯**

Run: `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml runtime::tests::windows_runtime_discovers_new_workspace_python_packages`

Expected: FAIL，`workspace_python_source_paths` 尚不存在或 `execution/research` 未进入 `PYTHONPATH`。

- [ ] **Step 3: 实现 Rust 最小 discovery**

新增：

```rust
fn workspace_python_source_paths(project_root: &Path) -> Vec<PathBuf> {
    let mut paths = fs::read_dir(project_root.join("packages"))
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .map(|entry| entry.path().join("src"))
        .filter(|path| path.is_dir())
        .collect::<Vec<_>>();
    paths.sort();
    paths.dedup();
    paths
}
```

Windows `runtime_launch_spec()` 的 `PYTHONPATH` 由 venv `site-packages` 加该函数结果构成；保留 `PYTHONNOUSERSITE=1` 与 base interpreter 逻辑。

- [ ] **Step 4: 写 integration discovery 红灯并实现 helper**

在 `tests/integration/test_runtime_round_trip.py` 新增 `_workspace_python_paths(repository_root, virtual_environment)`，用 `tmp_path` 创建未来 package 并断言动态发现。`running_runtime()` 只调用该 helper，不再列举 api/data/domain/paper/quant。

Run: `uv run pytest tests/integration/test_runtime_round_trip.py -q --basetemp .astraquant/test-tmp/task6-runtime-red`

Expected before helper: FAIL；实现后 PASS。

- [ ] **Step 5: 写 launcher 红灯**

更新 `test_root_launcher_finds_the_active_development_worktree`，断言：

```python
assert "phase-1-desktop-platform" not in script
assert "ASTRAQUANT_WORKTREE" in script
assert "git worktree list --porcelain" in script
assert "scripts\\dev.ps1" in script
```

Run: `uv run pytest tests/repository/test_dev_launcher.py -q --basetemp .astraquant/test-tmp/task6-launcher-red`

Expected: FAIL，当前脚本仍硬编码 `phase-1-desktop-platform`。

- [ ] **Step 6: 实现 launcher discovery**

`start.ps1` 依次解析：合法的 `$env:ASTRAQUANT_WORKTREE`；`git -C $PSScriptRoot worktree list --porcelain` 返回且含 `scripts/dev.ps1` 的非 root worktree；最后回退 `$PSScriptRoot`。所有候选使用 `Resolve-Path`，拒绝不存在的 launcher，不执行字符串拼接命令。

- [ ] **Step 7: 验证并提交**

Run: `uv run pytest tests/integration/test_runtime_round_trip.py tests/repository/test_dev_launcher.py -q --basetemp .astraquant/test-tmp/task6-discovery-green`

Run: `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml runtime::tests`

Commit: `git commit -m "refactor(runtime): 动态发现工作区Python包"`

## Task 2: API 与 TypeScript legacy 分类契约

**Files:**

- Modify: `packages/api/src/astraquant_api/paper_schemas.py`
- Modify: `packages/api/src/astraquant_api/paper_routes.py`
- Modify: `tests/api/test_paper_routes.py`
- Modify: `apps/desktop/src/api/paper-contracts.ts`

- [ ] **Step 1: 写 API 红灯**

扩展 Paper route tests，断言 account、strategy run 与 model JSON 均包含：

```python
assert payload["semantic_class"] == "LEGACY_SEMANTICS"
assert payload["evidence_class"] == "LEGACY_UNVERIFIED"
assert payload["run_class"] == "EXPLORATORY"
```

模型字段从 `ModelRegistryRecord` 透传；策略运行字段从 `StrategyRunRecord` 透传；当前 `PaperAccount` 没有 v3 lineage，因此 account view 使用不可被请求覆盖的 Literal legacy defaults。

- [ ] **Step 2: 运行 API 红灯**

Run: `uv run pytest tests/api/test_paper_routes.py -q --basetemp .astraquant/test-tmp/task6-contract-red`

Expected: FAIL，response schema 尚未暴露 classification。

- [ ] **Step 3: 实现 Pydantic contract**

新增共享 literal aliases，并在 `AccountView`、`StrategyRunView`、`ModelRegistryView` 声明 snake_case 字段。`_strategy_view_from_record()` 与 `_model_view()` 显式映射 repository record；账户分类固定为迁移后的 legacy，不接受客户端输入。

- [ ] **Step 4: 同步 TypeScript contract**

新增：

```ts
export type LegacySemanticClass = "LEGACY_SEMANTICS";
export type LegacyEvidenceClass = "LEGACY_UNVERIFIED";
export type LegacyRunClass = "EXPLORATORY";
```

并让 `PaperAccount`、`PaperStrategyRun`、`ModelRegistryView` 使用相同 snake_case 字段；不添加 camelCase adapter。

- [ ] **Step 5: 验证并提交**

Run: `uv run pytest tests/api/test_paper_routes.py tests/api/test_model_registry.py -q --basetemp .astraquant/test-tmp/task6-contract-green`

Run: `pnpm --dir apps/desktop check`

Commit: `git commit -m "feat(api): 暴露旧量化结果证据分类"`

## Task 3: Legacy 只读分区与说明

**Files:**

- Modify: `apps/desktop/src/pages/PaperPage.tsx`
- Modify: `apps/desktop/src/pages/PaperPage.test.tsx`
- Modify: `apps/desktop/src/styles/paper.css`

- [ ] **Step 1: 写 UI 红灯**

在共享 `summary` fixture 加入三个 classification 字段。新增测试断言策略区展示“旧版演示结果”“只读隔离”，并且页面不存在名称为“升级为正式”“批准为正式”或“转为正式”的按钮。

- [ ] **Step 2: 运行 UI 红灯**

Run: `pnpm --dir apps/desktop test -- --run src/pages/PaperPage.test.tsx`

Expected: FAIL，legacy badge/说明尚不存在。

- [ ] **Step 3: 实现最小 UI**

在 `StrategyConsole` 上方按 `account.semantic_class` 渲染独立 legacy notice，文案说明当前 LightGBM、回放与 Paper 账本仅作 demo/历史查看，不能作为 v3 formal 发布证据；不新增升级 mutation。将 account classification 作为 prop 从 workspace 传入，不从展示文案反推状态。

- [ ] **Step 4: 验证并提交**

Run: `pnpm --dir apps/desktop test -- --run src/pages/PaperPage.test.tsx`

Run: `pnpm --dir apps/desktop check`

Run: `pnpm --dir apps/desktop build`

Commit: `git commit -m "feat(ui): 明确展示旧量化结果隔离状态"`

## Task 4: Task 6 集成验收

- [ ] 更新 `2026-08-10-quant-core-v3-phase-0-repository-ci-legacy.md` 的 Task 6 checkbox，只勾选已有机器证据支持的步骤。
- [ ] 运行 `uv run pytest tests/integration/test_runtime_round_trip.py tests/repository/test_dev_launcher.py tests/api/test_paper_routes.py tests/api/test_model_registry.py -q --basetemp .astraquant/test-tmp/task6-final`。
- [ ] 运行 `pnpm --dir apps/desktop test`、`pnpm --dir apps/desktop check`、`pnpm --dir apps/desktop build`。
- [ ] 运行 `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml`。
- [ ] 运行 `uv run ruff check packages/api/src tests/api tests/integration tests/repository`、`uv run ruff format --check packages/api/src tests/api tests/integration tests/repository` 与 `uv run mypy packages/api/src tests/api tests/integration tests/repository`。
- [ ] 检查 `git diff --name-status origin/codex/quant-core-v3-phase0-task5...HEAD` 仅含 Task 6 文件，然后推送 `codex/quant-core-v3-phase0-task6`。

## Self-review

- Spec coverage: 覆盖 runtime/integration/launcher discovery、API/TypeScript 一致分类、UI 分区和禁止升级动作。
- No placeholders: 所有 symbol、字段、命令、失败原因和提交边界均明确。
- Type consistency: 三类对象统一使用 snake_case `semantic_class/evidence_class/run_class`；不混入 camelCase alias。
- Scope: 不创建 Phase 1 的 execution/research package，只保证未来 package 自动发现；不改变 handshake，不把 legacy 数据升级为 formal。

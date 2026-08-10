# Phase 0 Task 1 Repository and CI Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立唯一、fail-fast、可在本地与 GitHub Actions 重复执行的仓库验证入口，并阻止真实数据、运行产物、模型和秘密进入 Git。

**Architecture:** `scripts/verify.ps1` 是唯一验证编排器，按 `Python|Desktop|Rust|All` scope 运行现有工具链并为每次执行生成 UUID 临时目录和逐命令日志；任何 native command 非零都立即失败。`.github/workflows/ci.yml` 只安装锁定工具链并调用该脚本，不复制测试、lint 或 build 命令。`tools/repository_policy.py` 保持纯函数扫描与 CLI 两层结构，供 pytest 和验证脚本共同消费。

**Tech Stack:** PowerShell 7/Windows PowerShell、GitHub Actions、Python 3.12、uv 0.11.32、pytest、Ruff、mypy、Node 24、pnpm 11.9.0、Vitest/TypeScript/Vite、Rust 1.96.0、Cargo、pytest。

---

### Task 1: 用红灯契约冻结唯一验证入口

**Files:**
- Create: `tests/repository/test_ci_workflow.py`

- [ ] **Step 1: 写验证脚本契约测试**

在 `tests/repository/test_ci_workflow.py` 写入测试，读取 `scripts/verify.ps1`，断言：

```python
import re
from pathlib import Path


def test_verify_script_defines_scopes_unique_temp_and_fail_fast_commands() -> None:
    script = Path("scripts/verify.ps1").read_text(encoding="utf-8")

    assert '[ValidateSet("Python", "Desktop", "Rust", "All")]' in script
    assert "[guid]::NewGuid().ToString(\"n\")" in script
    assert "--basetemp" in script
    assert "Invoke-Checked" in script
    assert "if ($exitCode -ne 0)" in script
    normalized = re.sub(r"\s+", " ", script)
    for invocation in (
        '-FilePath "uv" -ArgumentList @("run", "pytest", "-q"',
        '-FilePath "uv" -ArgumentList @("run", "ruff", "check", ".")',
        '-FilePath "uv" -ArgumentList @("run", "ruff", "format", "--check", ".")',
        '-FilePath "uv" -ArgumentList @("run", "mypy")',
        '-FilePath "uv" -ArgumentList @("run", "python", "tools/repository_policy.py")',
        '-FilePath "pnpm" -ArgumentList @("--dir", "apps/desktop", "test")',
        '-FilePath "pnpm" -ArgumentList @("--dir", "apps/desktop", "check")',
        '-FilePath "pnpm" -ArgumentList @("--dir", "apps/desktop", "build")',
        '-FilePath "cargo" -ArgumentList @("fmt"',
        '-FilePath "cargo" -ArgumentList @("clippy"',
        '-FilePath "cargo" -ArgumentList @("test"',
    ):
        assert invocation in normalized
```

- [ ] **Step 2: 写 CI 单入口契约测试**

同文件增加：

```python
def test_ci_uses_pinned_toolchains_and_only_the_shared_verifier() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "windows-latest" in workflow
    assert "python-version: '3.12'" in workflow
    assert "version: '0.11.32'" in workflow
    assert "node-version: '24'" in workflow
    assert "pnpm@11.9.0" in workflow
    assert "toolchain: 1.96.0" in workflow
    assert "./scripts/verify.ps1 -Scope All" in workflow
    assert workflow.count("./scripts/verify.ps1") == 1
    for forbidden_duplicate in (
        "uv run pytest",
        "uv run ruff",
        "uv run mypy",
        "pnpm --dir apps/desktop test",
        "cargo test",
    ):
        assert forbidden_duplicate not in workflow
```

- [ ] **Step 3: 运行测试并确认正确红灯**

Run:

```powershell
uv run pytest tests/repository/test_ci_workflow.py -q
```

Expected: FAIL；`scripts/verify.ps1` 或 `.github/workflows/ci.yml` 不存在。失败不得来自 import、编码或 pytest 配置。

- [ ] **Step 4: 提交红灯契约**

```powershell
git add tests/repository/test_ci_workflow.py
git commit -m "test(ci): 冻结统一仓库验证契约"
```

### Task 2: 实现 fail-fast PowerShell 验证器

**Files:**
- Create: `scripts/verify.ps1`
- Test: `tests/repository/test_ci_workflow.py`

- [ ] **Step 1: 实现参数、路径与 native command wrapper**

`scripts/verify.ps1` 必须使用以下稳定接口：

```powershell
param(
    [ValidateSet("Python", "Desktop", "Rust", "All")]
    [string]$Scope = "All"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$runId = [guid]::NewGuid().ToString("n")
$tempRoot = Join-Path $projectRoot ".astraquant/test-tmp/$runId"
$logRoot = Join-Path $projectRoot ".astraquant/test-logs/$runId"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )

    $logPath = Join-Path $logRoot "$Name.log"
    & $FilePath @ArgumentList 2>&1 | Tee-Object -FilePath $logPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Verification command '$Name' failed with exit code $exitCode. Log: $logPath"
    }
}
```

脚本必须在 `try/finally` 中切换到 `$projectRoot`，预先创建 temp/log 目录，并检测当前 scope 所需的 `uv`、`pnpm`、`cargo` 命令；缺命令时抛出不含 secret/path dump 的明确错误。

- [ ] **Step 2: 实现 Python scope**

通过 `Invoke-Checked` 顺序执行：

```powershell
uv run pytest -q --basetemp $tempRoot/pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python tools/repository_policy.py
```

每个命令使用独立日志名；前一命令失败时不得执行后一命令。

- [ ] **Step 3: 实现 Desktop 与 Rust scopes**

Desktop 顺序：

```powershell
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

Rust 顺序：

```powershell
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --all -- --check
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
```

`All` 精确执行 Python→Desktop→Rust；单 scope 不运行其他工具链。

- [ ] **Step 4: 运行契约测试，确认 script 侧已转绿**

Run:

```powershell
uv run pytest tests/repository/test_ci_workflow.py::test_verify_script_defines_scopes_unique_temp_and_fail_fast_commands -q
```

Expected: PASS。

- [ ] **Step 5: 运行 Python scope 的真实 smoke**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Scope Python
```

Expected: pytest、Ruff check、Ruff format check、mypy、repository policy 全部退出 0；输出一个 UUID log root。

- [ ] **Step 6: 提交脚本**

```powershell
git add scripts/verify.ps1
git commit -m "ci: 建立统一失败即停验证脚本"
```

### Task 3: 建立只调用共享脚本的 Windows CI

**Files:**
- Create: `.github/workflows/ci.yml`
- Test: `tests/repository/test_ci_workflow.py`

- [ ] **Step 1: 写 workflow**

workflow 必须具备：

```yaml
name: CI

on:
  push:
  pull_request:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  verify:
    runs-on: windows-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5
        with:
          python-version: '3.12'
      - uses: astral-sh/setup-uv@94527f2e458b27549849d47d273a16bec83a01e9 # v7
        with:
          version: '0.11.32'
          enable-cache: true
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4
        with:
          node-version: '24'
      - name: Enable pinned pnpm
        shell: pwsh
        run: |
          corepack enable
          corepack prepare pnpm@11.9.0 --activate
      - uses: dtolnay/rust-toolchain@6c977a6ca4077a0ceb28ffbe03f59d46e9ac8772
        with:
          toolchain: 1.96.0
          components: clippy, rustfmt
      - name: Install locked dependencies
        shell: pwsh
        run: |
          uv sync --locked --all-packages
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          pnpm install --frozen-lockfile
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
      - name: Run shared verification gate
        shell: pwsh
        run: ./scripts/verify.ps1 -Scope All
      - name: Upload verification logs
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: verification-logs-${{ github.run_id }}
          path: .astraquant/test-logs/**
          include-hidden-files: true
          if-no-files-found: error
          retention-days: 7
```

CI 不得包含任何测试/lint/build 命令副本；dependency install 是环境准备，不属于验证门。

- [ ] **Step 2: 运行 CI contract tests**

Run:

```powershell
uv run pytest tests/repository/test_ci_workflow.py -q
```

Expected: 两个测试 PASS。

- [ ] **Step 3: 提交 workflow**

```powershell
git add .github/workflows/ci.yml tests/repository/test_ci_workflow.py
git commit -m "ci: 恢复Windows持续集成门"
```

### Task 4: 加严仓库数据与秘密政策

**Files:**
- Modify: `tests/repository/test_repository_policy.py`
- Modify: `tools/repository_policy.py`

- [ ] **Step 1: 写路径红灯测试**

增加测试，输入以下路径并要求全部拒绝：

```python
def test_reject_raw_captures_qualification_bodies_and_append_only_databases() -> None:
    paths = [
        "packages/data/raw-captures/eastmoney/page-1.json",
        "raw-captures/eastmoney/page-1.ndjson",
        "captures/eastmoney/daily.capture.json",
        "qualification-reports/eastmoney/report.json",
        "state/formal/catalog.sqlite-wal",
        "artifacts/verification/run.json",
        "models/champion.onnx",
    ]

    assert find_forbidden_paths(paths) == paths
```

- [ ] **Step 2: 写秘密内容红灯测试**

```python
def test_reject_generic_astraquant_tokens_and_secret_json_fields() -> None:
    contents = {
        "notes/token.txt": "ASTRAQUANT_BROKER_TOKEN=real-token",
        "tmp/config.json": '{"client_secret": "real-secret"}',
        "tmp/password.json": '{"password": "real-password"}',
    }

    assert find_forbidden_content(contents) == list(contents)
```

Run:

```powershell
uv run pytest tests/repository/test_repository_policy.py -q
```

Expected: 新测试 FAIL，因为 `.ndjson`、capture/qualification roots 和通用 secret assignments 尚未识别。

- [ ] **Step 3: 实现最小政策扩展**

在 `tools/repository_policy.py`：

- 把 `.jsonl`、`.ndjson` 加入 `FORBIDDEN_SUFFIXES`；
- 新建不受 source-code 目录例外影响的 `FORBIDDEN_ARTIFACT_DIRECTORIES={"captures", "raw-captures", "qualification-reports"}`；这些目录在 `packages/data` 或 `tests/data` 下也必须拒绝；
- 将内容正则扩展为 `ASTRAQUANT_[A-Z0-9_]*(TOKEN|SECRET|PASSWORD)=...`，以及 JSON/YAML 风格的 `access_token|api_token|client_secret|password` 非 `[REDACTED]` 值；
- 保持 `.env.example` 与测试文件例外；
- 不禁止源代码路径中的 `capture.py`、`qualification.py`、schema、脱敏摘要或 digest 文档。

- [ ] **Step 4: 运行 repository policy tests**

Run:

```powershell
uv run pytest tests/repository/test_repository_policy.py tests/repository/test_ci_workflow.py -q
```

Expected: PASS。

- [ ] **Step 5: 运行 CLI 扫描当前 Git index**

Run:

```powershell
uv run python tools/repository_policy.py
```

Expected: 输出 `Repository policy passed.`，退出 0。

- [ ] **Step 6: 提交政策变更**

```powershell
git add tools/repository_policy.py tests/repository/test_repository_policy.py
git commit -m "security: 阻止真实量化数据与秘密入库"
```

### Task 5: 完成 Task 1 全门验证与原子收口

**Files:**
- Modify: `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-0-repository-ci-legacy.md`

- [ ] **Step 1: 运行 Task 1 定向测试**

```powershell
uv run pytest tests/repository/test_ci_workflow.py tests/repository/test_repository_policy.py -q
```

Expected: PASS，0 failures。

- [ ] **Step 2: 运行共享 All gate**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Scope All
```

Expected: Python、Desktop、Rust 全部通过；任何失败都保留对应 `.astraquant/test-logs/{run_id}` 日志并阻止后续命令。

- [ ] **Step 3: 检查计划范围和工作树**

```powershell
git diff --check
git diff --name-status codex/quant-core-v3-plans...HEAD
git status --short
```

Expected: 只出现本微计划、CI、验证脚本、repository policy/tests 和 Phase 0 roadmap checkbox；无运行数据、日志、依赖目录或其他阶段代码。

- [ ] **Step 4: 勾选 Phase 0 Task 1 并提交**

只在上述命令真实通过后，把 Phase 0 Task 1 的 checkbox 全部改为 `[x]`，并提交：

```powershell
git add docs/superpowers/plans/2026-08-10-quant-core-v3-phase-0-repository-ci-legacy.md
git commit -m "docs: 记录Phase 0统一验证门完成证据"
```

- [ ] **Step 5: 推送实现分支**

```powershell
git push -u origin codex/quant-core-v3-phase0-task1
```

Expected: 远端 branch head 与本地 `HEAD` 完全一致；本步骤不创建或合并 PR。

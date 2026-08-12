# Kronos Upstream Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Kronos 官方项目作为固定版本、可持续同步且不干扰现有量化模型的独立上游完整引入 AstraQuant。

**Architecture:** 使用 `external/Kronos` Git submodule 保存完整上游仓库；使用 AstraQuant 自有文档和 manifest 固定来源与边界。本批不加载模型权重、不修改官方源码，也不改变任何现有训练路径。

**Tech Stack:** Git submodule、JSON manifest、Python/pytest、AstraQuant runner contract。

---

### Task 1: 封存官方上游源码

**Files:**
- Create: `.gitmodules`
- Create: `external/Kronos`

- [ ] 执行 `git submodule add https://github.com/shiyu-coder/Kronos.git external/Kronos`，必须完整 clone，不使用 shallow 参数。
- [ ] 执行 `git -C external/Kronos rev-parse HEAD`，预期为封存时记录的官方 commit。
- [ ] 执行 `git submodule status --recursive`，预期没有以 `-` 或 `+` 开头的未初始化/漂移条目。
- [ ] 提交 `.gitmodules` 和 submodule gitlink。

### Task 2: 固定模型边界和上游身份

**Files:**
- Create: `runners/kronos/README.md`
- Create: `runners/kronos/upstream-manifest.json`

- [ ] 在 manifest 写入官方 repository、branch、commit、公开模型清单和默认 `Kronos-base`。
- [ ] 在 README 明确 `external/Kronos` 只读、权重不进 Git、未来 runner 独立环境，以及自有模型不依赖 Kronos 可用性。
- [ ] 使用 Python 解析 manifest，预期 JSON 有效且 commit 与 submodule HEAD 相同。
- [ ] 提交 runner 边界文档和 manifest。

### Task 3: 验证不干扰现有训练系统

**Files:**
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`

- [ ] 运行 `uv run pytest tests/domain/test_research.py tests/research/test_runner_contract.py -q`，预期全部通过。
- [ ] 运行 `git -C external/Kronos status --short`，预期无输出。
- [ ] 在进度文档增加 Kronos 独立 challenger，并将“上游源码封存”标为完成；零样本 runner 与公平评估保持待办。
- [ ] 提交进度更新。

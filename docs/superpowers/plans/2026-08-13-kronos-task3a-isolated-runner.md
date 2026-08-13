# Kronos Task 3A Isolated Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在不安装 Torch、不下载权重的条件下，用可注入后端打通 request → windows → 多路径预测 → 标准 forecast response → 原子发布的完整隔离 runner。

**Architecture:** `run_request()` 负责契约、Parquet 与输出完整性，`KronosBackend` 只负责把一个 OHLCVA window 和 forecast times 转成多条 close paths。测试使用 deterministic fake backend；正式 upstream adapter 留给 Task 3B。任何 backend 异常、NaN、路径长度或覆盖错误都不得留下 response 文件。

**Tech Stack:** Python 3.11、PyArrow、标准库 statistics/random、pytest、Ruff、mypy。

---

## Task 3A.1: 冻结端到端 runner 行为

**Files:**

- Create: `runners/kronos/tests/test_runner.py`
- Create: `runners/kronos/tests/fakes.py`
- Modify: `runners/kronos/pyproject.toml`

- [x] 用真实 Task 1 request 和固定 Arrow windows fixture 测试每个 eligible row 恰好产生一个 forecast，顺序与 request 一致。
- [x] fake backend 返回 5 条未来 close paths；测试 terminal-return p10/p50/p90、expected return、上涨路径占比、波动和区间宽度。
- [x] 测试相同 request/backend 两次 response bytes 相同，派生 seed 对 fold/instrument/row 稳定且不同 row 不复用。
- [x] 测试 windows digest/schema/context/identity 错误、backend exception、NaN、路径数量/长度错误都不创建 output。
- [x] 首次运行目标测试，按预期因 `run_request` 不存在而失败。

## Task 3A.2: 实现隔离编排与 forecast 聚合

**Files:**

- Create: `runners/kronos/src/astraquant_kronos_runner/forecast.py`
- Create: `runners/kronos/src/astraquant_kronos_runner/runner.py`
- Modify: `runners/kronos/src/astraquant_kronos_runner/__init__.py`

- [x] 定义 `KronosBackend.predict_paths(...)` 与 `environment_identity()` Protocol。
- [x] `run_request(request_path, output_path, root, backend)` 先调用 Task 1 validator，再验证 `windows.parquet` digest、固定 schema、row coverage、sequence 和时间边界。
- [x] 使用 `sha256(global_seed,fold_id,instrument_id,row_id)` 派生 64 位 row seed，不依赖 Python hash randomization。
- [x] 将 paths 汇总为 Task 1 response 字段；所有 close 必须正数有限，路径数等于 sample count，长度等于 prediction length。
- [x] response 先写同目录临时文件，验证完整 response 后 rename；异常时删除临时文件且不触碰既有正式文件。
- [x] 运行 runner tests、Ruff、mypy；提交 `feat(kronos): 打通隔离零样本运行链路`。

## Task 3B 交接

下一微计划才安装官方依赖、实现只读 `external/Kronos` adapter、准备精确 revision 权重并完成真实 small/base smoke。Task 3A 的 fake backend 永不暴露为正式 CLI 模式。

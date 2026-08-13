# Kronos Task 2 Window Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 把统一多标的 panel 的测试行转换为 Kronos 官方接口需要的无未来泄漏 OHLCVA 历史窗口，并生成与 Task 1 契约一致的不可变 request。

**Architecture:** `astraquant_data.exports.kronos` 通过 Protocol 消费 panel/fold，不反向依赖 `astraquant_quant`。每个 test row 只导出 `event_time <= decision_time` 的最后 N 根真实 K 线；午休、隔夜或停牌间隔保留原始时间戳，不补造连续 K 线。context 不足的行不进入 request 的 `rows`，该列表就是公平评价使用的显式 eligibility mask。

**Tech Stack:** Python 3.12、PyArrow/Parquet、dataclasses/Protocol、pytest、Ruff、mypy。

---

## Task 2.1: 用测试冻结导出行为

**Files:**

- Create: `tests/data/test_kronos_export.py`

- [ ] 测试两个标的、一个 fold 的 test rows 被按 `(fold,row,sequence)` 稳定导出，Parquet 精确列为 identity、event_time 与 OHLCVA。
- [ ] 测试每个窗口最后时间等于 decision time，全部历史时间不晚于 decision time；午休/隔夜间隔按原时间戳保留。
- [ ] 测试 context 不足的 test row 从 request `rows` 排除，但 full folds digest 不变；重复导出到两个新目录的 request 与 Parquet bytes 一致。
- [ ] 测试非 exact snapshot、source/instrument 不匹配、决策时间与 raw bar 不一致、无 eligible rows、已存在 output root 全部 fail closed。
- [ ] 首次运行 `uv run pytest tests/data/test_kronos_export.py -q`，预期因 `astraquant_data.exports.kronos` 不存在而失败。

## Task 2.2: 实现确定性窗口和 request

**Files:**

- Create: `packages/data/src/astraquant_data/exports/kronos.py`
- Modify: `packages/data/src/astraquant_data/exports/__init__.py`

- [ ] 定义 `KronosSource`、`KronosArtifact`、`KronosExport` 以及 panel/instrument/fold Protocol。
- [ ] 实现 `export_kronos_request(...)`：校验 sources/folds/artifacts/config，计算 full folds digest，建立 eligible row identity。
- [ ] 从 `row_bar_indices[local_row_id]` 向前截取 context；若窗口不足则排除，若任何 bar 晚于 decision time 或当前 bar 不等于 decision time 则拒绝整个导出。
- [ ] 用固定 Arrow schema 写 `windows.parquet`；每条 row 保存 `fold_id,row_id,instrument_id,decision_time,sequence_index,event_time,open,high,low,close,volume,amount`。
- [ ] 生成 Task 1 request 字段与 canonical content digest；使用 must-not-exist 输出目录和临时文件 rename，失败不发布半份 request。
- [ ] 运行目标测试、Ruff、mypy；更新父计划和进度，提交 `feat(data): 导出Kronos真实K线窗口`。

## 完成后的程序能力

程序可以把任意数量标的的统一回测测试行变成 Kronos 可消费的真实 OHLCVA 窗口，同时明确哪些测试行因历史不足被排除。它不下载权重、不运行模型，也不改变现有 Ridge/DoubleEnsemble 结果。

# Qlib Fair Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让固定版本的 Qlib LightGBM 消费与 AstraQuant S1 完全相同的 Eastmoney 行集和 walk-forward folds，并输出可直接比较的预测与净收益差异。

**Architecture:** 主运行时只负责把训练行和 folds 导出为 Parquet+JSON；Qlib 位于独立 Python 3.11 runner，以固定 commit 安装。Runner 只输出逐 row prediction，AUC、交易阈值和费用仍由 AstraQuant 的统一评分器计算，避免两套收益口径。

**Tech Stack:** Python 3.12 host、Python 3.11 runner、PyArrow/Parquet、Qlib `79633dd9506ea689e5400dea0197717b5b3d74b7`、pytest、uv。

---

### Task 1: 冻结 Qlib 输入导出契约

**Files:**
- Create: `packages/data/src/astraquant_data/exports/__init__.py`
- Create: `packages/data/src/astraquant_data/exports/qlib.py`
- Create: `tests/data/test_qlib_export.py`

- [x] **Step 1: 写失败测试**：`export_qlib_request()` 接收 Eastmoney dataset/snapshot、S1 rows 与 `WalkForwardFold`，写出 `rows.parquet` 和 `request.json`；相同输入生成相同 `content_digest`，row order、fold index、feature value 或 source snapshot 改变会改变 digest。
- [x] **Step 2: 运行** `uv run pytest tests/data/test_qlib_export.py -q`，预期 module missing。
- [x] **Step 3: 最小实现**：Parquet 固定 `row_id`、十个 S1 features、`label/future_return`；request 固定 contract version、provider、dataset/snapshot、feature columns、fold indices、fee/threshold/seed、rows file SHA 和 Qlib upstream commit。
- [x] **Step 4: 增加拒绝非 Eastmoney、重复/越界 fold index、缺列/NaN、sentinel snapshot 的测试与实现。
- [x] **Step 5: 重跑 pytest、Ruff、format、mypy，预期全绿。

### Task 2: 建立固定 Qlib Runner 并运行共同 LightGBM

**Files:**
- Create: `runners/qlib/pyproject.toml`
- Create: `runners/qlib/.python-version`
- Create: `runners/qlib/runner-manifest.json`
- Create: `runners/qlib/src/astraquant_qlib_runner/__init__.py`
- Create: `runners/qlib/src/astraquant_qlib_runner/__main__.py`
- Create: `runners/qlib/src/astraquant_qlib_runner/dataset.py`
- Create: `runners/qlib/tests/test_runner.py`

- [x] **Step 1: 写 runner 失败测试**：读取 Task 1 export 后，逐 fold 调用 Qlib `LGBModel(loss="binary")`，输出每个 test row 的 `fold_id/row_id/probability`；输入 digest、commit 或 schema 不符时拒绝。
- [x] **Step 2: 创建独立 Python 3.11 project**，依赖固定 commit 的 `pyqlib`、pandas、pyarrow、pytest；不加入根 workspace。
- [x] **Step 3: 实现 duck-typed `AstraFoldDataset.prepare()`，向 Qlib 返回 `feature/label` MultiIndex DataFrame；模型 seed、线程数和 boosting 参数固定。
- [x] **Step 4: 运行** `uv lock --project runners/qlib`、`uv sync --project runners/qlib --frozen` 和 runner tests，预期全绿并生成独立 `uv.lock`。

### Task 3: 用 AstraQuant 统一评分并生成差异报告

**Files:**
- Modify: `packages/quant/src/astraquant_quant/baseline_matrix.py`
- Create: `tools/research/compare_qlib_baseline.py`
- Create: `tests/research/test_compare_qlib_baseline.py`
- Modify: `docs/superpowers/plans/2026-08-11-strategy-effect-fast-lane.md`
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`

- [x] **Step 1: 写失败测试**：Qlib prediction 使用 S1 相同 threshold/fee scorer；报告展示 native LightGBM 与 Qlib LightGBM 的 row/fold coverage、AUC/gross/net/trades 差异，缺一行预测即失败。
- [x] **Step 2: 实现公开 `score_fold_predictions()` 和 compare CLI；收益计算不进入 Qlib runner。
- [x] **Step 3: 在 fixture export 上运行 host→runner→compare 端到端测试，重复运行结果一致。
- [x] **Step 4: 运行 `scripts/verify.ps1 -Scope All`、独立 runner tests，更新 S2 进度，提交并推送 `feat(strategy): 接入Qlib公平模型对照`。

## Self-review

- Qlib 官方 Alpha158 handler 默认自行生成特征并使用固定日期切分，不能直接证明与 S1 公平；本阶段先用 Qlib 官方 `LGBModel` 对共同特征/共同 folds 做框架差分。共同 runner 稳定后，下一微计划再增加 Alpha158 特征组，并保持 row/fold/成本不变。
- Qlib 官方回测的 close 成交和默认成本只作参考，不进入本报告；所有净收益由 AstraQuant scorer 计算。

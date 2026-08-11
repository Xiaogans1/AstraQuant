# Alpha158 Fair Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用东方财富原始 bars 驱动固定 Qlib 官方 Alpha158 表达式，并在现有统一 OOS 扣费评分下与十特征 LightGBM 比较。

**Architecture:** Host 冻结 raw bars、训练行和 row-to-bar mapping；Python 3.11 runner 用内存 FeatureProvider 调用 Qlib 官方 expression engine。Runner 只输出逐行概率，收益仍由 AstraQuant host 计算。

**Tech Stack:** Python 3.12 host、Python 3.11 runner、Qlib pinned commit、PyArrow、LightGBM、pytest、uv。

---

### Task 1: 冻结 raw-bar 与训练行映射

**Files:**
- Modify: `packages/quant/src/astraquant_quant/research_features.py`
- Modify: `tools/research/build_training_set.py`
- Create: `packages/data/src/astraquant_data/exports/qlib_alpha158.py`
- Create: `tests/data/test_qlib_alpha158_export.py`
- Modify: `tests/quant/test_training_rows.py`
- Modify: `tests/research/test_build_training_set.py`

- [x] **Step 1:** 写失败测试：训练行返回全局 `row_bar_indices`，跨日仍严格对齐当前决策 bar。
- [x] **Step 2:** 运行测试，确认因映射 API/字段缺失而失败。
- [x] **Step 3:** 最小实现训练行映射，并让 training JSON 携带 raw OHLCV/VWAP context。
- [x] **Step 4:** 写失败测试并实现 Alpha158 request export；篡改 bars、未来映射、越界/非单调映射必须拒绝。
- [x] **Step 5:** 运行 Task 1 pytest、Ruff、mypy。

### Task 2: 用 Qlib 官方表达式生成 Alpha158 并训练

**Files:**
- Create: `runners/qlib/src/astraquant_qlib_runner/alpha158.py`
- Modify: `runners/qlib/src/astraquant_qlib_runner/__init__.py`
- Modify: `runners/qlib/src/astraquant_qlib_runner/__main__.py`
- Create: `runners/qlib/tests/test_alpha158.py`

- [x] **Step 1:** 写失败测试：官方 config 恰好生成 158 列，简单 K-bar 特征数值与预期一致，输入不下载/读取 Qlib provider 数据。
- [x] **Step 2:** 实现只读内存 FeatureProvider 与 `LocalExpressionProvider(time2idx=False)` 注册；用官方 `Alpha158DL.get_feature_config()` 计算特征。
- [x] **Step 3:** 写失败测试并实现 `run_alpha158_request()`；每个 fold 输出完整 test predictions，重复运行完全一致。
- [x] **Step 4:** 运行独立 runner tests，确认固定 commit 和 lockfile 未漂移。

### Task 3: 统一评分、差异报告与真实入口

**Files:**
- Create: `tools/research/export_qlib_alpha158.py`
- Create: `tools/research/compare_alpha158.py`
- Create: `tests/research/test_compare_alpha158.py`
- Modify: `docs/superpowers/plans/2026-08-11-strategy-effect-fast-lane.md`
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`

- [x] **Step 1:** 写失败测试：现有十特征与 Alpha158 必须共享 snapshot/folds/test rows/fee/threshold，少一行预测即拒绝。
- [x] **Step 2:** 实现 export/compare CLI；报告输出 `alpha158_minus_astra10` 的 AUC/gross/net/trades 差值。
- [x] **Step 3:** 运行 host→Alpha158 runner→compare 端到端，重复报告 digest 一致。
- [x] **Step 4:** 运行 `scripts/verify.ps1 -Scope All` 和 runner tests，更新进度、提交并推送。

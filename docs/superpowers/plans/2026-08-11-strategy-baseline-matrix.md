# Strategy Baseline Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正研究收益口径，并在完全相同的 walk-forward 样本与成本上比较 no-skill、Logistic Regression 和 LightGBM。

**Architecture:** `research_features.py` 只负责产生与标签同区间的训练行；新建 `baseline_matrix.py` 负责 folds、模型 adapter 与聚合报告；CLI 只负责 JSON I/O。所有模型共享 folds、特征列、阈值、费率和 seed。

**Tech Stack:** Python 3.12、scikit-learn、LightGBM、pytest、JSON。

---

### Task 1: 对齐标签与收益区间

**Files:**
- Modify: `packages/quant/src/astraquant_quant/research_features.py`
- Modify: `tests/quant/test_training_rows.py`
- Modify: `tests/research/test_train_model.py`

- [x] **Step 1: 写失败测试**：构造 index close 不变、下一根变化、horizon 终点反向变化的 bars，断言 `label` 与 `future_return` 都由 `bars[index].close → bars[index+horizon].close` 计算。
- [x] **Step 2: 运行** `uv run pytest tests/quant/test_training_rows.py tests/research/test_train_model.py -q`，预期旧实现因 `future_return` 使用 `index+1` 而失败。
- [x] **Step 3: 最小实现**：在 `build_training_rows()` 中统一调用一个持有区间收益函数，label 只由同一个 return 与 threshold 派生。
- [x] **Step 4: 重跑目标测试**，预期全绿。

### Task 2: 建立共享 walk-forward folds

**Files:**
- Create: `packages/quant/src/astraquant_quant/baseline_matrix.py`
- Create: `tests/quant/test_baseline_matrix.py`

- [x] **Step 1: 写失败测试**：`expanding_walk_forward(rows, minimum_train_size=40, test_size=10, fold_count=3)` 返回三个 fold，且每个 train 最大位置小于 test 最小位置；不足样本明确报错。
- [x] **Step 2: 运行** `uv run pytest tests/quant/test_baseline_matrix.py -q`，预期 import/module missing。
- [x] **Step 3: 最小实现**：定义 frozen `WalkForwardFold` 与 expanding splitter；不 shuffle，不跨模型重新切分。
- [x] **Step 4: 重跑目标测试**，预期全绿。

### Task 3: 比较三个开源基线

**Files:**
- Modify: `packages/quant/src/astraquant_quant/baseline_matrix.py`
- Modify: `tests/quant/test_baseline_matrix.py`

- [x] **Step 1: 写失败测试**：同一 folds 运行 `NO_SKILL/LOGISTIC_REGRESSION/LIGHTGBM`，每个模型得到相同 fold IDs/test row counts，并包含 AUC、gross/net/trades；重复运行报告相等。
- [x] **Step 2: 运行目标测试**，预期缺少 `run_baseline_matrix()`。
- [x] **Step 3: 最小实现**：no-skill 使用训练集正类率；Logistic 使用 `StandardScaler+LogisticRegression(random_state=seed)`；LightGBM 固定 seed、单线程和参数。固定预测阈值，`net=gross-2*fee_rate*trades`。
- [x] **Step 4: 增加全模型 `net_return<=0` 返回 `NO_EDGE`、否则选择净收益最高模型为 `CHALLENGER` 的测试与实现。
- [x] **Step 5: 重跑目标测试**，预期全绿。

### Task 4: CLI、进度与交付

**Files:**
- Create: `tools/research/run_baseline_matrix.py`
- Create: `tests/research/test_run_baseline_matrix.py`
- Modify: `docs/superpowers/plans/2026-08-11-strategy-effect-fast-lane.md`
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`

- [x] **Step 1: 写失败测试**：CLI 读取 `features.json`，输出稳定 JSON；缺 rows、非 Eastmoney provider metadata 或样本不足返回非零退出码且不写报告。
- [x] **Step 2: 运行目标测试**，预期 module missing。
- [x] **Step 3: 最小实现**：CLI 接受 input/output、fee/threshold/fold 参数，输出 model/fold/summary/status，不训练或发布 champion。
- [x] **Step 4: 运行定向测试、Ruff、format、mypy 与 `scripts/verify.ps1 -Scope All`。
- [x] **Step 5: 更新 S1 进度，提交并推送**：`git commit -m "feat(strategy): 建立公平开源模型基线矩阵"`。

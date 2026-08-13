# StockMixer Walk-forward Training Implementation Plan

> **Execution rule:** 按 task 顺序执行；每个 task 必须先红灯测试、再最小实现、再独立提交。不得让 outer-test 标签参与归一化、早停或阈值选择。

**Goal:** 将已验收的动态 StockMixer 核心升级为可在真实 Eastmoney A 股共享面板上按 fold 训练、早停、预测并生成确定性模型 artifact 的 challenger runner。

**Architecture:** `panel.parquet` 只物化一次共享 `time × instrument` 张量；`samples.parquet` 只保存窗口索引。每折从 `train` 尾部按时间切出 inner-valid，并在切分边界 purge；特征统计量只拟合 inner-train。模型同时优化有效标签上的回归损失与同一决策时点的截面排序损失，outer-test 仅在模型冻结后预测。

**Tech Stack:** Python 3.11、PyArrow、NumPy、PyTorch 2.7 CUDA、pytest。

---

### Task 1: Build lazy fold windows and masked objectives

**Files:**

- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/dataset.py`
- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/loss.py`
- Create: `runners/stockmixer/tests/test_dataset.py`
- Create: `runners/stockmixer/tests/test_loss.py`

- [x] Write red-light tests for canonical panel reshaping, lazy lookback slicing, train-only normalization, invalid-label exclusion and correct-vs-reversed ranking.
- [x] Run the focused tests and confirm missing-module failures.
- [x] Implement `PanelWindowDataset`, `FeatureNormalizer`, `fit_feature_normalizer` and `masked_stock_loss`.
- [x] Run focused and existing runner tests; run Ruff (`19 passed`; Ruff clean).
- [ ] Commit and push Task 1.

### Task 2: Train one fold without outer-test leakage

**Files:**

- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/training.py`
- Create: `runners/stockmixer/tests/test_training.py`

- [ ] Test deterministic tail-by-time inner validation, purge gap, seeded batches and test-label mutation invariance.
- [ ] Implement immutable `TrainingConfig`, fold split, CUDA/CPU trainer, patience-based early stopping and best-state restoration.
- [ ] Test that only inner-valid drives early stopping and outer-test is predicted once after freeze.
- [ ] Run focused and complete runner suites; commit and push Task 2.

### Task 3: Seal model and prediction artifacts

**Files:**

- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/artifacts.py`
- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/__main__.py`
- Create: `runners/stockmixer/tests/test_artifacts.py`
- Create: `runners/stockmixer/tests/test_cli.py`
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`

- [ ] Define a versioned response carrying request/config/code/model/prediction digests and fold metrics.
- [ ] Persist sorted tensor state without timestamps and reject overwrite/digest mismatch.
- [ ] Add CLI `train` command and deterministic repeated-run test.
- [ ] Run a real 9-ETF fold on CUDA, record runtime/metrics/digests and update progress.
- [ ] Run all required verification, commit and push Task 3.

# Training Task Contract and DoubleEnsemble Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 先建立不会把概率、预期收益、截面排序和风险分数混用的统一训练任务契约，再把 Qlib DoubleEnsemble 作为第一个生产路线 challenger 接入同一数据、fold、费用和执行评价协议。

**Architecture:** 稳定任务/分数语义进入 `astraquant_domain`；Qlib 模型保持在固定 commit 的隔离 runner。DoubleEnsemble 训练 future return 并输出 `EXPECTED_RETURN`，主进程依据版本化 selection policy 评分，绝不把原始回归值冒充概率。完成本计划只关闭 DoubleEnsemble challenger。

**Tech Stack:** Python 3.12、frozen dataclasses/Enum、pytest、Qlib `79633dd9506ea689e5400dea0197717b5b3d74b7`、LightGBM DoubleEnsemble runner。

---

## Task 1: 冻结统一训练任务与分数语义

**Files:**

- Create: `packages/domain/src/astraquant_domain/research.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`
- Create: `tests/domain/test_research.py`

- [x] 先测试六类 `TrainingTaskKind`、四类 `ScoreSemantics`、非空 label/universe/execution policy、正 horizon、稳定 `task_digest`。
- [x] 测试 `TrainingTaskSpec.assert_comparable_with()` 拒绝 task kind、label、horizon、score semantics、universe 或 execution policy 任一不一致。
- [x] 实现 immutable `TrainingTaskSpec` 和 canonical SHA-256 digest；不加入模型名，使不同模型在同一任务下可比较。
- [x] 运行 `uv run pytest tests/domain/test_research.py -q`、Ruff 和 mypy。
- [x] 提交：`feat(domain): 冻结统一训练任务语义`

## Task 2: 扩展 runner contract 支持声明式模型与回归分数

**Files:**

- Modify: `packages/data/src/astraquant_data/exports/qlib.py`
- Create: `contracts/research-runner/v1/request.schema.json`
- Create: `contracts/research-runner/v1/response.schema.json`
- Modify: `runners/qlib/src/astraquant_qlib_runner/dataset.py`
- Modify: `runners/qlib/src/astraquant_qlib_runner/__init__.py`
- Test: `tests/data/test_qlib_export.py`
- Test: `tests/research/test_runner_contract.py`
- Test: `runners/qlib/tests/test_runner.py`

- [x] 先测试 request 固定 `training_task_digest`、`model_kind`、target column；response 固定 `score_semantics`。
- [x] 保持现有 Qlib LightGBM binary 路径兼容，并新增 regression dataset target。
- [x] 非法的 model/score/target 组合必须 fail closed。
- [x] 运行主 workspace 与 runner 项目目标测试。
- [x] 提交：`feat(research): 扩展声明式Qlib训练契约`

## Task 3: 接入 DoubleEnsemble challenger

**Files:**

- Create: `runners/qlib/src/astraquant_qlib_runner/models/double_ensemble.py`
- Modify: `runners/qlib/src/astraquant_qlib_runner/__main__.py`
- Modify: `runners/qlib/tests/test_runner.py`
- Create: `tools/research/compare_double_ensemble.py`
- Create: `tests/research/test_compare_double_ensemble.py`

- [x] 先测试固定 seed/config 下输出 index、raw expected-return score、model/env/input digests 可重复。
- [x] 使用 Qlib `DEnsembleModel` 的 regression 语义；禁止 sigmoid、`0.5` threshold 或把结果命名为 probability。
- [x] 比较工具让 native Ridge regression 与 DoubleEnsemble 使用相同 expected-return selection policy；该步骤明确标记 `RESEARCH_RETURN_ONLY`，真实 A 股 executable-net-return 留给 Task 4，避免把行级收益评分冒充成交回放。
- [x] 提交：`feat(research): 接入DoubleEnsemble挑战模型`

## Task 4: 真实多标的验收与进度回写

**Files:**

- Create: `docs/verification/quant-core-v3/double-ensemble-challenger.md`
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`

- [ ] 使用 exact real-API snapshot、相同 folds/costs/seeds 分别运行两次，比较 input/fold/prediction/report digest。
- [ ] 报告按 fold、instrument、liquidity/regime 展示收益、回撤、换手、容量和成交集中度。
- [ ] 结论可以是 `INSUFFICIENT_EVIDENCE`；无论结果如何只更新 challenger 状态，不关闭训练核心。
- [ ] 提交：`test(research): 验收DoubleEnsemble挑战模型`

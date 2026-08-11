# Multi-ETF Panel Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 10 只真实 Eastmoney ETF 上用统一时间 folds 训练并执行 no-skill、Logistic Regression、LightGBM，输出确定性等权 OOS 净收益证据。

**Architecture:** 新增纯 Quant panel 模块，以 decision timestamp 构造带 purge 的 expanding walk-forward，并把 global OOS predictions 映射回各 instrument 的 local rows，复用 S3 可执行回测器。CLI 只负责 exact snapshot 加载、三模型编排和 JSON 报告。

**Tech Stack:** Python 3.12、LightGBM、scikit-learn、PyArrow、pytest。

---

### Task 1: Panel 时间轴与 folds

**Files:**
- Create: `packages/quant/src/astraquant_quant/panel_research.py`
- Create: `tests/quant/test_panel_research.py`

- [x] **Step 1: 写失败测试**

构造 A/B 两标的共享四个 timestamps 的 rows，断言 `build_panel()` 按 `(timestamp, instrument_id)` 排序；`panel_walk_forward(..., purge_timestamp_count=1)` 中相同 timestamp 不跨集合，且 train 最大 timestamp 严格早于 purge 后的 test 起点。

- [x] **Step 2: 验证 RED**

Run: `uv run pytest tests/quant/test_panel_research.py -q --basetemp .astraquant/test-tmp/s5-panel-red`

Expected: `ModuleNotFoundError: astraquant_quant.panel_research`。

- [x] **Step 3: 最小实现**

实现不可变 `PanelInstrumentData`、`PanelObservation`、`PanelDataset`，以及：

```python
def build_panel(instruments: Sequence[PanelInstrumentData]) -> PanelDataset: ...


def panel_walk_forward(
    panel: PanelDataset,
    *,
    minimum_train_timestamps: int,
    test_timestamp_count: int,
    fold_count: int,
    purge_timestamp_count: int,
) -> tuple[WalkForwardFold, ...]: ...
```

所有数量必须为正；instrument 唯一；rows、bars mapping 数量一致；bar index 有效；同 timestamp 只进入一个集合。

- [x] **Step 4: GREEN 与静态检查**

Run:

```powershell
uv run pytest tests/quant/test_panel_research.py -q --basetemp .astraquant/test-tmp/s5-panel-green
uv run ruff check packages/quant/src/astraquant_quant/panel_research.py tests/quant/test_panel_research.py
uv run mypy packages/quant/src/astraquant_quant/panel_research.py tests/quant/test_panel_research.py
```

Expected: 全部通过。

### Task 2: Global prediction 回落和等权执行

**Files:**
- Modify: `packages/quant/src/astraquant_quant/panel_research.py`
- Modify: `tests/quant/test_panel_research.py`

- [x] **Step 1: 写失败测试**

固定两标的 global predictions，断言 `localize_predictions()` 生成的 local folds/predictions 完整且无重复；调用 `run_panel_executable_model()` 后，总交易数等于 instrument reports 之和、初始/期末权益相加、panel net return 用总权益计算、字段名为 `worst_instrument_max_drawdown`。

- [x] **Step 2: 验证 RED**

Run: `uv run pytest tests/quant/test_panel_research.py -q --basetemp .astraquant/test-tmp/s5-execution-red`

Expected: 缺少 `localize_predictions` 或 `run_panel_executable_model`。

- [x] **Step 3: 最小实现**

实现：

```python
def localize_predictions(
    panel: PanelDataset,
    folds: Sequence[WalkForwardFold],
    predictions: Sequence[Mapping[str, object]],
    instrument_id: str,
) -> tuple[tuple[WalkForwardFold, ...], tuple[dict[str, object], ...]]: ...


def run_panel_executable_model(
    panel: PanelDataset,
    *,
    folds: Sequence[WalkForwardFold],
    model: BaselineModel,
    seed: int,
    prediction_threshold: float,
    holding_bars: int,
    policy: ExecutionPolicy,
) -> PanelExecutableReport: ...
```

模型只训练一次 global panel；每个 instrument 只执行属于自己的 OOS predictions。aggregate 从 instrument reports 加总，不拼接成交时间制造共享现金。

- [x] **Step 4: GREEN 与静态检查**

运行 Task 1 命令，Expected: 全部通过。

### Task 3: 真实 snapshot CLI 与证据门

**Files:**
- Create: `tools/research/run_panel_executable_backtest.py`
- Create: `tests/research/test_run_panel_executable_backtest.py`

- [x] **Step 1: 写失败测试**

发布两个 Eastmoney fixture snapshots，运行 CLI 两次并断言 bytes 相同、source snapshot 列表完整、三个模型共享 fold/test rows；交易不足 30 时状态为 `INSUFFICIENT_EVIDENCE`。把任一 provider 改为 fixture 时 CLI 返回 1。

- [x] **Step 2: 验证 RED**

Run: `uv run pytest tests/research/test_run_panel_executable_backtest.py -q --basetemp .astraquant/test-tmp/s5-cli-red`

Expected: `ModuleNotFoundError: tools.research.run_panel_executable_backtest`。

- [x] **Step 3: 最小实现**

CLI 参数固定为：

```text
run-panel-executable-backtest DATASET_ID... --data-root PATH --output PATH
  --minimum-train-timestamps 5000 --test-timestamp-count 1500 --fold-count 3
  --holding-bars 5 --prediction-threshold 0.5 --minimum-evidence-trades 30
```

使用 `build_features_json()` 重建每个 dataset，要求 `provider_id == "eastmoney"`；ETF policy 读取命令行显式费率，默认与当前持久化配置一致。输出 `astraquant.multi-etf-panel-executable/v1`，不写生成时间。

- [x] **Step 4: GREEN 与静态检查**

Run:

```powershell
uv run pytest tests/quant/test_panel_research.py tests/research/test_run_panel_executable_backtest.py -q --basetemp .astraquant/test-tmp/s5-cli-green
uv run ruff check packages/quant/src/astraquant_quant/panel_research.py tools/research/run_panel_executable_backtest.py tests/quant/test_panel_research.py tests/research/test_run_panel_executable_backtest.py
uv run mypy packages/quant/src/astraquant_quant/panel_research.py tools/research/run_panel_executable_backtest.py
```

Expected: 全部通过。

### Task 4: 真实 10 ETF 实验与交付

**Files:**
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`
- Modify: `docs/superpowers/plans/2026-08-11-strategy-effect-fast-lane.md`
- Modify: `docs/superpowers/plans/2026-08-11-multi-etf-panel-evaluation.md`

- [x] **Step 1: 真实运行两次**

使用 spec 固定的 10 个 dataset IDs、当前持久化费率、`5000/1500/3` folds 运行两次，比较 SHA-256。Expected: 完全一致；记录每模型交易数、净收益、胜率、最差单标的回撤和证据状态。51 个交易日经每日预热与标签尾部删除后只有 10,164 个有效 timestamps，因此首轮训练下限由原估算 6,000 修正为可执行的 5,000，OOS 4,500 timestamps、阈值和成本保持不变。

- [x] **Step 2: 全量验证**

Run:

```powershell
uv run pytest tests/quant/test_panel_research.py tests/research/test_run_panel_executable_backtest.py -q --basetemp .astraquant/test-tmp/s5-final
pwsh -File scripts/verify.ps1 -Scope All
```

Expected: 全部通过。

- [x] **Step 3: 更新进度、commit、push**

如实记录结果；若仍不足 30 笔，不改阈值并继续 HOLD。只 stage 本计划所列文件，保留 `.pytest-data/`，推送 `codex/quant-core-v3-phase1a-task3`。

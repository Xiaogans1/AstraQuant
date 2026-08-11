# A Share Executable Net Return Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在相同真实 Eastmoney rows、walk-forward folds 和模型预测上，输出按下一可执行开盘价、真实人民币费税、滑点与容量计算的资金曲线和净收益。

**Architecture:** `research_features` 先把标签统一成 next-open holding interval；新的 `executable_backtest` 只负责把冻结 predictions 映射为顺序资金交易。CLI 读取 Alpha158 冻结 request/response，同时在 host 训练 ASTRA10，确保两个模型共享执行配置。

**Tech Stack:** Python 3.12、Decimal、dataclasses、LightGBM、PyArrow、pytest、现有 Eastmoney/Qlib artifacts。

---

## 文件结构

- Modify: `packages/quant/src/astraquant_quant/research_features.py` — next-open label/return contract。
- Modify: `tools/research/build_training_set.py` — 固化 `holding_bars` 与 `label_price_contract`。
- Modify: `packages/quant/src/astraquant_quant/baseline_matrix.py` — 公开共同 fold prediction 生成器。
- Create: `packages/quant/src/astraquant_quant/executable_backtest.py` — 费税、成交、资金曲线及指标。
- Create: `tools/research/run_executable_backtest.py` — ASTRA10/Alpha158 共同执行报告。
- Test: `tests/quant/test_training_rows.py` — next-open 标签防前视。
- Test: `tests/quant/test_executable_backtest.py` — 成交、费税、容量、重叠和指标。
- Test: `tests/research/test_run_executable_backtest.py` — 端到端共同执行契约。
- Modify: `docs/superpowers/plans/2026-08-11-strategy-effect-fast-lane.md` — 勾选 S3。
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md` — 记录真实结果和下一阶段。

### Task 1: 将训练标签改为下一可执行开盘价

- [x] **Step 1: 写失败测试**

在 `tests/quant/test_training_rows.py` 构造 decision close 相同但 `i+1.open` 与 `i+horizon+1.open` 不同的 bars：

```python
def test_training_return_uses_next_open_entry_and_exit() -> None:
    rows = build_training_rows(bars, horizon=2, threshold=Decimal("0.05"))
    assert rows[0]["future_return"] == pytest.approx(0.10)
    assert rows[0]["label"] == 1
```

- [x] **Step 2: 验证 RED**

Run: `uv run pytest tests/quant/test_training_rows.py -q`

Expected: FAIL，旧实现仍使用 decision close 和 `index+horizon.close`。

- [x] **Step 3: 最小实现**

把 `_holding_period_return()` 改为：

```python
entry_index = index + 1
exit_index = index + horizon + 1
if exit_index >= len(bars):
    return None
entry = bars[entry_index].open
return (bars[exit_index].open - entry) / entry
```

训练 JSON 增加：

```python
"holding_bars": horizon,
"label_price_contract": "NEXT_OPEN_TO_NEXT_OPEN",
```

- [x] **Step 4: 验证 GREEN 与回归**

Run: `uv run pytest tests/quant/test_training_rows.py tests/research/test_build_training_set.py tests/research/test_train_model.py -q`

Expected: PASS。

### Task 2: 建立人民币资金级可执行评分器

- [x] **Step 1: 写费税和 next-open 失败测试**

在 `tests/quant/test_executable_backtest.py` 固定 100,000 CNY、100 股整数手、10→11 的 next-open round trip：

```python
policy = ExecutionPolicy(
    initial_cash=Decimal("100000"),
    commission_rate=Decimal("0.00025"),
    minimum_commission=Decimal("5"),
    stamp_duty_rate=Decimal("0.0005"),
    transfer_fee_rate=Decimal("0.00001"),
    slippage_bps=Decimal("0"),
    participation_rate=Decimal("1"),
    lot_size=100,
    instrument_kind=InstrumentKind.STOCK,
)
result = run_executable_backtest(...)
assert result.trades[0].entry_bar_index == decision_index + 1
assert result.trades[0].exit_bar_index == decision_index + holding_bars + 1
assert result.total_commission == Decimal("10.00")
assert result.total_stamp_duty > 0
```

再分别测试 ETF 印花税/过户费为零、最低佣金、滑点不利、100 股取整和双端容量。

- [x] **Step 2: 验证 RED**

Run: `uv run pytest tests/quant/test_executable_backtest.py -q`

Expected: ERROR，模块尚不存在。

- [x] **Step 3: 实现配置、交易和汇总类型**

在 `executable_backtest.py` 定义：

```python
class InstrumentKind(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    initial_cash: Decimal = Decimal("100000")
    commission_rate: Decimal = Decimal("0.00025")
    minimum_commission: Decimal = Decimal("0")
    stamp_duty_rate: Decimal = Decimal("0.0005")
    transfer_fee_rate: Decimal = Decimal("0.00001")
    slippage_bps: Decimal = Decimal("2")
    participation_rate: Decimal = Decimal("0.10")
    lot_size: int = 100
    instrument_kind: InstrumentKind = InstrumentKind.STOCK
```

实现 `run_executable_backtest(rows, raw_bars, row_bar_indices, folds, predictions, prediction_threshold, holding_bars, policy)`，逐 fold 独立从初始现金开始，顺序处理信号。

- [x] **Step 4: 写重叠和指标失败测试**

```python
assert report.executed_trades == 2
assert report.overlap_skips == 1
assert report.turnover > 0
assert report.max_drawdown >= 0
assert 0 <= report.win_rate <= 1
```

- [x] **Step 5: 实现顺序资金曲线**

同一 fold 内 `decision_index <= active_exit_index` 的新信号计入 `overlap_skips`。每笔交易使用 entry/exit 两端 `floor(volume * participation / lot_size) * lot_size` 的较小值和现金上限，逐笔更新 cash/equity，并汇总 drawdown、win rate、turnover、费用与滑点损耗。

- [x] **Step 6: 验证 GREEN**

Run: `uv run pytest tests/quant/test_executable_backtest.py -q`

Expected: PASS。

### Task 3: 让 ASTRA10 与 Alpha158 使用同一执行器

- [x] **Step 1: 写 prediction API 失败测试**

扩展 `tests/quant/test_baseline_matrix.py`：

```python
predictions = predict_fold_probabilities(BaselineModel.LIGHTGBM, rows, folds=folds, seed=7)
assert {(item["fold_id"], item["row_id"]) for item in predictions} == expected
```

- [x] **Step 2: 验证 RED 并实现公开 API**

Run: `uv run pytest tests/quant/test_baseline_matrix.py -q`

Expected: FAIL，API 尚不存在。随后把 `_evaluate_model()` 内的 prediction 生成提取为 `predict_fold_probabilities()`，原 S1 行为保持不变。

- [x] **Step 3: 写 CLI 端到端失败测试**

`tests/research/test_run_executable_backtest.py` 生成冻结 Alpha158 request/response，运行 CLI 并断言：

```python
assert result["schema_version"] == "astraquant.a-share-executable-backtest/v1"
assert result["fidelity"] == "BAR_NEXT_OPEN_CONSERVATIVE"
assert result["shared_contract"]["test_rows"] == 20
assert set(result["models"]) == {"ASTRA10_LIGHTGBM", "QLIB_ALPHA158_LIGHTGBM"}
assert result["models"]["ASTRA10_LIGHTGBM"]["executed_trades"] >= 0
```

- [x] **Step 4: 实现 CLI**

`run_executable_backtest.py` 校验 request/response digest、读取 `rows.parquet`/`bars.parquet`/`row_bar_indices`/folds，生成 host ASTRA10 predictions，并让两组 predictions 调用同一 `run_executable_backtest()`。输出冻结的 policy、共同 coverage、逐模型 metrics 和差值。

- [x] **Step 5: 验证端到端**

Run: `uv run pytest tests/quant/test_baseline_matrix.py tests/research/test_run_executable_backtest.py -q`

Expected: PASS。

### Task 4: 真实数据运行、回归和交付

- [x] **Step 1: 重建真实训练集与 Qlib artifacts**

使用 snapshot `7ae18d45894e850985d0da45006fd0ae8b7927fd5978710cd566ec588122cbec` 对应的 `cn-equity-159516-szse-1m-none`，重新运行 training set、Alpha158 export、固定 Qlib runner 和 S3 CLI；instrument kind 显式设为 `ETF`。

- [x] **Step 2: 重复运行并比较摘要**

相同输入运行两次，计算两个报告 SHA-256；Expected: 完全相同。

- [x] **Step 3: 运行目标与全量验证**

Run:

```powershell
uv run pytest tests/quant/test_training_rows.py tests/quant/test_baseline_matrix.py tests/quant/test_executable_backtest.py tests/research/test_run_executable_backtest.py -q
pwsh -File scripts/verify.ps1 -Scope All
```

Expected: 全部通过；只允许仓库已知 warning/skip。

- [x] **Step 4: 更新路线与进度文档**

勾选 S3 三项，记录 ASTRA10/Alpha158 的可执行净收益、回撤、换手和跳过机会，并把下一关键节点更新为 S4 目标仓位与 T+1。

- [x] **Step 5: 提交并推送**

```powershell
git add -- <本计划列出的代码、测试和文档>
git commit -m "feat(strategy): 完成A股可执行净收益回测"
git push origin codex/quant-core-v3-phase1a-task3
```

# Stage B v2 Batch 1 Label and Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立执行价格一致的 D1/D5/D10 截面标签、inner-valid Huber 收益校准和统一 rank-aware long-only 目标组合，为后续真实日线宽历史与 MASTER/StockMixer v2 公平竞赛提供不可变契约。

**Architecture:** Domain 包只定义多 horizon 标签矩阵与组合政策身份；Quant 包以全市场交易日历和动态 membership 计算 next-open 标签，再把已校准 forecast 转成带换手上限的目标权重。Batch 1 不下载新数据、不训练模型，也不修改既有分钟 BaseTarget；它交付后 Batch 2 可直接用东方财富日线面板物化相同契约。

**Tech Stack:** Python 3.12、dataclasses、Decimal、NumPy、现有 `MarketBar`、pytest、Ruff、mypy。

---

## File map

- `packages/domain/src/astraquant_domain/cross_sectional.py`: 稳定 label matrix、calibration policy 和 rank portfolio policy。
- `packages/domain/src/astraquant_domain/__init__.py`: 导出新契约。
- `packages/quant/src/astraquant_quant/cross_sectional_labels.py`: 计算 D1/D5/D10 raw/excess/rank/downside labels 和 train-only extreme mask。
- `packages/quant/src/astraquant_quant/return_calibration.py`: 只允许 inner-valid 拟合的确定性 Huber 线性校准器。
- `packages/quant/src/astraquant_quant/rank_portfolio.py`: 将 rank + calibrated return + volatility 转成 long-only 目标权重。
- `tests/domain/test_cross_sectional.py`: 契约和 digest 测试。
- `tests/quant/test_cross_sectional_labels.py`: 全市场日历、next-open、rank、极值和缺失语义。
- `tests/quant/test_return_calibration.py`: split gate、outlier robustness 和确定性。
- `tests/quant/test_rank_portfolio.py`: top fraction、正收益过滤、权重上限、换手和排列不变性。
- `tests/quant/test_stage_b_v2_batch1.py`: label→forecast→target 的 canonical 场景。

### Task 1: Freeze cross-sectional task contracts

**Files:**

- Create: `packages/domain/src/astraquant_domain/cross_sectional.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`
- Create: `tests/domain/test_cross_sectional.py`

- [x] **Step 1: Write the failing contract tests**

```python
from decimal import Decimal

import pytest
from astraquant_domain import (
    CrossSectionalTaskMatrix,
    RankPortfolioPolicy,
    ReturnCalibrationPolicy,
)


def test_stage_b_v2_contract_has_stable_identity() -> None:
    first = CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI")
    second = CrossSectionalTaskMatrix.stage_b_v2_daily("000985.CSI")
    assert first.horizons == (1, 5, 10)
    assert first.entry_lag_sessions == 1
    assert first.extreme_tail_fraction == Decimal("0.025")
    assert first.task_digest == second.task_digest


def test_rank_policy_freezes_strategy_semantics() -> None:
    policy = RankPortfolioPolicy.stage_b_v2()
    assert policy.top_fraction == Decimal("0.10")
    assert policy.max_positions == 50
    assert policy.max_instrument_weight == Decimal("0.03")
    assert policy.max_one_way_turnover == Decimal("0.20")


@pytest.mark.parametrize("horizons", [(1, 1), (5, 1), ()])
def test_task_matrix_rejects_noncanonical_horizons(horizons: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        CrossSectionalTaskMatrix(
            schema_version="astraquant.cross-sectional-task/v1",
            benchmark_instrument_id="000985.CSI",
            horizons=horizons,
            entry_lag_sessions=1,
            extreme_tail_fraction=Decimal("0.025"),
        )


def test_calibration_policy_only_accepts_inner_valid() -> None:
    policy = ReturnCalibrationPolicy.stage_b_v2()
    assert policy.fit_segment == "inner_valid"
    with pytest.raises(ValueError, match="inner_valid"):
        ReturnCalibrationPolicy(
            schema_version=policy.schema_version,
            method="HUBER_LINEAR",
            fit_segment="outer_test",
            huber_delta=Decimal("1.345"),
            max_iterations=20,
        )
```

- [x] **Step 2: Run the contract tests and confirm the import red light**

Run:

```powershell
uv run pytest tests/domain/test_cross_sectional.py -q --basetemp .test-tmp/stage-b-v2-contract-red
```

Expected: collection fails because the three contracts are absent.

- [x] **Step 3: Implement immutable contracts and canonical digests**

Create three frozen dataclasses with these exact factory values:

```python
CrossSectionalTaskMatrix(
    schema_version="astraquant.cross-sectional-task/v1",
    benchmark_instrument_id=benchmark,
    horizons=(1, 5, 10),
    entry_lag_sessions=1,
    extreme_tail_fraction=Decimal("0.025"),
)
ReturnCalibrationPolicy(
    schema_version="astraquant.return-calibration/v1",
    method="HUBER_LINEAR",
    fit_segment="inner_valid",
    huber_delta=Decimal("1.345"),
    max_iterations=20,
)
RankPortfolioPolicy(
    schema_version="astraquant.rank-portfolio/v1",
    top_fraction=Decimal("0.10"),
    max_positions=50,
    max_instrument_weight=Decimal("0.03"),
    max_one_way_turnover=Decimal("0.20"),
)
```

Validation must require sorted unique positive horizons, `entry_lag_sessions == 1`, tail fraction in `[0, 0.5)`, `fit_segment == "inner_valid"`, positive Huber values, top fraction/weight/turnover in `(0, 1]`, and positive max positions. Each class exposes a `*_digest` computed from sorted canonical JSON with Decimal serialized as strings.

- [x] **Step 4: Export the contracts and run green tests (`29 passed`; Ruff clean)**

Run:

```powershell
uv run pytest tests/domain/test_cross_sectional.py tests/domain/test_research.py -q --basetemp .test-tmp/stage-b-v2-contract-green
uv run ruff check packages/domain/src/astraquant_domain/cross_sectional.py tests/domain/test_cross_sectional.py
```

Expected: all selected tests pass and Ruff reports `All checks passed!`.

- [x] **Step 5: Commit Task 1 (`bb0b9a4`)**

```powershell
git add packages/domain/src/astraquant_domain/cross_sectional.py packages/domain/src/astraquant_domain/__init__.py tests/domain/test_cross_sectional.py
git commit -m "feat(domain): 冻结截面任务与组合契约"
```

### Task 2: Build execution-aligned daily label matrices

**Files:**

- Create: `packages/quant/src/astraquant_quant/cross_sectional_labels.py`
- Create: `tests/quant/test_cross_sectional_labels.py`

- [x] **Step 1: Write failing next-open and rank tests**

The fixture contains 50 instruments and 13 timezone-aware sessions. For instrument `S000`, decision session index 0, D5 must use `open[1]` as entry and `open[6]` as exit. The test must assert:

```python
rows = build_daily_cross_sectional_labels(panel, matrix)
d5 = _row(rows, "S000.SSE", decision_index=0, horizon=5)
assert d5.raw_return == (panel.open("S000.SSE", 6) / panel.open("S000.SSE", 1)) - 1
assert d5.market_excess_return == d5.raw_return - d5.benchmark_return
assert Decimal("0") <= d5.cross_sectional_rank <= Decimal("1")
assert d5.downside_risk >= 0
```

Add independent tests that:

- mutate decision-day close and confirm next-open labels do not change;
- remove the entry or exit bar and confirm only that instrument/horizon is absent;
- confirm rank 0 is the worst and rank 1 is the best for 50 unique returns;
- confirm exactly one instrument per tail has `training_eligible=False` when `n=50` (`floor(50×0.025)=1`);
- confirm all valid rows remain present even when `training_eligible=False`;
- reject a non-canonical session calendar, unknown membership instrument or missing benchmark bar.

- [x] **Step 2: Run the label tests and confirm the missing module red light**

Run:

```powershell
uv run pytest tests/quant/test_cross_sectional_labels.py -q --basetemp .test-tmp/stage-b-v2-label-red
```

Expected: collection fails for `astraquant_quant.cross_sectional_labels`.

- [x] **Step 3: Implement panel and label types**

Use these public types:

```python
@dataclass(frozen=True, slots=True)
class DailyCrossSectionalPanel:
    sessions: tuple[datetime, ...]
    instrument_bars: Mapping[str, Mapping[datetime, MarketBar]]
    benchmark_bars: Mapping[datetime, MarketBar]
    eligible_by_session: Mapping[datetime, frozenset[str]]


@dataclass(frozen=True, slots=True)
class CrossSectionalLabelRow:
    decision_time: datetime
    instrument_id: str
    horizon_sessions: int
    entry_time: datetime
    exit_time: datetime
    raw_return: Decimal
    benchmark_return: Decimal
    market_excess_return: Decimal
    cross_sectional_rank: Decimal
    downside_risk: Decimal
    training_eligible: bool
```

`build_daily_cross_sectional_labels(panel, matrix)` must:

1. iterate decision sessions in chronological order;
2. use global session offsets `entry = decision + 1`, `exit = entry + horizon`;
3. require instrument entry/exit bars and all benchmark sessions;
4. calculate downside as `max(0, 1 - min(low[entry:exit+1]) / entry_open)`;
5. rank `market_excess_return` per `(decision_time, horizon)` with deterministic average rank for ties, scaled to `[0, 1]`;
6. sort rows by `(decision_time, horizon, instrument_id)`;
7. mark the bottom/top `floor(n * 0.025)` rows as train-ineligible using `(return, instrument_id)` canonical order, without deleting rows.

- [x] **Step 4: Run label green tests and existing minute-label regressions (`19 passed`; Ruff and mypy clean)**

Run:

```powershell
uv run pytest tests/quant/test_cross_sectional_labels.py tests/quant/test_research_features.py tests/quant/test_training_rows.py -q --basetemp .test-tmp/stage-b-v2-label-green
uv run ruff check packages/quant/src/astraquant_quant/cross_sectional_labels.py tests/quant/test_cross_sectional_labels.py
```

Expected: all tests pass; existing minute labels are unchanged.

- [x] **Step 5: Commit Task 2 (`ac835ff`)**

```powershell
git add packages/quant/src/astraquant_quant/cross_sectional_labels.py tests/quant/test_cross_sectional_labels.py
git commit -m "feat(quant): 构建多周期截面收益标签"
```

### Task 3: Fit an inner-valid-only return calibrator

**Files:**

- Create: `packages/quant/src/astraquant_quant/return_calibration.py`
- Create: `tests/quant/test_return_calibration.py`

- [x] **Step 1: Write failing leakage and robustness tests**

```python
def test_huber_calibration_is_robust_and_deterministic() -> None:
    samples = [CalibrationSample(score=float(x), realized_return=2 * x + 1) for x in range(20)]
    samples.append(CalibrationSample(score=10.0, realized_return=-10000.0))
    first = fit_huber_linear(samples, policy=_policy(), segment="inner_valid")
    second = fit_huber_linear(samples, policy=_policy(), segment="inner_valid")
    assert first == second
    assert 1.5 < first.slope < 2.5
    assert 0.5 < first.intercept < 1.5


def test_outer_test_cannot_fit_calibrator() -> None:
    with pytest.raises(ValueError, match="inner_valid"):
        fit_huber_linear(_samples(), policy=_policy(), segment="outer_test")
```

Also test constant scores, fewer than three samples, NaN/inf and mutated outer-test rows.

- [x] **Step 2: Confirm the calibration module red light**

Run:

```powershell
uv run pytest tests/quant/test_return_calibration.py -q --basetemp .test-tmp/stage-b-v2-calibration-red
```

Expected: missing module failure.

- [x] **Step 3: Implement deterministic IRLS Huber regression**

Public API:

```python
@dataclass(frozen=True, slots=True)
class CalibrationSample:
    score: float
    realized_return: float


@dataclass(frozen=True, slots=True)
class HuberLinearCalibrator:
    slope: float
    intercept: float
    sample_count: int
    policy_digest: str

    def predict(self, score: float) -> float:
        if not math.isfinite(score):
            raise ValueError("score must be finite")
        return self.intercept + self.slope * score


def fit_huber_linear(
    samples: Sequence[CalibrationSample],
    *,
    policy: ReturnCalibrationPolicy,
    segment: str,
) -> HuberLinearCalibrator:
    if segment != policy.fit_segment:
        raise ValueError("calibrator may only fit inner_valid")
    values = tuple(samples)
    if len(values) < 3:
        raise ValueError("calibration requires at least three samples")
    x = np.asarray([item.score for item in values], dtype=np.float64)
    y = np.asarray([item.realized_return for item in values], dtype=np.float64)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("calibration samples must be finite")
    if np.ptp(x) <= 1e-12:
        return HuberLinearCalibrator(
            slope=0.0,
            intercept=float(np.median(y)),
            sample_count=len(values),
            policy_digest=policy.calibration_digest,
        )
    design = np.column_stack((x, np.ones_like(x)))
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    for _ in range(policy.max_iterations):
        residual = y - design @ beta
        median = np.median(residual)
        scale = max(1.4826 * float(np.median(np.abs(residual - median))), 1e-12)
        threshold = float(policy.huber_delta) * scale
        absolute = np.abs(residual)
        weights = np.ones_like(absolute)
        outside = absolute > threshold
        weights[outside] = threshold / absolute[outside]
        weighted = design * np.sqrt(weights)[:, None]
        beta = np.linalg.lstsq(weighted, y * np.sqrt(weights), rcond=None)[0]
    return HuberLinearCalibrator(
        slope=float(beta[0]),
        intercept=float(beta[1]),
        sample_count=len(values),
        policy_digest=policy.calibration_digest,
    )
```

Use NumPy float64, add an intercept column, initialize with `np.linalg.lstsq`, then run exactly `policy.max_iterations` IRLS iterations with Huber weights `1` inside delta and `delta/abs(residual)` outside. Scale delta by `max(1.4826*MAD(residual), 1e-12)`. Constant score returns slope 0 and median target intercept. Reject fewer than three finite samples.

- [x] **Step 4: Run calibration tests and lint (`14 passed`; Ruff and mypy clean)**

```powershell
uv run pytest tests/quant/test_return_calibration.py -q --basetemp .test-tmp/stage-b-v2-calibration-green
uv run ruff check packages/quant/src/astraquant_quant/return_calibration.py tests/quant/test_return_calibration.py
```

Expected: green and deterministic.

- [x] **Step 5: Commit Task 3 (`f9642dd`)**

```powershell
git add packages/quant/src/astraquant_quant/return_calibration.py tests/quant/test_return_calibration.py
git commit -m "feat(quant): 增加inner-valid收益校准"
```

### Task 4: Construct rank-aware long-only targets

**Files:**

- Create: `packages/quant/src/astraquant_quant/rank_portfolio.py`
- Create: `tests/quant/test_rank_portfolio.py`

- [x] **Step 1: Write failing selection, risk and turnover tests**

Use these assertions:

```python
target = build_rank_portfolio_target(
    forecasts=_forecasts(count=40),
    current_weights={},
    policy=RankPortfolioPolicy.stage_b_v2(),
)
assert len(target.selected_instruments) == 4  # ceil(40 * 10%)
assert all(weight <= Decimal("0.03") for weight in target.target_weights.values())
assert target.cash_weight == Decimal("0.88")  # four capped 3% positions
```

Add tests for:

- top-ranked forecast with negative calibrated return is not replaced by a lower-ranked name;
- lower volatility gets larger uncapped inverse-volatility weight;
- input permutation produces identical target digest;
- non-tradable forecasts never enter selection;
- current holdings outside selection target zero;
- interpolated target has one-way turnover `<= 0.20`;
- empty/negative-edge input returns 100% cash;
- duplicate instruments, non-finite scores, zero volatility and current weights above one fail closed.

- [x] **Step 2: Confirm the rank portfolio module red light**

```powershell
uv run pytest tests/quant/test_rank_portfolio.py -q --basetemp .test-tmp/stage-b-v2-portfolio-red
```

Expected: missing module failure.

- [x] **Step 3: Implement target construction**

Public types:

```python
@dataclass(frozen=True, slots=True)
class RankedForecast:
    forecast_id: str
    instrument_id: str
    rank_score: float
    calibrated_expected_return: float
    trailing_volatility: float
    tradable: bool


@dataclass(frozen=True, slots=True)
class RankPortfolioTarget:
    selected_instruments: tuple[str, ...]
    target_weights: Mapping[str, Decimal]
    cash_weight: Decimal
    one_way_turnover: Decimal
    policy_digest: str
    target_digest: str
```

Algorithm:

1. canonicalize and validate forecasts/current weights;
2. sort all tradable forecasts by `(-rank_score, instrument_id)`;
3. compute quota `min(max_positions, ceil(tradable_count * top_fraction))`;
4. inspect exactly the top quota and remove negative calibrated returns without backfill;
5. calculate inverse-volatility weights, water-fill repeatedly at 3%, and leave unallocatable capital as cash;
6. set unselected current holdings to target zero;
7. calculate one-way turnover as `sum(abs(target-current))/2` including cash;
8. if turnover exceeds 20%, interpolate every asset and cash weight by `limit/turnover`;
9. quantize Decimal weights to `1e-12`, remove exact zeros, and hash canonical sorted output.

- [x] **Step 4: Run portfolio and existing target regressions (`35 passed`; Ruff and mypy clean)**

```powershell
uv run pytest tests/quant/test_rank_portfolio.py tests/quant/test_targets.py tests/quant/test_strategy_layer.py -q --basetemp .test-tmp/stage-b-v2-portfolio-green
uv run ruff check packages/quant/src/astraquant_quant/rank_portfolio.py tests/quant/test_rank_portfolio.py
```

Expected: all pass; the existing per-instrument T+1 reconciliation remains unchanged.

- [ ] **Step 5: Commit Task 4**

```powershell
git add packages/quant/src/astraquant_quant/rank_portfolio.py tests/quant/test_rank_portfolio.py
git commit -m "feat(quant): 构建截面排名目标组合"
```

### Task 5: Close the canonical Batch 1 flow

**Files:**

- Create: `tests/quant/test_stage_b_v2_batch1.py`
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`
- Modify: `docs/superpowers/plans/2026-08-13-stage-b-v2-batch-1-label-portfolio.md`

- [ ] **Step 1: Add an end-to-end canonical test**

Build 50 securities × 13 sessions, create D1/D5/D10 labels, fit a calibrator only on an explicitly marked inner-valid subset, create ranked forecasts, and build one target. Assert:

```python
assert {row.horizon_sessions for row in labels} == {1, 5, 10}
assert all(row.entry_time > row.decision_time for row in labels)
assert target.selected_instruments == tuple(sorted(target.target_weights))
assert target.cash_weight + sum(target.target_weights.values()) == Decimal("1")
assert target.one_way_turnover <= Decimal("0.20")
```

Then mutate all outer-test realized returns and assert the calibrator and target digests do not change.

- [ ] **Step 2: Run the complete Batch 1 verification**

```powershell
New-Item -ItemType Directory -Force .test-tmp | Out-Null
uv run pytest tests/domain/test_cross_sectional.py tests/domain/test_research.py tests/quant/test_cross_sectional_labels.py tests/quant/test_return_calibration.py tests/quant/test_rank_portfolio.py tests/quant/test_stage_b_v2_batch1.py tests/quant/test_targets.py tests/quant/test_research_features.py -q --basetemp .test-tmp/stage-b-v2-batch1-final
uv run ruff check packages/domain/src packages/quant/src tests/domain tests/quant
uv run mypy packages/domain/src/astraquant_domain/cross_sectional.py packages/quant/src/astraquant_quant/cross_sectional_labels.py packages/quant/src/astraquant_quant/return_calibration.py packages/quant/src/astraquant_quant/rank_portfolio.py tests/domain/test_cross_sectional.py tests/quant/test_cross_sectional_labels.py tests/quant/test_return_calibration.py tests/quant/test_rank_portfolio.py tests/quant/test_stage_b_v2_batch1.py
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 3: Update user-facing progress**

Record that the program can now answer: “在某个日期，哪些股票在 D1/D5/D10 上相对更强、校准收益是否为正、在 3% 单票和 20% 换手约束下目标持仓是多少”。Do not claim model alpha or profitability; Batch 2 still needs real broad daily history.

- [ ] **Step 4: Close and commit the plan**

```powershell
git add tests/quant/test_stage_b_v2_batch1.py docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md docs/superpowers/plans/2026-08-13-stage-b-v2-batch-1-label-portfolio.md
git commit -m "docs(training): 关闭Stage B v2 Batch 1"
git push origin codex/stockmixer-shared-representation
```

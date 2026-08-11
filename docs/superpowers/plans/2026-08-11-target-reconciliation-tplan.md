# Target Reconciliation and TPlan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 forecast 转换为不可变 BaseTarget，并输出受 T+1、现金、整数手、活动委托和底仓约束后的可执行数量与做 T 计划。

**Architecture:** `targets.py` 提供纯函数 forecast→target 与 target→reachable intent；`tplan.py` 只生成两腿计划草案。研究 CLI 读取 S3 报告决定 evidence status，并输出真实模型 HOLD 与 canonical validated 场景，不接管订单或成交。

**Tech Stack:** Python 3.12、Decimal、dataclasses、StrEnum、pytest、现有 S3 JSON artifact。

---

## 文件结构

- Create: `packages/quant/src/astraquant_quant/targets.py` — forecast、BaseTarget、T+1 target reconciliation。
- Create: `packages/quant/src/astraquant_quant/tplan.py` — 两种底仓做 T 计划草案。
- Modify: `packages/quant/src/astraquant_quant/strategy_layer.py` — 旧目标数量函数复用共同整数手计算。
- Create: `tools/research/plan_targets.py` — S3 证据状态与 canonical 目标/TPlan 报告。
- Create: `tests/quant/test_targets.py` — forecast 映射与 T+1 可达性。
- Create: `tests/quant/test_tplan.py` — 两种做 T 数量约束。
- Create: `tests/research/test_plan_targets.py` — 真实报告形态端到端输出。
- Modify: `docs/superpowers/plans/2026-08-11-strategy-effect-fast-lane.md` — 勾选 S4。
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md` — 记录 S4 结果与下一关键节点。

### Task 1: Forecast 转换为 BaseTarget

- [x] **Step 1: 写失败测试**

`tests/quant/test_targets.py` 先覆盖证据、成本和 no-trade band：

```python
target = build_base_target(
    ForecastInput(
        forecast_id="f-1",
        probability_up=Decimal("0.75"),
        expected_return=Decimal("0.01"),
        evidence_status=ForecastEvidenceStatus.VALIDATED,
    ),
    ForecastTargetPolicy(
        enter_probability=Decimal("0.55"),
        exit_probability=Decimal("0.45"),
        max_position_percent=Decimal("20"),
        round_trip_cost_rate=Decimal("0.0005"),
        lot_size=100,
    ),
    current_target_quantity=0,
    equity=Decimal("100000"),
    price=Decimal("10"),
)
assert target.target_quantity == 1000
assert target.reason is TargetReason.FORECAST_TARGET
```

证据不足、`abs(expected_return) <= cost`、`0.45 < p < 0.55` 均保持当前 target；validated 低概率且负 expected return 输出 target 0。

- [x] **Step 2: 验证 RED**

Run: `uv run pytest tests/quant/test_targets.py -q --basetemp .astraquant/test-tmp/s4-target-red`

Expected: import error，`astraquant_quant.targets` 尚不存在。

- [x] **Step 3: 最小实现**

在 `targets.py` 定义：

```python
class ForecastEvidenceStatus(StrEnum):
    VALIDATED = "VALIDATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"


class TargetReason(StrEnum):
    FORECAST_TARGET = "FORECAST_TARGET"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_NET_EDGE = "NO_NET_EDGE"
    NO_TRADE_BAND = "NO_TRADE_BAND"
```

实现 `build_base_target()`：高概率用 `(p-0.5)/0.5` 强度乘最大风险预算并向下取整；低概率目标 0；其余保持 current target。

- [x] **Step 4: 旧接口复用整数手 helper**

把 `strategy_layer.build_target_position()` 改为调用 `targets.quantity_for_budget()`，保持现有测试和 API 行为不变。

- [x] **Step 5: 验证 GREEN**

Run: `uv run pytest tests/quant/test_targets.py tests/quant/test_strategy_layer.py -q --basetemp .astraquant/test-tmp/s4-target-green`

Expected: PASS。

### Task 2: T+1 与活动委托下的目标可达性

- [ ] **Step 1: 写 T+1 失败测试**

```python
result = reconcile_target(
    target_quantity=0,
    position=PositionProjection(
        actual_quantity=2000,
        rule_sellable_quantity=1000,
        reserved_sell_quantity=0,
        working_buy_quantity=0,
        working_sell_quantity=0,
    ),
    cash_available=Decimal("0"),
    price=Decimal("10"),
    buy_cost_buffer_rate=Decimal("0.001"),
    lot_size=100,
)
assert result.proposed_side is OrderSide.SELL
assert result.proposed_quantity == 1000
assert result.reachable_quantity == 1000
assert result.unreachable_quantity == 1000
assert TargetReason.T1_FROZEN in result.reasons
```

- [ ] **Step 2: 验证 RED**

Run: `uv run pytest tests/quant/test_targets.py::test_t1_target_zero_only_sells_opening_quantity -q --basetemp .astraquant/test-tmp/s4-reconcile-red`

Expected: FAIL，API 尚不存在。

- [ ] **Step 3: 实现 reconciliation**

增加 `PositionProjection`、`TargetIntentKind`、`TargetReconciliation` 与 `reconcile_target()`。先用 working orders 计算 projected quantity，再分别按现金/可卖未预占量限制 BUY/SELL。

- [ ] **Step 4: 写活动单、预占、现金和风险测试**

覆盖：

```python
assert working_sell_result.proposed_quantity == 0
assert TargetReason.WORKING_ORDER_COVERS_DELTA in working_sell_result.reasons
assert cash_limited_result.reachable_quantity == 900
assert TargetReason.CASH_LIMIT in cash_limited_result.reasons
assert TargetReason.SELL_RESERVED in reserved_result.reasons
assert TargetReason.RISK_REDUCTION_PARTIAL in risk_result.reasons
```

- [ ] **Step 5: 验证 GREEN**

Run: `uv run pytest tests/quant/test_targets.py -q --basetemp .astraquant/test-tmp/s4-reconcile-green`

Expected: PASS。

### Task 3: 两种底仓做 T 计划草案

- [ ] **Step 1: 写失败测试**

`tests/quant/test_tplan.py`：

```python
draft = build_tplan(
    TPlanRequest(
        plan_id="t-1",
        plan_type=TPlanType.SELL_THEN_BUYBACK,
        base_target_quantity=2000,
        actual_quantity=2000,
        opening_sellable_quantity=1000,
        reserved_opening_quantity=200,
        requested_quantity=1000,
        cash_available=Decimal("0"),
        price=Decimal("10"),
        expected_incremental_return=Decimal("0.002"),
        round_trip_cost_rate=Decimal("0.0005"),
        evidence_status=ForecastEvidenceStatus.VALIDATED,
        lot_size=100,
    )
)
assert draft.planned_quantity == 800
assert draft.first_side is OrderSide.SELL
assert draft.second_side is OrderSide.BUY
```

再测 buy-first 同量预留 opening lots、现金只能支持 500 时 planned=500；证据不足、净优势不足、无可卖底仓都 HOLD。

- [ ] **Step 2: 验证 RED**

Run: `uv run pytest tests/quant/test_tplan.py -q --basetemp .astraquant/test-tmp/s4-tplan-red`

Expected: import error，模块尚不存在。

- [ ] **Step 3: 实现 `tplan.py`**

定义 `TPlanType`、`TPlanStatus`、`TPlanReason`、`TPlanRequest`、`TPlanDraft` 和 `build_tplan()`。planned quantity 始终不超过 `opening_sellable - reserved`；buy-first 再受现金和 lot size 限制，且 `opening_quantity_to_reserve == planned_quantity`。

- [ ] **Step 4: 验证 GREEN 与静态检查**

Run:

```powershell
uv run pytest tests/quant/test_targets.py tests/quant/test_tplan.py -q --basetemp .astraquant/test-tmp/s4-planners-green
uv run ruff check packages/quant/src/astraquant_quant/targets.py packages/quant/src/astraquant_quant/tplan.py tests/quant/test_targets.py tests/quant/test_tplan.py
uv run mypy packages/quant/src/astraquant_quant/targets.py packages/quant/src/astraquant_quant/tplan.py tests/quant/test_targets.py tests/quant/test_tplan.py
```

Expected: 全部通过。

### Task 4: S3 证据接入、可见报告和交付

- [ ] **Step 1: 写 CLI 失败测试**

`tests/research/test_plan_targets.py` 构造 S3 报告：ASTRA10 2 trades、Alpha158 1 trade。运行 CLI 后断言：

```python
assert result["models"]["ASTRA10_LIGHTGBM"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"
assert result["models"]["ASTRA10_LIGHTGBM"]["base_target"]["reason"] == "INSUFFICIENT_EVIDENCE"
assert result["canonical_t1"]["proposed_quantity"] == 1000
assert result["canonical_t1"]["unreachable_quantity"] == 1000
assert result["canonical_tplans"]["SELL_THEN_BUYBACK"]["planned_quantity"] == 800
```

- [ ] **Step 2: 实现 `plan_targets.py`**

CLI 接受 S3 JSON、`--minimum-evidence-trades`（默认 30）、`--current-target` 和 `--output`。交易数不足时保持 BaseTarget；同时输出固定 canonical validated target/T+1/TPlan 场景，供 UI/API 后续直接消费。

- [ ] **Step 3: 重复运行真实 S3 报告**

对 `.astraquant/research/s3-159516-20260811/executable-fee-config-a.json` 运行两次 CLI，Expected: SHA-256 一致；两个模型均为 `INSUFFICIENT_EVIDENCE/HOLD`。

- [ ] **Step 4: 运行目标、隔离 runner 和全量验证**

Run:

```powershell
uv run pytest tests/quant/test_targets.py tests/quant/test_tplan.py tests/quant/test_strategy_layer.py tests/research/test_plan_targets.py -q --basetemp .astraquant/test-tmp/s4-final
uv run --project runners/qlib --frozen pytest runners/qlib/tests -q --basetemp .astraquant/test-tmp/s4-qlib
pwsh -File scripts/verify.ps1 -Scope All
```

Expected: 全部通过。

- [ ] **Step 5: 更新进度、提交和推送**

勾选 fast lane S4 前两项；第三项 publication/model registry 保持延后。记录真实模型 HOLD、canonical T+1/TPlan 数量与报告 SHA，提交并推送当前分支。

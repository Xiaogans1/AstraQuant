# Phase 1b Task 3 Coverage and Formal Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用历史 lifecycle、精确交易时段和分页证据定义“应该存在的数据”，并用版本化正式质量策略决定 PASS、INCOMPLETE 或 QUARANTINE。

**Architecture:** `coverage.py` 只比较 sealed expectation 与 canonical logical intervals，不从当前 universe 推断历史。`calendars.py` 负责由明确 session segments 生成预期 bar interval；`quality.py` 保留 legacy gate，新增独立 formal gate，防止 v1 warning 语义污染 v3。分页/5000 行截断作为 coverage proof 的一等故障，而不是靠观察返回长度猜测。

**Tech Stack:** Python 3.12、frozen dataclasses、Decimal、SHA-256、pytest、Ruff、mypy。

---

### Task 1: 精确 session segment 与 bar expectation

**Files:**
- Modify: `packages/data/src/astraquant_data/calendars.py`
- Modify: `tests/data/test_calendars.py`

- [x] 写红灯：A 股上午/下午 segment 生成 240 个一分钟 interval，不跨午休；半日市只生成 120 个；naive/重叠 segment 拒绝。
- [x] 运行 `uv run pytest tests/data/test_calendars.py -q`，预期缺 `SessionSegment/expected_bar_intervals`。
- [x] 实现 frozen `SessionSegment`、`ExpectedBarInterval` 与 `expected_bar_intervals()`；要求 duration 可整除 interval，绑定 calendar snapshot digest。
- [x] 重跑 calendar tests 全绿。

### Task 2: 历史 lifecycle coverage 与分页故障

**Files:**
- Create: `packages/data/src/astraquant_data/coverage.py`
- Create: `tests/data/test_coverage.py`

- [x] 写红灯：listing 前/delisting 后不进入 denominator；当前仍上市 universe 不能替代 exact lifecycle；缺 calendar/lifecycle digest fail closed。
- [x] 写红灯：缺分钟 segment、unexpected interval、未 sealed page、单 chunk 静默命中 5000 上限分别产生稳定 reason；合法 revision 不重复计 coverage。
- [x] 运行目标测试，预期模块缺失。
- [x] 实现 `InstrumentLifecycle`、`CoverageRequirement`、`CaptureChunkCoverage`、`CoveragePlan`、`CoverageReport`、`evaluate_coverage()`。
- [x] 重跑 coverage/canonical tests 全绿。

### Task 3: 版本化 role-aware formal quality gate

**Files:**
- Modify: `packages/data/src/astraquant_data/quality.py`
- Modify: `tests/data/test_quality.py`

- [x] 写红灯：policy 必须含 version/source/hash；coverage error 或 schema/unit/OHLCV conflict 为 QUARANTINE；warning 只能 INCOMPLETE，绝不能 PASS。
- [x] 写红灯：RAW_EXECUTION 必须 exact complete coverage；RESEARCH 可按冻结阈值接受显式 gap，但结果仍披露 issue，阈值变化必须改变 policy digest。
- [x] 实现 `DataRole`、`FormalGateState`、`FormalQualityPolicy`、`FormalQualityIssue/Report`、`evaluate_formal_quality()`；不改 legacy `QualityReport` wire format。
- [x] 运行 quality/manifest/parquet/evidence tests，确认 legacy 兼容。
- [x] 运行 Ruff、mypy、`scripts/verify.ps1 -Scope All`；更新路线图，原子提交并推送。

## Self-review

- Spec coverage：历史 lifecycle denominator、午休/半日市、分钟缺段、5000 静默截断、分页 seal、revision 去重、版本化阈值、warning 非 PASS 均有红灯。
- Boundary：公司行动、status/universe 数据本身由 Phase 1c reference capture 提供；本 Task 只要求其 lifecycle evidence digest，不伪造 reference 数据。
- Compatibility：legacy `evaluate_bars/QualityReport` 不改 schema；v3 formal gate 使用独立类型。

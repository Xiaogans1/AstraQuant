# Phase 1b Task 2 Temporal Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development task-by-task.

**Goal:** 为 canonical observation 实现可解释、fail-closed 的历史/在线可见性和版本选择，避免修订值穿越旧决策。

**Architecture:** `temporal.py` 只消费已验证的 `CanonicalBarObservation`。策略负责派生 `visible_time`，版本选择另由 `RevisionPolicy` 控制，并强制 exact `data_vintage_cutoff`；AS_DELIVERED 的报告必须标记 nominal replay，不能冒充 PIT_STRICT。

**Tech Stack:** Python 3.12、frozen dataclasses、StrEnum、pytest、Ruff、mypy。

---

### Task 1: 冻结策略与 reasoned decision

**Files:**
- Create: `packages/data/src/astraquant_data/temporal.py`
- Create: `tests/data/test_temporal_visibility.py`

- [x] 红灯覆盖 2010 bar 在 2026 首收：AS_DELIVERED 在 nominal time 可见，PIT_STRICT 在 proven time 前不可见。
- [x] 红灯覆盖 PAPER/MIRROR/LIVE 共用 `max(source_available, observed_received, source_revision)`，边界前后精确判断。
- [x] 实现 `VintageMode`、`RevisionPolicy`、policy classes、`VisibilityDecision`、`visible_at()`、`assess_visibility()`、`is_visible()`。

### Task 2: 冻结 revision selection 与 disclosure

**Files:**
- Modify: `packages/data/src/astraquant_data/temporal.py`
- Modify: `tests/data/test_temporal_visibility.py`

- [x] 红灯覆盖旧 decision 不被新 revision 改写、cutoff 后记录不可入选、EXACT_VINTAGE 不存在时 reasoned rejection。
- [x] 红灯覆盖 AS_DELIVERED report 必须包含 cutoff/占比/`NOMINAL_ONLY`，且禁止声明 PIT_STRICT；严格 PIT 区分 authoritative 与 observed proof。
- [x] 实现 `select_visible_vintage()`、`build_visibility_report()` 及 frozen report contract。
- [x] 运行目标测试、legacy data tests、Ruff、mypy 和 `scripts/verify.ps1 -Scope All`。
- [x] 更新路线图 Task 2，提交并推送 `feat(data): 实现版本化时间可见性`。

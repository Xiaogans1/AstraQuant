# Phase 1b Task 1 Canonical Observation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立不可变、可哈希、可 Arrow 序列化的 canonical bar observation，完整保留 interval、三时钟、vintage proof 与 capture-row lineage。

**Architecture:** 旧 `Bar` 继续服务 legacy/UI，不原地改写其语义；v3 使用独立 `CanonicalBarObservation`。调用方必须提供 exact calendar snapshot 推导的 `ObservationInterval`，normalizer 只验证而不猜交易日历；所有价值摘要、vintage identity 与 Arrow metadata 都由 canonical serialization 生成。

**Tech Stack:** Python 3.12、frozen dataclasses、Decimal、SHA-256、PyArrow、pytest、Ruff、mypy。

---

### Task 1: 冻结 domain 时间与 vintage 枚举

**Files:**
- Modify: `packages/domain/src/astraquant_domain/market_data.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`
- Modify: `tests/domain/test_market_data.py`

- [x] **Step 1: 写红灯测试**：实例化 `ObservationInterval`，要求 `interval_start < event_time == interval_end`、时间 aware、`calendar_snapshot_id` 为非 sentinel SHA-256；验证 `VintageKind` 与 `AvailabilityBasis` 枚举值稳定。

```python
interval = ObservationInterval(
    interval_start=OPEN,
    interval_end=CLOSE,
    event_time=CLOSE,
    calendar_snapshot_id=DIGEST,
)
assert interval.event_time == interval.interval_end
```

- [x] **Step 2: 运行红灯**：`uv run pytest tests/domain/test_market_data.py -q`；预期 import `ObservationInterval` 失败。
- [x] **Step 3: 最小实现**：增加 `VintageKind(SOURCE_CERTIFIED, SOURCE_VERSIONED, LOCALLY_OBSERVED, AS_DELIVERED_UNVERSIONED)`、`AvailabilityBasis` 与 frozen `ObservationInterval`；不修改 legacy `Bar/Tick` 字段。
- [x] **Step 4: 运行绿灯**：domain tests、Ruff、mypy 全绿。

### Task 2: Canonical bar 与 normalization 不变量

**Files:**
- Create: `packages/data/src/astraquant_data/canonical.py`
- Create: `tests/data/test_canonical_schema.py`

- [x] **Step 1: 写 normalization 红灯**：构造 2010 日线在 2026 首次收到的输入，断言 `source_available_time << observed_received_time` 合法；`event_time` 固定为 interval close；value/vintage digest 稳定；capture/chunk/row lineage 完整。

```python
bar = normalize_bar(input_row, interval=exact_interval, lineage=lineage)
assert bar.source_available_time.year == 2010
assert bar.observed_received_time.year == 2026
assert bar.event_time == exact_interval.interval_end
assert bar.value_hash.startswith("sha256:")
```

- [x] **Step 2: 写 quarantine 红灯**：raw `Adjustment.FORWARD/BACKWARD`、未知单位、naive 时间、`recorded_time < observed_received_time`、缺 revision proof、vintage proof 与 kind 不一致全部抛 `CanonicalQuarantineError`。
- [x] **Step 3: 写 duplicate 红灯**：同 canonical key/vintage id 的不同 value 必须 quarantine；相同正文幂等去重；合法 superseding vintage 必须引用旧 vintage id。
- [x] **Step 4: 运行红灯**：`uv run pytest tests/data/test_canonical_schema.py -q`；预期缺少 `astraquant_data.canonical`。
- [x] **Step 5: 最小实现**：增加 `CaptureRowLineage`、`CanonicalBarInput`、`CanonicalBarObservation`、`normalize_bar()`、`validate_canonical_observations()`；摘要使用 `canonical_json_bytes`，Decimal 以字符串编码。
- [x] **Step 6: 运行绿灯**：canonical tests 全绿。

### Task 3: Arrow schema v2 与精确往返

**Files:**
- Create: `packages/data/src/astraquant_data/canonical_schema.py`
- Modify: `packages/data/src/astraquant_data/arrow_schema.py`
- Modify: `tests/data/test_canonical_schema.py`

- [x] **Step 1: 写 Arrow 红灯**：schema 必须含 interval、三时钟、revision、vintage、availability、calendar、lineage 和精确 Decimal 字段；metadata 固定 `astraquant.canonical-bar/v1`；nullable 只允许 source revision fields、turnover/open-interest/settlement、supersedes。
- [x] **Step 2: 写 round-trip 红灯**：`canonical_bars_to_table()`/`table_to_canonical_bars()` 往返后对象与 digest 不变；字段/metadata/scale 漂移拒绝。
- [x] **Step 3: 运行红灯**：目标 tests 预期缺 schema/serializer。
- [x] **Step 4: 最小实现**：使用 UTC microsecond timestamp、decimal128 精度与 schema metadata；`arrow_schema.py` 只 re-export v3 schema，不改变 legacy `BAR_SCHEMA`。
- [x] **Step 5: 完整验证**：运行 domain/canonical/legacy Arrow tests、Ruff format/check、mypy、`scripts/verify.ps1 -Scope All`。
- [x] **Step 6: 更新 Phase 1b Task 1 checkbox 并提交**：`git commit -m "feat(data): 建立规范市场数据契约"`，推送并确认远端 CI。

## Self-review

- Spec coverage：三时钟分离、historical backfill、exact interval/calendar lineage、raw NONE adjustment、revision/vintage proof、capture row lineage、duplicate conflict 与 Arrow 精度均有红灯。
- Scope：本 Task 不实现 visible-time policy、coverage、publication 或 snapshot v2；这些分别留给 Phase 1b Tasks 2–5。
- Compatibility：legacy `Bar/BAR_SCHEMA` 不改字段，避免把 v3 时间语义偷偷注入旧 UI/research 路径。

# Phase 1a Task 1 Provider Qualification Contracts 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立不可变、可哈希、按 endpoint/capability 独立审批的 ProviderIdentity、QualificationReport 与 approval/revocation timeline，使任何 build、权限或 schema 变化都不能沿用旧批准。

**Architecture:** `provider_identity.py` 只负责供应商调用面的稳定身份；Eastmoney vendor、gm SDK interface 和 NDJSON transport 永远分字段。`provider_qualification.py` 将 probe evidence、必测能力结果、人工 approval 和后续 revocation 建模为不可变 value objects；报告全绿只表示 `approvable`，不会自动变为 APPROVED。普通 revoke/supersede 只阻止其 effective time 后的 capture，`RETROACTIVE_COMPROMISE` 才隔离历史。

**Tech Stack:** Python 3.12、frozen dataclasses、StrEnum、SHA-256 canonical JSON、pytest、Ruff、mypy。

---

## Task 1: ProviderIdentity 精确身份与稳定 digest

**Files:**

- Create: `packages/data/src/astraquant_data/provider_identity.py`
- Create: `tests/data/test_provider_qualification.py`

- [ ] **Step 1: 写 identity 字段分离红灯**

测试公开 API：

```python
identity = ProviderIdentity(
    vendor="eastmoney",
    product="eastmoney-terminal",
    endpoint="market.daily-bars",
    capability=ProviderCapability.DAILY_BARS,
    interface="gm_python_sdk",
    interface_build="3.0.176",
    transport=ProviderTransport.NDJSON_BRIDGE,
    permission_tier="level1-history",
    schema_fingerprint=_digest("1"),
)
assert identity.vendor == "eastmoney"
assert identity.interface == "gm_python_sdk"
assert identity.transport is ProviderTransport.NDJSON_BRIDGE
```

`vendor="Eastmoney/GM"`、前后空白、空 endpoint、sentinel/非 SHA-256 schema fingerprint 全部 `ValueError`。

- [ ] **Step 2: 写 capability 与 identity drift 红灯**

以 `dataclasses.replace` 分别改变 endpoint、capability、interface_build、permission_tier、schema_fingerprint，断言每次 `identity_digest` 都变化；同 vendor 的 `DAILY_BARS`、`MINUTE_BARS`、`CORPORATE_ACTIONS`、`INSTRUMENT_STATUS`、`L2_QUOTES` 五个对象 digest 两两不同。

- [ ] **Step 3: 运行红灯**

Run: `uv run pytest tests/data/test_provider_qualification.py -q --basetemp .astraquant/test-tmp/phase1a-identity-red`

Expected: FAIL，`astraquant_data.provider_identity` 尚不存在。

- [ ] **Step 4: 实现最小 identity contract**

创建：

```python
class ProviderCapability(StrEnum):
    DAILY_BARS = "DAILY_BARS"
    MINUTE_BARS = "MINUTE_BARS"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    INSTRUMENT_STATUS = "INSTRUMENT_STATUS"
    L2_QUOTES = "L2_QUOTES"

class ProviderTransport(StrEnum):
    NDJSON_BRIDGE = "NDJSON_BRIDGE"
    DIRECT_SDK = "DIRECT_SDK"
    HTTP = "HTTP"

@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    vendor: str
    product: str
    endpoint: str
    capability: ProviderCapability
    interface: str
    interface_build: str
    transport: ProviderTransport
    permission_tier: str
    schema_fingerprint: str

    def to_dict(self) -> dict[str, str]: ...
    @property
    def identity_digest(self) -> str: ...
```

vendor/interface/permission 使用 lowercase canonical slug；product/endpoint/build 要求非空且前后无空白。digest 使用 UTF-8、`sort_keys=True`、无空格 canonical JSON；复用 `astraquant_domain.run_manifest.validate_digest` 拒绝 sentinel。

- [ ] **Step 5: 验证并提交**

Run: `uv run pytest tests/data/test_provider_qualification.py -q --basetemp .astraquant/test-tmp/phase1a-identity-green`

Run: `uv run ruff check packages/data/src/astraquant_data/provider_identity.py tests/data/test_provider_qualification.py`

Run: `uv run mypy packages/data/src/astraquant_data/provider_identity.py tests/data/test_provider_qualification.py`

Commit: `git commit -m "feat(data): 建立真实数据源精确身份"`

## Task 2: QualificationReport 完整性与稳定 digest

**Files:**

- Create: `packages/data/src/astraquant_data/provider_qualification.py`
- Modify: `tests/data/test_provider_qualification.py`

- [ ] **Step 1: 写 report required evidence 红灯**

定义并测试：

```python
ProbeEvidence(
    request_digest=_digest("2"),
    raw_response_digest=_digest("3"),
    observed_at=NOW,
)
QualificationCoverage(
    start=date(2020, 1, 1),
    end=date(2026, 8, 8),
    instruments=("600000.SSE", "000001.SZSE"),
    delisted_instruments=("600001.SSE",),
)
CapabilityResult(
    check=QualificationCheck.PAGINATION_AND_TRUNCATION,
    status=CheckStatus.PASS,
    evidence_digest=_digest("4"),
)
```

缺 probe、空 coverage、无退市标的、naive datetime、重复 check、缺任一 required check 均不能 `approvable`；digest 字段不合法直接 `ValueError`。

- [ ] **Step 2: 固定必测矩阵**

`QualificationCheck` 精确包含 `COVERAGE`、`DELISTED_INSTRUMENT`、`ADJUST_AND_UNITS`、`PAGINATION_AND_TRUNCATION`、`REVISION_BEHAVIOR`、`RATE_LIMIT`、`SCHEMA_EVOLUTION`。`CheckStatus` 为 `PASS/FAIL/NOT_TESTED`；只有七项各出现一次且全 PASS 才 `report.approvable is True`。

- [ ] **Step 3: 写 canonical digest 红灯**

相同 probes/results/instruments 输入顺序不同必须得到同一 `report_digest`；改变 raw response、coverage、adjust modes、units、任一 result evidence 或 identity 必须改变 digest。report schema 固定 `astraquant.provider-qualification-report/v1`。

- [ ] **Step 4: 运行红灯**

Run: `uv run pytest tests/data/test_provider_qualification.py -q --basetemp .astraquant/test-tmp/phase1a-report-red`

Expected: FAIL，qualification types 尚不存在。

- [ ] **Step 5: 实现 report value objects**

创建 frozen `ProbeEvidence`、`QualificationCoverage`、`CapabilityResult` 与 `QualificationReport`。Report fields 精确为 `identity`、`probes`、`coverage`、`results`、`adjust_modes`、`units`、`observed_at`、`schema_version`；构造时 tuple 化并按 identity 排序、校验 UTC aware datetime 与 check uniqueness。`report_digest` 对完整 `to_dict()` 做 canonical SHA-256；`approvable` 只计算完整性，不改变 state。

- [ ] **Step 6: 验证并提交**

Run: `uv run pytest tests/data/test_provider_qualification.py -q --basetemp .astraquant/test-tmp/phase1a-report-green`

Commit: `git commit -m "feat(data): 固化数据源资格报告"`

## Task 3: 人工 approval 与按时间 revocation

**Files:**

- Modify: `packages/data/src/astraquant_data/provider_qualification.py`
- Modify: `tests/data/test_provider_qualification.py`

- [ ] **Step 1: 写默认 fail-closed 与人工批准红灯**

`ProviderQualificationTimeline(identity, report)` 默认 `state is QualificationState.UNQUALIFIED`，即使 report 全 PASS 也 `is_approved_for(identity, captured_at=NOW) is False`。仅 `timeline.approve(reviewer="reviewer-1", policy_version="provider-policy/v1", effective_at=NOW)` 返回新 timeline，旧对象不变；FAIL/NOT_TESTED report 调 approve 抛 `QualificationError("report is not approvable")`。

- [ ] **Step 2: 写 identity binding 红灯**

批准后原 identity 在 effective time 起可用；用 `replace` 改 interface_build、permission_tier 或 schema_fingerprint 后 `is_approved_for` 必须 False。Approval 固定 `identity_digest`、`report_digest`、reviewer、policy version、effective_at 与稳定 `approval_id`，不能由调用方传入 ID。

- [ ] **Step 3: 写普通 revoke/supersede 时间语义红灯**

`timeline.revoke(kind=REVOKED|SUPERSEDED, effective_at=T1, reviewer=..., reason_digest=...)` 返回新 timeline：`captured_at < T1` 仍 true，`captured_at >= T1` false；撤销前、重复同 kind/effective 或 effective_at 早于 approval 均拒绝。当前 state 为 `REVOKED`。

- [ ] **Step 4: 写 retroactive compromise 红灯**

`RETROACTIVE_COMPROMISE` 一旦记录，任何 capture_time（包括 approval 后、compromise effective time 前）都 false，state=`COMPROMISED`；不能靠后续普通 approve 覆盖同 identity/report 的 compromise。

- [ ] **Step 5: 运行红灯**

Run: `uv run pytest tests/data/test_provider_qualification.py -q --basetemp .astraquant/test-tmp/phase1a-timeline-red`

- [ ] **Step 6: 实现 timeline**

新增 `QualificationState(UNQUALIFIED, APPROVED, REVOKED, COMPROMISED)`、`RevocationKind(SUPERSEDED, REVOKED, RETROACTIVE_COMPROMISE)`、frozen `ProviderApproval`、`ProviderRevocation`、`ProviderQualificationTimeline`。所有 mutation method 通过 `dataclasses.replace` 返回新对象；所有 datetime 强制 timezone-aware 并 canonical UTC；`is_approved_for(identity, captured_at)` 先做 exact identity digest binding，再按 approval/revocation effective time判定。

- [ ] **Step 7: 验证完整 Task 1**

Run: `uv run pytest tests/data/test_provider_qualification.py tests/data/test_evidence_gate.py tests/domain/test_run_manifest.py -q --basetemp .astraquant/test-tmp/phase1a-task1-green`

Run: `uv run ruff check packages/data/src tests/data/test_provider_qualification.py`

Run: `uv run ruff format --check packages/data/src tests/data/test_provider_qualification.py`

Run: `uv run mypy packages/data/src tests/data/test_provider_qualification.py`

- [ ] **Step 8: 更新路线图、范围检查与 GitHub 交付**

勾选 Phase 1a roadmap Task 1；检查 `git diff --name-status origin/codex/quant-core-v3-phase0-task7...HEAD` 只含 identity/qualification/tests/micro plan/roadmap。提交：`git commit -m "feat(data): 建立真实数据源资格契约"`，推送 `codex/quant-core-v3-phase1a-task1`，确认最终远端 SHA 与 CI success/annotations=0；不创建或合并 PR。

## Self-review

- Spec coverage: endpoint/capability/build/permission/schema identity、probe/raw digests、coverage/退市/adjust/units/pagination/revision/rate/schema、人工批准与三类撤销全部有字段和测试。
- Evidence honesty: 全 PASS 只产生 approvable report，不自动 APPROVED；本 Task 不调用 Eastmoney、不创建 capture、不伪造真实 evidence。
- Time semantics: ordinary revoke/supersede 保留 effective time 前历史；只有 RETROACTIVE_COMPROMISE 全历史隔离。
- Type consistency: identity/report/approval/revocation digest 都是 canonical non-sentinel SHA-256；所有时间 UTC-aware；所有 collections immutable tuples。
- Scope: 无数据库、API route、CLI、raw payload 或凭据；这些留在 Phase 1a Tasks 2–4。

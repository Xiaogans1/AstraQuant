# Phase 0 Task 2 Evidence Gate and RunManifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立共享、不可变、fail-closed 的 `RunManifest` 与递归证据准入门，使任何 `FORMAL` 运行只能消费精确 pin、sealed、祖先闭合且审批有效的真实 API/官方规则证据。

**Architecture:** `astraquant_domain.run_manifest` 只负责跨运行时共享的 run identity、canonical serialization、seal/runnable 语义；`astraquant_data.evidence` 负责数据证据分类、来源角色、递归祖先验证与审批集合。旧 `SnapshotManifest schema_version=1` 保持只读兼容，但通过显式 adapter 永久映射为 `LEGACY_UNVERIFIED`；路径、文件名、provider 字符串和重新计算 hash 都不参与升级分类。

**Tech Stack:** Python 3.12、frozen dataclasses、`StrEnum`、SHA-256 canonical JSON、pytest、Ruff、mypy、PowerShell shared verifier。

---

## File map

- Create `packages/domain/src/astraquant_domain/run_manifest.py`: `RunClass`、`RunManifestState`、canonical serializer、digest validator、immutable `RunManifest`。
- Modify `packages/domain/src/astraquant_domain/__init__.py`: 导出共享 run contract。
- Create `tests/domain/test_run_manifest.py`: 决定性、seal、不可变和非法 digest 的契约测试。
- Create `packages/data/src/astraquant_data/evidence.py`: evidence enums/value objects、legacy adapter、递归 `EvidenceGate`。
- Modify `packages/data/src/astraquant_data/manifests.py`: 把现有 schema v1 snapshot 显式投影为 legacy evidence。
- Create `tests/data/test_evidence_gate.py`: formal admission 的允许/拒绝矩阵、cycle/collision、legacy snapshot 集成测试。
- Modify `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-0-repository-ci-legacy.md`: 只在真实验收通过后勾选 Task 2。

## Task 1: Shared immutable RunManifest

**Files:**

- Create: `tests/domain/test_run_manifest.py`
- Create: `packages/domain/src/astraquant_domain/run_manifest.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`

- [ ] **Step 1: 写 canonical identity 与 seal 红灯测试**

```python
def test_sealed_manifest_is_canonical_and_runnable() -> None:
    first = _draft(inputs={"bars": DIGEST_A, "rules": DIGEST_B}).seal()
    second = _draft(inputs={"rules": DIGEST_B, "bars": DIGEST_A}).seal()
    assert first.to_canonical_bytes() == second.to_canonical_bytes()
    assert first.manifest_digest == second.manifest_digest
    first.assert_runnable()


def test_draft_manifest_cannot_start_a_run() -> None:
    with pytest.raises(UnsealedRunManifestError, match="SEALED"):
        _draft().assert_runnable()
```

- [ ] **Step 2: 运行测试并确认因模块缺失而失败**

Run: `uv run pytest tests/domain/test_run_manifest.py -q`

Expected: collection FAIL，`ModuleNotFoundError: astraquant_domain.run_manifest`。

- [ ] **Step 3: 实现最小 immutable contract**

```python
class RunClass(StrEnum):
    FORMAL = "FORMAL"
    EXPLORATORY = "EXPLORATORY"
    TEST = "TEST"


class RunManifestState(StrEnum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_class: RunClass
    code_digest: str
    environment_digest: str
    input_digests: Mapping[str, str]
    config_digest: str
    randomness_digest: str
    event_order_policy_digest: str
    matcher_policy_digest: str
    vintage_policy_digest: str
    policy_digests: Mapping[str, str]
    state: RunManifestState = RunManifestState.DRAFT
    schema_version: str = "astraquant.run-manifest/v1"

    def seal(self) -> "RunManifest":
        if self.state is RunManifestState.SEALED:
            return self
        return replace(self, state=RunManifestState.SEALED)

    def assert_runnable(self) -> None:
        if self.state is not RunManifestState.SEALED:
            raise UnsealedRunManifestError("run manifest must be SEALED")

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())
```

所有 mapping 在 `__post_init__` 中复制、排序并转成 `MappingProxyType`；所有 digest 必须是非全零的 `sha256:<64 lowercase hex>`。`seal()` 返回新对象，不修改 draft。

- [ ] **Step 4: 增加不可变、字段敏感和 fail-closed 边界测试**

```python
def test_sealed_manifest_rejects_mutation() -> None:
    sealed = _draft().seal()
    with pytest.raises(FrozenInstanceError):
        sealed.run_class = RunClass.TEST  # type: ignore[misc]
    with pytest.raises(TypeError):
        sealed.input_digests["bars"] = DIGEST_B  # type: ignore[index]


@pytest.mark.parametrize("field", MANIFEST_IDENTITY_FIELDS)
def test_each_identity_field_changes_manifest_digest(field: str) -> None:
    assert _draft().seal().manifest_digest != _draft(**{field: replacement(field)}).seal().manifest_digest
```

- [ ] **Step 5: 运行 domain tests、Ruff 与 mypy**

Run:

```powershell
uv run pytest tests/domain/test_run_manifest.py tests/domain/test_features.py -q
uv run ruff check packages/domain/src/astraquant_domain tests/domain
uv run ruff format --check packages/domain/src/astraquant_domain tests/domain
uv run mypy packages/domain/src/astraquant_domain tests/domain
```

Expected: 全部 exit 0，且新测试无 warning。

- [ ] **Step 6: 提交 domain contract**

```powershell
git add packages/domain/src/astraquant_domain/run_manifest.py packages/domain/src/astraquant_domain/__init__.py tests/domain/test_run_manifest.py
git commit -m "feat(domain): 建立不可变运行清单契约"
```

## Task 2: Typed evidence and recursive formal admission

**Files:**

- Create: `tests/data/test_evidence_gate.py`
- Create: `packages/data/src/astraquant_data/evidence.py`

- [ ] **Step 1: 写 formal allow/deny 矩阵红灯测试**

```python
def test_derived_real_api_requires_closed_approved_ancestry() -> None:
    raw = EvidenceRef.real_api_market(artifact_id="capture-1", approval_id="qa-1", digest=DIGEST_A)
    feature = EvidenceRef.derived(artifact_id="feature-1", digest=DIGEST_B, parents=(raw,))
    result = EvidenceGate(approved_authority_ids={"qa-1"}).admit(RunClass.FORMAL, roots=(feature,))
    assert result.root_artifact_ids == ("feature-1",)


@pytest.mark.parametrize("bad", [EvidenceRef.fixture("renamed-real-api.parquet", DIGEST_A), EvidenceRef.exploratory("akshare", DIGEST_A), EvidenceRef.legacy("old", DIGEST_A)])
def test_nonformal_evidence_cannot_enter_formal_even_when_renamed(bad: EvidenceRef) -> None:
    with pytest.raises(FormalAdmissionError):
        EvidenceGate().admit(RunClass.FORMAL, roots=(bad,))
```

- [ ] **Step 2: 运行测试并确认因 evidence 模块缺失而失败**

Run: `uv run pytest tests/data/test_evidence_gate.py -q`

Expected: collection FAIL，`ModuleNotFoundError: astraquant_data.evidence`。

- [ ] **Step 3: 实现 evidence value objects 与递归 gate**

```python
class EvidenceClass(StrEnum):
    REAL_API_MARKET = "REAL_API_MARKET"
    REAL_API_REFERENCE = "REAL_API_REFERENCE"
    REAL_API_BROKER = "REAL_API_BROKER"
    DERIVED_REAL_API = "DERIVED_REAL_API"
    OFFICIAL_RULE = "OFFICIAL_RULE"
    TEST_ONLY = "TEST_ONLY"
    EXPLORATORY_ONLY = "EXPLORATORY_ONLY"
    LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    artifact_id: str | None
    evidence_class: EvidenceClass
    role: EvidenceRole
    content_digest: str
    parents: tuple["EvidenceRef", ...] = ()
    approval_id: str | None = None
    sealed: bool = True
    manifest_schema_version: int = 2


class EvidenceGate:
    def admit(self, run_class: RunClass, roots: tuple[EvidenceRef, ...]) -> AdmissionResult:
        if not roots:
            raise FormalAdmissionError("at least one evidence root is required")
        seen: dict[str, tuple[object, ...]] = {}
        for root in roots:
            self._visit(root, run_class=run_class, path=(), seen=seen)
        return AdmissionResult(
            root_artifact_ids=tuple(sorted(root.require_exact_id() for root in roots)),
            evidence_digests=tuple(sorted({item.content_digest for item in self._walk(roots)})),
        )
```

FORMAL 递归规则：root 必须 exact ID、sealed、schema v2；真实 API/官方规则必须引用当前 gate 的 approved authority ID；derived 必须至少有一个非规则数据祖先，全部父级 formal eligible；unknown enum/schema、空父级、循环、同 artifact ID 不同 fingerprint、TEST/EXPLORATORY/LEGACY 全部拒绝。非 FORMAL 仍验证结构和 cycle，但允许非正式 evidence。

- [ ] **Step 4: 增加循环、碰撞、未 pin、未审批和角色错误红灯测试**

```python
def test_formal_rejects_unpinned_root() -> None:
    root = EvidenceRef.derived(artifact_id=None, digest=DIGEST_B, parents=(_approved_raw(),))
    with pytest.raises(FormalAdmissionError, match="exact"):
        _formal_gate().admit(RunClass.FORMAL, roots=(root,))


def test_formal_rejects_unknown_or_v1_schema() -> None:
    root = replace(_approved_raw(), manifest_schema_version=1)
    with pytest.raises(FormalAdmissionError, match="schema"):
        _formal_gate().admit(RunClass.FORMAL, roots=(root,))


def test_formal_rejects_unapproved_real_api() -> None:
    with pytest.raises(FormalAdmissionError, match="approval"):
        EvidenceGate().admit(RunClass.FORMAL, roots=(_approved_raw(),))


def test_gate_rejects_cycle() -> None:
    root = EvidenceRef.derived(artifact_id="feature-1", digest=DIGEST_B, parents=(_approved_raw(),))
    object.__setattr__(root, "parents", (root,))
    with pytest.raises(EvidenceCycleError, match="feature-1"):
        _formal_gate().admit(RunClass.FORMAL, roots=(root,))


def test_gate_rejects_same_artifact_id_with_different_digest() -> None:
    first = _approved_raw(artifact_id="capture-1", digest=DIGEST_A)
    second = _approved_raw(artifact_id="capture-1", digest=DIGEST_B)
    root = EvidenceRef.derived(artifact_id="feature-1", digest=DIGEST_C, parents=(first, second))
    with pytest.raises(EvidenceCollisionError, match="capture-1"):
        _formal_gate().admit(RunClass.FORMAL, roots=(root,))


def test_rule_only_parents_cannot_claim_derived_market_evidence() -> None:
    rule = EvidenceRef.official_rule(artifact_id="rule-1", approval_id="rule-approval", digest=DIGEST_A)
    root = EvidenceRef.derived(artifact_id="feature-1", digest=DIGEST_B, parents=(rule,))
    with pytest.raises(FormalAdmissionError, match="data ancestor"):
        EvidenceGate(approved_authority_ids={"rule-approval"}).admit(RunClass.FORMAL, roots=(root,))
```

- [ ] **Step 5: 运行 evidence tests、Ruff 与 mypy**

Run:

```powershell
uv run pytest tests/data/test_evidence_gate.py -q
uv run ruff check packages/data/src/astraquant_data/evidence.py tests/data/test_evidence_gate.py
uv run ruff format --check packages/data/src/astraquant_data/evidence.py tests/data/test_evidence_gate.py
uv run mypy packages/data/src/astraquant_data/evidence.py tests/data/test_evidence_gate.py
```

Expected: 全部 exit 0。

- [ ] **Step 6: 提交 recursive gate**

```powershell
git add packages/data/src/astraquant_data/evidence.py tests/data/test_evidence_gate.py
git commit -m "feat(data): 建立正式证据递归准入门"
```

## Task 3: Legacy manifest adapter and compatibility proof

**Files:**

- Modify: `packages/data/src/astraquant_data/manifests.py`
- Modify: `tests/data/test_evidence_gate.py`
- Test: `tests/data/test_feature_snapshots.py`

- [ ] **Step 1: 写 SnapshotManifest v1 永久降级红灯测试**

```python
def test_snapshot_manifest_v1_is_always_legacy_unverified(tmp_path: Path) -> None:
    manifest = _legacy_snapshot_manifest()
    evidence = manifest.to_evidence_ref()
    assert evidence.evidence_class is EvidenceClass.LEGACY_UNVERIFIED
    with pytest.raises(FormalAdmissionError, match="LEGACY_UNVERIFIED"):
        EvidenceGate().admit(RunClass.FORMAL, roots=(evidence,))
```

- [ ] **Step 2: 运行单测并确认缺少 adapter**

Run: `uv run pytest tests/data/test_evidence_gate.py::test_snapshot_manifest_v1_is_always_legacy_unverified -q`

Expected: FAIL，`SnapshotManifest` 没有 `to_evidence_ref`。

- [ ] **Step 3: 实现显式 v1 adapter**

```python
def to_evidence_ref(self) -> EvidenceRef:
    return EvidenceRef.legacy(
        artifact_id=self.snapshot_id,
        digest=f"sha256:{self.snapshot_id}",
        manifest_schema_version=self.schema_version,
    )
```

该 adapter 不读取 `provider`、路径或文件名来决定等级；即使 provider 字符串改成 Eastmoney、文件复制到 formal root 或 hash 重算，schema v1 仍为 `LEGACY_UNVERIFIED`。

- [ ] **Step 4: 运行兼容测试**

Run:

```powershell
uv run pytest tests/data/test_evidence_gate.py tests/data/test_feature_snapshots.py tests/data/test_parquet_store.py tests/data/test_query.py -q
```

Expected: 全部通过；旧 snapshot/feature 读写保持兼容，但不能进入 FORMAL。

- [ ] **Step 5: 提交 legacy adapter**

```powershell
git add packages/data/src/astraquant_data/manifests.py tests/data/test_evidence_gate.py
git commit -m "fix(data): 将旧快照永久标记为未验证证据"
```

## Task 4: Phase verification and GitHub delivery

**Files:**

- Modify: `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-0-repository-ci-legacy.md`
- Modify: `docs/superpowers/plans/2026-08-10-phase0-task2-evidence-run-manifest.md`

- [ ] **Step 1: 运行 Task 2 精确验收**

Run:

```powershell
$runId = [guid]::NewGuid().ToString("n")
$root = ".astraquant/test-logs/$runId"
New-Item -ItemType Directory -Path $root | Out-Null
uv run pytest tests/domain/test_run_manifest.py tests/data/test_evidence_gate.py tests/data/test_feature_snapshots.py -q --basetemp "$root/pytest"
uv run ruff check packages/domain/src packages/data/src tests/domain tests/data
uv run ruff format --check packages/domain/src packages/data/src tests/domain tests/data
uv run mypy packages/domain/src packages/data/src tests/domain tests/data
```

Expected: 全部 exit 0。

- [ ] **Step 2: 运行完整共享门**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Scope All`

Expected: Python、Desktop、Rust、repository policy 全部通过，验证日志只写 ignored `.astraquant/test-logs/{run_id}`。

- [ ] **Step 3: 检查范围并勾选 roadmap Task 2**

Run:

```powershell
git diff --check
git diff --name-status codex/quant-core-v3-phase0-task1...HEAD
git status --short
```

Expected: 只包含本微计划、run/evidence contract、对应 tests、legacy adapter 和 roadmap checkbox。

- [ ] **Step 4: 提交验收证据并推送**

```powershell
git add docs/superpowers/plans/2026-08-10-quant-core-v3-phase-0-repository-ci-legacy.md docs/superpowers/plans/2026-08-10-phase0-task2-evidence-run-manifest.md
git commit -m "docs: 记录Phase 0证据门完成证据"
git push -u origin codex/quant-core-v3-phase0-task2
```

- [ ] **Step 5: 等待最终 HEAD 的 GitHub Actions**

Expected: 远端 branch HEAD 与本地一致，GitHub Actions conclusion=`success`、annotations=0；不创建或合并 PR。

## Self-review

- Spec coverage: 覆盖 design §6.1 的 evidence classes/递归 ancestry/approval/fail-closed、§6.3 的 exact pin/sealed/legacy v1，以及 §14 的 shared `RunManifest` identity/seal/determinism。
- Scope boundary: Phase 0 只建立 contract 和旧数据降级；ProviderQualification 的真实审批状态机、snapshot v2 publication ledger 与 FormalAdmissionService 分别留在 Phase 1a、Phase 1b 和 Phase 0 Task 4。
- Type consistency: `RunClass` 只定义于 domain；data gate 复用该 enum。所有正式 hash 都使用统一 `sha256:<64 lowercase hex>`，不接受全零 sentinel。
- Placeholder scan: 无 `TBD/TODO/implement later` 或省略的方法体；每个生产行为均有明确红灯、最小实现和验收命令。

# Phase 0 Task 7 Legacy Quarantine Sign-off 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用独立、可重复、fail-closed 的机器验证器证明 Phase 0 已阻断所有 legacy/样例/未封存/别名输入进入 formal，并以机器 artifact digest 与 docs-only sign-off 封存被验证的实现 commit。

**Architecture:** `verify_phase_0.py` 不创建或冒充真实 API 正向证据；验证 run 使用 sealed `RunClass.TEST` manifest，仅将 Git tree、验证策略和固定测试输入摘要作为自身身份。每个负例通过公开 `FormalAdmissionService` 执行并要求精确异常，另用正式 `RuntimeConfig` 与 repository-policy 函数重验物理隔离和 Git 内容。输出目录 must-not-exist，验证结果写入 schema 固定的 `verification.json`；实现 commit 验证通过后再创建独立 sign-off commit。

**Tech Stack:** Python 3.12、dataclasses/Pydantic contracts、hashlib/json、Git、pytest、PowerShell、GitHub Actions。

---

## Task 1: Phase 0 verifier contract 与负例矩阵

**Files:**

- Create: `tools/verification/verify_phase_0.py`
- Create: `tests/verification/test_verify_phase_0.py`

- [ ] **Step 1: 写 must-not-exist 与 schema 红灯**

测试 `_run(output_path, repository_root, created_at)` 首次创建 `run-id/verification.json`，并断言：

```python
assert report["phase"] == "phase-0"
assert re.fullmatch(r"[0-9a-f]{40}", report["git_commit"])
assert report["run_manifest_digest"].startswith("sha256:")
assert all(item.startswith("sha256:") for item in report["sealed_input_digests"])
assert {check["status"] for check in report["checks"]} == {"PASS"}
```

再次以同一 parent 调用必须抛 `FileExistsError("verification output directory already exists")`；零 digest/sentinel 不得出现在报告。

- [ ] **Step 2: 写完整负例 ID 红灯**

断言 checks 精确包含：

```python
{
    "renamed-fixture-rejected",
    "unknown-ancestor-rejected",
    "mixed-ancestor-rejected",
    "unsealed-run-rejected",
    "mutable-latest-rejected",
    "legacy-model-hold",
    "formal-roots-separated",
    "repository-policy-clean",
}
```

并断言 `legacy-model-hold` 的 details 含 `allow_new_orders=false`，而非只测试异常文本。

- [ ] **Step 3: 运行 verifier 红灯**

Run: `uv run pytest tests/verification/test_verify_phase_0.py -q --basetemp .astraquant/test-tmp/phase0-signoff-red`

Expected: FAIL，`tools.verification.verify_phase_0` 尚不存在。

- [ ] **Step 4: 实现 sealed TEST RunManifest identity**

实现 `_digest(label: str) -> str`、`_git_commit(repository_root) -> str` 与 `_verification_manifest(git_commit) -> RunManifest`。manifest 固定 code/env/input/config/randomness/event-order/matcher/vintage/policy digest，`run_class=RunClass.TEST` 并调用 `.seal()`；禁止声明 `REAL_API_*` 正向证据。

- [ ] **Step 5: 实现 formal rejection checks**

用 `_expect_rejected(check_id, expected_error, operation)` 执行公开 gate：

- `EvidenceRef.fixture("renamed-real-api.parquet", digest)` 必须因 `TEST_ONLY` 拒绝；
- unknown manifest metadata 必须降级 `LEGACY_UNVERIFIED` 并拒绝；
- approved-looking authority + fixture 的 derived mixed ancestry 必须因 fixture 拒绝；
- draft FORMAL `RunManifest` 必须因未 SEALED 拒绝；
- artifact ID `latest` 必须因 mutable alias 拒绝；
- `select_formal_model()` 必须返回 `HOLD`、`allow_new_orders=False`、`model_id=None`。

构造负例时允许使用 synthetic object 触发更早的 contract 分支，但不得把它写入 report 为 real evidence、不得调用成功 formal admission、不得写 publication root。

- [ ] **Step 6: 实现物理隔离与 repository policy checks**

在 verifier 私有临时目录创建 `RuntimeConfig(session_token="x" * 43, state_dir=...)`，调用 `prepare_directories()` 后确认 legacy root 与四个 formal roots resolved、互不重叠、qualification 不落到 `.astraquant/qualification`。repository check 调用 `tracked_files()`、`find_forbidden_paths()`、`find_forbidden_content()`，任何命中均生成 FAIL。

- [ ] **Step 7: 实现原子报告与 CLI**

`_run()` 在 output parent 不存在时创建目录，逐项生成 `checks` 和真实 details；任一 FAIL 时仍写报告并返回 exit code 1。成功时写 UTF-8 canonical JSON，`commands` 记录本 verifier argv 与 exit code 0，`created_at` 为 UTC。`main()` 只接受 `--output`，repository root 由脚本位置解析。

- [ ] **Step 8: 验证并提交**

Run: `uv run pytest tests/verification/test_verify_phase_0.py tests/api/test_formal_admission.py tests/data/test_evidence_gate.py tests/api/test_config.py tests/repository/test_repository_policy.py -q --basetemp .astraquant/test-tmp/phase0-signoff-green`

Run: `uv run ruff check tools/verification tests/verification`

Run: `uv run ruff format --check tools/verification tests/verification`

Run: `uv run mypy tools/verification tests/verification`

Commit: `git commit -m "test(governance): 建立Phase 0机器验收器"`

## Task 2: Legacy 学习文档降级说明

**Files:**

- Modify: `docs/research/quant-core-learning-guide.md`

- [ ] **Step 1: 写文档 policy 红灯**

扩展 `tests/repository/test_repository_policy.py`，断言学习文档开头包含 `LEGACY_SEMANTICS`、`demo`、`不得作为 v3 alpha` 和指向 v3 权威设计的相对路径；禁止继续把 LightGBM 称为“当前唯一生产模型”。

- [ ] **Step 2: 运行红灯**

Run: `uv run pytest tests/repository/test_repository_policy.py -q --basetemp .astraquant/test-tmp/phase0-guide-red`

Expected: FAIL，旧文档仍把 demo 结果描述为已运行生产模型。

- [ ] **Step 3: 最小修订学习文档**

在标题后增加醒目冻结说明：本文只描述 2026-08-07 的 `LEGACY_SEMANTICS/LEGACY_UNVERIFIED` demo；AUC、收益、阈值和“批准”仅是旧实现记录，不得作为 v3 alpha、发布或实盘证据。把“一句话总结”“当前唯一生产模型”“发布门槛”改成历史口径，并链接 `../superpowers/specs/2026-08-10-quant-core-open-source-architecture-design.md`。

- [ ] **Step 4: 验证并提交**

Run: `uv run pytest tests/repository/test_repository_policy.py -q --basetemp .astraquant/test-tmp/phase0-guide-green`

Commit: `git commit -m "docs: 将旧量化学习资料标记为演示证据"`

## Task 3: 生成机器证据与 docs-only sign-off

**Files:**

- Create: `docs/verification/quant-core-v3/phase-0-signoff.md`
- Modify: `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-0-repository-ci-legacy.md`
- Modify: `docs/superpowers/plans/2026-08-10-phase0-task7-signoff.md`

- [ ] **Step 1: 在实现 commit 上运行唯一全量门**

工作树必须干净。Run: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Scope All`，任一命令失败立即停止；不得把 warning 伪记 PASS。

- [ ] **Step 2: 生成 must-not-exist UUID artifact**

```powershell
$phase0RunId = [guid]::NewGuid().ToString('n')
$phase0Output = "artifacts/verification/phase-0/$phase0RunId/verification.json"
uv run python tools/verification/verify_phase_0.py --output $phase0Output
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

重算 `verification.json` SHA-256，记录绝对不进入 Git 的 artifact path、digest、实现 commit、全部 PASS check IDs。

- [ ] **Step 3: 检查范围与远端基线**

Run: `git diff --name-status origin/codex/quant-core-v3-phase0-task6...HEAD`，只允许 Task 7 verifier/tests/guide/plan。Run: `git status --short`，除 ignored artifact 外必须干净。

- [ ] **Step 4: 写 sign-off**

`phase-0-signoff.md` 必须写明：被验证 implementation commit、artifact digest、run manifest digest、测试命令、8 个 PASS checks、已知限制（尚无 Phase 1 真实 provider qualification；Phase 5 前 formal model 永远 HOLD）和“不授权 LIVE”。不复制本地绝对路径、密钥或 artifact 正文。

- [ ] **Step 5: 更新路线图并 docs-only 提交**

只在机器证据已生成且通过后勾选 Phase 0 Task 7 与本微计划；提交：`git commit -m "test(governance): 完成量化核心旧证据隔离验收"`。

- [ ] **Step 6: 推送并确认 GitHub Actions**

推送 `codex/quant-core-v3-phase0-task7`；确认本地 HEAD、remote branch SHA 和最新 CI `headSha` 一致，CI conclusion=`success`、annotations=0。按既有交付约定不创建或合并 PR。

## Self-review

- Spec coverage: 覆盖 Phase 0 八项负例/隔离/仓库门、全量验证、机器 artifact、docs-only sign-off 与远端 CI。
- Evidence honesty: verifier identity 是 TEST manifest，不伪造、提升或发布任何 fixture/legacy 数据；没有 successful FORMAL admission 假证据。
- Failure semantics: 每个 check 有独立 PASS/FAIL；失败仍写机器报告并返回非零，sign-off 不能生成。
- Reproducibility: output parent must-not-exist，Git commit/input/policy digest 固定，artifact 与 sign-off 分离。
- Scope: 不实现 Phase 1 qualification/capture，不创建 v3 ModelVersion，不授权 LIVE。

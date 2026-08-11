# Phase 1a Task 7 Real Evidence Verifier Implementation Plan

> **For agentic workers:** Use `executing-plans`, `test-driven-development`, and `verification-before-completion`.

**Goal:** 用 fail-closed 机器验证器复核外部真实 Eastmoney qualification/approval/sealed capture/reconciliation 证据，并在真实证据缺失时保持 Phase 1a 未签核。

**Architecture:** verifier 只读 manifest 指向的外部不可变 artifact，不访问网络、不读取凭据、不接受仓库 fixture。它重算 report/approval/capture/seal/reconciliation digest，验证日报与分钟能力闭合，并以 sealed TEST RunManifest 固定输入；输出目录 must-not-exist。公司行动与历史状态在 Phase 1c 前必须显式列为 `UNQUALIFIED`。

## Task 1: Evidence manifest 与 verifier 红灯

- [x] 新建 `tests/verification/test_verify_phase_1a.py`，覆盖缺 manifest、TEST_ONLY、sentinel digest、输出目录复用、artifact tamper 和 documented CLI。
- [x] 测试使用 TEST_ONLY manifest；不得创建可冒充正式通过的 pytest fixture。
- [x] 运行红灯，确认 `tools.verification.verify_phase_1a` 缺失。

## Task 2: 最小 verifier

- [x] 新建 `tools/verification/verify_phase_1a.py`。
- [x] 固定 schema 与 exact keys，拒绝仓库内 artifact path、secret-like keys、mutable alias 和全零 digest。
- [x] 重建 QualificationReport/ProviderApproval，重验 `approvable`、identity/report/approval binding；每个 probe digest 必须回溯到 sealed `QUALIFICATION_PROBE` chunk。
- [x] 用 CaptureStore 重验 exact capture/seal/chunks 与 reconciliation report；self-reconciliation 不算重复性证据。
- [x] 要求 `DAILY_BARS`、`MINUTE_BARS` 各至少一份批准且 sealed 的 capture；`CORPORATE_ACTIONS`、`INSTRUMENT_STATUS` 明确保持未批准直至 Phase 1c。
- [x] 生成统一 verification JSON 与 sealed TEST RunManifest；任一检查失败返回非零。

## Task 3: PENDING sign-off、全量验证与推送

- [x] 新建 `docs/verification/quant-core-v3/phase-1a-signoff.md`，状态固定为 `PENDING_REAL_EVIDENCE`，不填写伪 digest。
- [x] 运行 verifier tests、Phase 1a 门、Ruff、mypy、`scripts/verify.ps1 -Scope All`。Phase 1a 门 `150 passed`；全仓 Python `595 passed, 1 skipped`、前端 `104 passed`、Rust `7 passed`，其余静态/构建/策略门全绿。
- [ ] 提交并推送实现；只有后续真实受控运行成功，才允许独立 docs-only commit 将 sign-off 改为 PASS。

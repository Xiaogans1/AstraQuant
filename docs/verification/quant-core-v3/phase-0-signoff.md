# Quant Core v3 Phase 0 Sign-off

## 结论

Phase 0 `Legacy quarantine` 通过。本签核只证明旧 snapshot、旧研究/模型、旧 Paper 账本、fixture、未知/混合祖先、未封存运行和 mutable alias 无法进入 v3 `FORMAL`；不证明任何模型具有 alpha，不授权 Paper 晋级或 LIVE 委托。

## 被验证实现

- Implementation commit: `7925d41b1c61b59a0bd26f9429aed5ae4b73038a`
- Verification run ID: `272526fcbbf4461e952c8b7d648c8494`
- Verification artifact digest: `sha256:e6ea11ac6b86a4c873d0b9ae6d8cab12894f3c3bc7fdec5de2a70938389b7109`
- Sealed TEST RunManifest digest: `sha256:5f5e27433712dbf6853fb03ec913335473817fc49c2f37055d911e95a0200791`
- Artifact policy: `artifacts/verification/phase-0/{run_id}/verification.json` 为本地不可覆盖机器证据，受 repository policy 排除，不进入 Git。

## 机器检查

| Check ID | 结果 | 证明内容 |
| --- | --- | --- |
| `renamed-fixture-rejected` | PASS | fixture 改名不能升级证据分类 |
| `unknown-ancestor-rejected` | PASS | 未知 manifest metadata 降级为 `LEGACY_UNVERIFIED` 并被拒绝 |
| `mixed-ancestor-rejected` | PASS | 含 TEST_ONLY parent 的 derived lineage 不能进入 FORMAL |
| `unsealed-run-rejected` | PASS | DRAFT RunManifest 不能启动运行 |
| `mutable-latest-rejected` | PASS | `latest` 等 mutable alias 不能作为 exact artifact ID |
| `legacy-model-hold` | PASS | Phase 5 前 formal model selection 恒为 `HOLD`、`allow_new_orders=false` |
| `formal-roots-separated` | PASS | legacy data 与 qualification/capture/publication/verification roots 物理分离 |
| `repository-policy-clean` | PASS | Git tracked files 不含 raw capture、运行数据库、模型权重或 secrets |

## 验证命令

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Scope All
uv run python tools/verification/verify_phase_0.py --output artifacts/verification/phase-0/272526fcbbf4461e952c8b7d648c8494/verification.json
```

完整共享门结果：Python `459 passed, 1 skipped`，desktop `104 passed`，Rust `7 passed`；Ruff、format、mypy、repository policy、TypeScript check、desktop build、Cargo fmt/clippy/test 均通过。唯一 skip 是当前 Windows 账户无目录 symlink 权限的真实 symlink 测试；同一边界的 canonical path/escape 契约测试仍执行。

## 已知限制与后续门

- Phase 1 尚未建立真实 Eastmoney provider qualification、不可变 L0 capture、canonical/vintage snapshot 和历史 RuleBook；因此本阶段没有也不声称存在可供 FORMAL 研究的真实数据快照。
- Phase 5 的不可变 `ModelVersion`、ReleasePolicy、Shadow/Paper promotion 尚未实现；formal model selection 必须继续 `HOLD/no-new-orders`。
- 旧 LightGBM AUC、净收益、阈值和 `APPROVED` 行全部属于 `LEGACY_SEMANTICS / LEGACY_UNVERIFIED`，不能作为 v3 alpha 或发布证据。
- 本签核不授权 LIVE。真实委托仍需完成 Phase 7 资格、熔断、对账和用户单独批准的 rollout plan。

## 下一步

Phase 0 完成后进入 Phase 1a：先展开并审阅 ProviderQualification 与真实 API capture 的 Task 1 micro implementation plan，再按 TDD 实施。

# AstraQuant 量化核心 v3 分阶段开发路线图

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 按已经确认的 v3 设计，把 AstraQuant 从 demo 级自训练模型与简化回放升级为以真实 API 证据、成熟开源模型、统一 A 股执行语义和可审计发布门为核心的正式量化平台。

**Architecture:** 实施分为 Data Truth、Research、Decision、Execution 四个平面；共享契约只进入 `astraquant_domain`，外部框架固定在隔离 Runner，REPLAY/PAPER/MIRROR 共用 `astraquant_execution` 状态转换。十二份阶段路线图按 Phase 0→7 严格推进；每个 Task 开工前另写可直接执行的 micro implementation plan，每个阶段用可机器验证的退出证据解锁下一阶段。

**Tech Stack:** Python 3.12、uv workspace、Pydantic/dataclasses、PyArrow/Parquet、DuckDB、SQLite/Alembic、FastAPI、React/TypeScript、pytest、Hypothesis、RQAlpha 6.3.0 oracle、Qlib/vnpy.alpha isolated runners、GitHub Actions。

---

## 1. 权威输入与禁止绕过项

- 设计基线：`docs/superpowers/specs/2026-08-10-quant-core-open-source-architecture-design.md`。
- 本文件只负责阶段依赖、共同门和交付物索引；逐文件步骤位于下列子计划。
- `FORMAL` 运行必须 fail closed：所有行情/参考数据祖先可递归追到已批准的真实 API 或官方规则证据，特征/标签只能是这些证据的确定性派生。
- fixture、CSV、AKShare、开源样例、旧快照与未知祖先只能进入 TEST/EXPLORATORY；文件名、复制或重算不能把证据“升级”为正式证据。
- Qlib、vnpy.alpha、RQAlpha、WonderTrader、Hikyuu、TSFM 不进入主 Python runtime；每个 Runner 固定 upstream commit、lockfile、环境 hash 和补丁清单。
- 旧 `astraquant_quant.replay`、`astraquant_paper.ledger` 与旧模型结果只可读；在统一 journal 完成前不得继续扩写成正式内核。
- Phase 7 不自动授权真实委托；LIVE 需要用户另行批准账户权限、券商接口、熔断和上线 runbook。
- FinRL-X/DRL allocator 或 timing overlay 只有在 Phase 5 可审计优化器与 Phase 6 监督学习基线稳定后才可另写 ADR/计划；它不是首批 alpha、目标组合或做 T 发布的必要条件，不能阻塞诚实基线，也不能绕过统一执行内核。

## 2. 阶段依赖图

```text
Phase 0 Legacy quarantine
  └─ Phase 1 Data truth + RuleBook
       ├─ Phase 2a Task 1 canonical scenarios
       │    └─ Phase 3 Tasks 1–3 pre-kernel RQAlpha golden freeze
       │         └─ Phase 2a Tasks 2–5 → Phase 2b kernel → Phase 2c runtime
       │              └─ Phase 3 Tasks 4–8 post-kernel differential sign-off
       └─ Phase 4 Research platform + honest baselines
                          └──────────────┬──────────────┘
                                         Phase 5 Daily champion + BaseTarget
                                           └─ Phase 6 Intraday T overlay
                                                └─ Phase 7 L2/Live qualification
```

Phase 2 与 Phase 4 的非持久化部分可以在 Phase 1 的 sealed contract 完成后并行开发，但执行状态转换开始前必须完成 Phase 3 Tasks 1–3，Phase 4 的 `0014` 合并与正式 sign-off 必须等待 Phase 2c/3；Phase 5 必须同时持有 Phase 3 完整 execution sign-off 与 Phase 4 research sign-off。

## 3. 子计划与交付门

| 顺序 | 阶段路线图 | 核心交付物 | 解锁条件 |
| --- | --- | --- | --- |
| 0 | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-0-repository-ci-legacy.md` | 干净 CI、证据分类、legacy 封存、formal admission、物理隔离 | 全量门可重复；旧数据/模型/账本无法进入 formal |
| 1a | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-1a-provider-capture.md` | ProviderQualification、CaptureEnvelope、batch API capture | 每个 endpoint 独立批准；raw evidence 不可变且无静默截断 |
| 1b | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-1b-canonical-vintage-snapshots.md` | canonical/PIT/vintage、coverage、snapshot v2、publication ledger | exact snapshot 可重现；AS_DELIVERED/PIT_STRICT 不可互换 |
| 1c | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-1c-rulebook-reference-data.md` | RuleBook、动态 session、历史 universe/status、公司行动 | 规则/状态 100% 有生效期和来源；缺失即 fail closed |
| 2a | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-2a-execution-contracts.md` | canonical scenarios、领域契约、deterministic journal | v3 契约冻结；journal 重放与不变量基座全绿 |
| 2b | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-2b-execution-kernel.md` | lots/settlement/cash/fees/OMS/matcher/TPlan/valuation | 全部 canonical execution scenarios 通过 |
| 2c | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-2c-runtime-migration.md` | SQLite store、REPLAY/PAPER/MIRROR 共核、legacy opening migration | 崩溃恢复/并发/模式 parity/MIRROR 分账全绿 |
| 3 | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-3-open-source-oracles.md` | 内核前 RQAlpha golden freeze；内核后主差分、局部开源交叉、Broker fixtures | 状态转换前 golden 已冻结；最终无未解释资金/持仓/可卖量差异 |
| 4 | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-4-research-platform.md` | `astraquant_research`、FeatureGraph/LabelSpec、预冻结 ReleasePolicy、walk-forward/lockbox、Qlib/vnpy.alpha、无争议基线 | 真实 API 日线基线矩阵可复现；无 lockbox/HPO 泄漏 |
| 5 | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-5-daily-target-release.md` | 日线 challenger、受限 RD-Agent 提案、组合优化、BaseTarget、Shadow/Paper promotion | 阶段允许诚实产出“暂无可发布模型”，但只有 champion 通过才解锁 Phase 6 |
| 6 | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-6-intraday-t.md` | 分钟模型、TPlan、两种做 T、sleeve attribution、forward Paper | 足够独立样本；成本/延迟压力后净增量成立；T+1 场景全绿 |
| 7 | `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-7-l2-live-readiness.md` | L2 资格、queue replay、gateway/reconciliation qualification、Live 审批包 | 只形成准入结论；用户单独批准后才能另写 LIVE rollout plan |

## 4. 设计覆盖映射

| v3 设计段落 | 主责计划/任务 | 机器出口 |
| --- | --- | --- |
| §2–3 原则与旧基线审计 | Phase 0 Tasks 1–7 | CI、legacy admission/physical isolation sign-off |
| §4 开源采用矩阵 | Phase 3 Tasks 1–8；Phase 4 Tasks 7–8；Phase 6 Tasks 3–4 | runner manifests、trace hashes、差异 ADR |
| §5 包边界 | Phase 2a Task 3；Phase 4 Task 1 | workspace/import/runtime discovery tests |
| §6 数据真相与快照 | Phase 1a 全部 Tasks；Phase 1b 全部 Tasks；Phase 1c reference/capture Tasks | qualification/capture/vintage/publication/reference lineage |
| §7 特征、标签、模型研究 | Phase 4 Tasks 2–10；Phase 6 Tasks 1–4；Phase 7 Tasks 4–5 | Feature/Label snapshots、Trial Ledger、model matrices |
| §8 预测到目标仓位/做 T | Phase 5 Tasks 3–5；Phase 6 Tasks 5–6；Phase 2b Task 9 | Target/Intent/TPlan/attribution digests |
| §9 RuleBook、lots、费用/税 | Phase 1c RuleBook/fee/tax Tasks；Phase 2b Tasks 1–5 | policy lineage、cash/lot/fee/tax invariants |
| §10 执行与回放 | Phase 2a Tasks 1–5；Phase 2b Tasks 6–10；Phase 2c Tasks 1–8；Phase 3 | canonical execution、mode parity、oracle diffs |
| §11 风控 | Phase 2b Task 7；Phase 5 Tasks 3–4；Phase 7 Tasks 6–7 | RiskDecision、安全动作、故障演练 |
| §12 验证协议 | Phase 4 Tasks 4–6/10；Phase 5 validation/promotion Tasks；Phase 6 validation/sign-off Tasks | splits/lockbox/statistics/stress/release decisions |
| §13 注册、Shadow、Paper、回滚 | Phase 5 Tasks 6–9；Phase 6 Task 7 | immutable ModelVersion、alias、forward gates |
| §14–15 契约、决定性、故障、审计 | Master §§5–8；Phase 0 Tasks 2/4；Phase 2a Tasks 2–5；Phase 2c Tasks 6–8 | RunManifest、journal digest、lineage UI、fail-closed drills |
| §16–17 阶段/最终验收 | 每份子计划最后一个 sign-off Task | `artifacts/verification/*` digest 与 Git sign-off |
| §18–19 禁止事项/文档治理 | Master §§1/8/10；Phase 0 Task 7；Phase 2c Task 8 | repository policy、superseded docs、ADRs |

同一要求可以有下游消费方，但只有表中的主责 Task 定义契约和首次验收；后续阶段只能复用或加严，不能另造不兼容语义。

## 5. 跨阶段包依赖

```text
astraquant_domain       # 无第三方框架、数据库或 UI 依赖
├── astraquant_data     # capture/canonical/vintage/snapshot
├── astraquant_research # feature/label/trial/validation contracts
├── astraquant_quant    # forecast→target→risk→intent
└── astraquant_execution# rules/OMS/lots/matcher/account journal
    └── astraquant_paper# mode orchestration + persistence/projections only

astraquant_api          # 调用以上服务，不直接改账本
apps/desktop            # 只经版本化 API command/query 交互
runners/*               # 外部开源框架独立环境，以 Arrow + versioned JSON 通信
```

`astraquant_research` 保持只依赖 domain/data；需要可执行价格、matcher 与成本时，只依赖 research-owned Protocol，由 API composition root 注入 `astraquant_execution` adapter，并以 integration test 固定 policy digest。研究包不得为了方便直接 import 执行内核。

新增 workspace package 时，同一提交必须更新根 `pyproject.toml` 的 dependencies、`[tool.uv.sources]`、workspace members、Ruff `src`/first-party 和 mypy files，并运行 `uv lock`；不能留下只在开发机 import 成功的隐式路径。

数据库 revision 顺序固定，计划并行开发也不得改变 Alembic 主链：

```text
0009_v3_legacy_evidence
  → 0010_provider_qualification_capture
  → 0011_snapshot_v2
  → 0012_rulebook_reference_data
  → 0013_execution_journal
  → 0014_research_v3
  → 0015_model_release_targets
  → 0016_intraday_t
  → 0017_l2_qualification
```

每个 migration micro plan 必须同时修改 `packages/api/src/astraquant_api/schema_registry.py` 与 `tests/api/test_schema_registry.py`，运行真实前一 revision→head 的 parity/smoke；没有 registry 更新的 migration 不得合并。

## 6. 每个 Task 的微计划门与标准执行循环

路线图 Task 不是实现粒度。开工前必须新增独立 micro implementation plan，写出精确 API/symbol/signature/DDL、完整首个失败测试、预期错误、最小实现步骤、逐条命令和原子提交边界，并先经审阅。只有该微计划通过后，才使用以下循环；不得把红灯测试与实现跨提交拆开。

- [ ] 从干净工作树开始，记录当前 plan checkbox 与权威设计段落。
- [ ] 先写一个最小失败测试；运行子集并确认它因缺少目标语义失败，而不是环境或拼写失败。
- [ ] 实现最小但完整的领域语义；禁止 hard-code 当前费率、交易日或 provider 特例。
- [ ] 运行相邻包测试、类型检查和 lint；保存机器可读证据 hash。
- [ ] 更新契约/ADR/用户文档与 plan checkbox。
- [ ] 用计划中给定的中文提交信息提交，不混入相邻 Task。

推荐每个 micro plan 的验证顺序：

```powershell
uv run pytest -q tests/data/test_evidence_gate.py
uv run ruff check packages/data/src tests/data/test_evidence_gate.py
uv run ruff format --check packages/data/src tests/data/test_evidence_gate.py
uv run mypy packages/data/src tests/data/test_evidence_gate.py
```

涉及桌面端时追加：

```powershell
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

Phase 0 落地后，每个 Phase 合并前必须从仓库根目录调用唯一 fail-fast 验证入口；子计划不得复制一套会漂移的全量门：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Scope All
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

## 7. 统一机器证据

每个 Phase 在已提交、干净的实现 commit 上生成 `artifacts/verification/{phase}/{run_id}/verification.json`；`run_id` 必须为新 UUID，输出目录 must-not-exist，禁止 `local`/`formal` 固定目录覆盖历史。`artifacts/` 不提交 Git，只提交 schema、生成器与使用说明。验证通过后再以独立 docs-only commit 写 sign-off，使 `git_commit` 精确指向被验证的实现。文件必须包含下列结构；示例中的全零值只展示长度，formal verifier 必须拒绝全零/sentinel digest：

```json
{
  "phase": "phase-1",
  "git_commit": "0000000000000000000000000000000000000000",
  "run_manifest_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "sealed_input_digests": ["sha256:0000000000000000000000000000000000000000000000000000000000000000"],
  "commands": [{"argv": ["uv", "run", "pytest", "-q"], "exit_code": 0}],
  "checks": [{"id": "formal-ancestor-closure", "status": "PASS"}],
  "created_at": "2026-08-10T00:00:00Z"
}
```

同一 Phase 的 sign-off 文件 `docs/verification/quant-core-v3/phase-{phase}-signoff.md` 必须引用该 JSON 的 digest、测试命令、已知限制和 ADR；不能复制本地数据、密钥、模型权重或伪造运行结果进 Git。

## 8. 共同硬门

- [ ] 所有 formal run 都有 sealed `RunManifest`，固定 code/env/input/config/randomness/event-order/matcher/vintage/policy hashes。
- [ ] 数据、feature、label、forecast、target、intent、order、fill、journal 和 PnL 的 lineage 可逆向追到 raw capture。
- [ ] 时间检查覆盖 `source_available_time`、`observed_received_time`、`vintage_proven_time`、processing delay 与 label maturity；不允许 same-bar close 决策成交。
- [ ] 资金、持仓、证券预占、交收义务、费用与税务都由 append-only journal 派生，任何补偿均为新事件。
- [ ] REPLAY/PAPER/MIRROR 的离散订单、Decimal 金额和状态对 sealed inputs 精确重现；浮点模型容差必须预声明。
- [ ] 任何发布门失败都执行 HOLD/no-new-orders，不能现场调阈值、重训或自动换未批准 fallback。
- [ ] 开源 oracle 与 Broker/交易所事实冲突时，记录最小 trace 和 ADR；不为了让 diff 变绿而复制已知缺陷。

## 9. 里程碑提交边界

| 里程碑 | 允许合并的内容 | 禁止夹带 |
| --- | --- | --- |
| M0 | quarantine、run/evidence gate、legacy read-only migration | 新模型、执行性能优化 |
| M1 | data truth、RuleBook、snapshot publication | 模型成绩或手工数据 |
| M2 | execution contracts/journal/canonical semantics | oracle 结果的人工覆盖 |
| M3 | isolated oracle runners、diff reports/ADR | 主 runtime 依赖外部框架 |
| M4 | research ledger、baseline matrix | challenger promotion |
| M5 | daily champion、targets、Shadow/Paper gates | 分钟 T 或 LIVE |
| M6 | intraday T、forward evidence | L2 成绩冒充分钟证据 |
| M7 | L2/gateway qualification 与审批包 | 真实下单开关 |

本路线图 docs bootstrap PR 先独立合入 `origin/main`；后续实现分支必须以含路线图的最新 main 为基线。PR 边界按“独立可合并 checkpoint”而不是“一个路线图文件一个 PR”：Phase 2/3 固定为 `2a Task 1 canonical inputs → 3 Tasks 1–3 oracle bootstrap → 2a Tasks 2–5 contracts → 2b kernel → 2c runtime → 3 Tasks 4–8 post-kernel diff`，每个 checkpoint 只在前一个合入 main 后创建短生命周期 `codex/quant-core-v3-*` 分支。其他阶段也可按经审阅 micro plan 拆 PR。开始和提交前都运行 `git diff --name-status origin/main...HEAD`；出现无关删除、README 回退、用户文件或其他阶段实现时立即停止拆分。外部 runner lock、数据库迁移与领域契约分别提交，便于独立回滚和审阅。

## 10. 计划自检与启动方式

- [ ] 运行 `rg -n -g '2026-08-10-quant-core-v3-*.md' '(T)(O)(D)(O)|(T)(B)(D)|(以)(后)(实)(现)|(先)(占)(位)|(待)(补)' docs/superpowers/plans`，期望无输出。
- [ ] 运行 `rg -n -g '2026-08-10-quant-core-v3-*.md' '^> \*\*Execution gate:\*\*' docs/superpowers/plans`，期望 13 个文件各命中一次。
- [ ] 核对每个 `Create:` 路径只在对应阶段首次出现；`Modify:` 路径当前存在或由更早任务创建。
- [ ] 核对所有测试步骤都先于实现步骤，所有 commit 步骤都在对应测试通过之后。
- [ ] 从 Phase 0 Task 1 的 micro implementation plan 开始；微计划审阅通过后，推荐使用 `superpowers:subagent-driven-development` 执行并在每个 checkpoint/Phase 请求独立 code review。

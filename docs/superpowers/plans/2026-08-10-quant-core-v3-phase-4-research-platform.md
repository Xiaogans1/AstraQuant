# Quant Core v3 Phase 4 Research Platform and Baselines Stage Roadmap

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 建立独立的 `astraquant_research`、唯一 FeatureGraph/LabelSpec、不可变派生快照、无泄漏 walk-forward/lockbox/Trial Ledger，并在真实 API 日线数据上公平运行 no-skill、线性和树模型基线及 Qlib/vnpy.alpha 复现。

**Architecture:** 正式研究只消费 exact approved snapshot IDs；shared observations/forecast contracts 在 domain，研究编排在 research，数据 materialization 在 data。外部框架各用独立 lock/env，通过 versioned JSON+Arrow 交换。Phase 4 可在 Phase 1 后开发，但可执行价格/净收益验收必须等待 Phase 2/3 的 RuleBook、matcher、cost sign-off。

**Tech Stack:** Python 3.12、PyArrow/Parquet、scikit-learn、LightGBM、XGBoost、CatBoost、Qlib `79633dd9506ea689e5400dea0197717b5b3d74b7`、vn.py `fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09`、SQLite/Alembic、pytest。

---

## 2026-08-11 策略效果优先执行顺序

不再先完成 research package、数据库迁移、lockbox UI 和完整审计体系。先按 `2026-08-11-strategy-effect-fast-lane.md` 在现有研究链上完成真实 Eastmoney 数据的 no-skill/线性/LightGBM 公平矩阵，再接 Qlib；当模型具备稳定 OOS 净收益、准备进入 Shadow/Paper 时，再补本路线图的不可变 registry、lockbox、迁移和 UI。原 Tasks 保留为上线治理清单，但不再代表当前开发优先级。

## Task 1: 创建 astraquant_research 并隔离 legacy research

**Files:**

- Create: `packages/research/pyproject.toml`
- Create: `packages/research/src/astraquant_research/__init__.py`
- Create: `packages/research/src/astraquant_research/py.typed`
- Modify: `pyproject.toml`
- Modify: `packages/api/pyproject.toml`
- Modify: `apps/desktop/src-tauri/src/runtime.rs`
- Modify: `tests/integration/test_runtime_round_trip.py`
- Modify: `packages/quant/src/astraquant_quant/research_features.py`
- Modify: `packages/data/src/astraquant_data/research_store.py`
- Modify: `tools/research/build_training_set.py`
- Modify: `tools/research/train_model.py`
- Test: `tests/research/test_package.py`
- Test: `tests/research/test_legacy_isolation.py`

- [ ] 先测试 root/API/Tauri/integration 都能 import `astraquant_research`，它只依赖 domain/data；主 runtime 不含 Qlib/vn.py。
- [ ] 先测试旧 research_features/store/tools 输出 `LEGACY_SEMANTICS`，formal import/admission 明确拒绝；旧 UI/CLI 保持可读，不删除。
- [ ] 运行目标 tests，确认 package/markers 缺失红灯。
- [ ] 更新 workspace/dependencies/Ruff/mypy/isort 与 API dependency，运行 `uv lock`；baseline dependencies 进入 research optional extra/main lock 的冻结范围，external runners 仍隔离。
- [ ] 实现 legacy boundary，并阻止 formal service import 旧 train/publish/replay functions。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "build(research): 建立正式研究包边界"`

## Task 2: 冻结 Feature/Label/Forecast contracts

**Files:**

- Create: `packages/domain/src/astraquant_domain/research.py`
- Create: `packages/research/src/astraquant_research/contracts.py`
- Create: `packages/research/src/astraquant_research/feature_graph.py`
- Create: `packages/research/src/astraquant_research/processors.py`
- Create: `packages/research/src/astraquant_research/labels.py`
- Test: `tests/domain/test_research_contracts.py`
- Test: `tests/research/test_feature_graph.py`
- Test: `tests/research/test_processors.py`
- Test: `tests/research/test_label_spec.py`

- [ ] 先测试 feature available time >= 所有 data/universe/rule/fit artifact visible time + declared processing delay；processor fitted on future fold 必须拒绝。
- [ ] 先测试 label entry 是 decision 后下一可执行 event，exit completion/grace/所有 ancestors 决定 `label_matures_at`；当前 close entry 和 horizon index 不一致的旧逻辑拒绝。
- [ ] 先测试 `label_matures_at > training_cutoff` 的 row 不进入 fit/select/calibration；AlphaForecast 固定 model/feature lineage、valid interval、expected/rank/quantiles/uncertainty。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 immutable FeatureSpec/Graph、processor artifacts、LabelSpec/Observation 和 shared forecast contract；graph canonical hash 与拓扑/cycle validation。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 建立特征标签与预测契约"`

## Task 3: 发布不可变 Feature/Label snapshots

**Files:**

- Create: `packages/data/src/astraquant_data/derived_store.py`
- Create: `packages/research/src/astraquant_research/materialization.py`
- Test: `tests/data/test_derived_store.py`
- Test: `tests/research/test_materialization.py`

- [ ] 先测试 materializer 只接 exact approved snapshot ids，并固定 data vintage cutoff、availability/revision policy、vintage mode、PIT fidelity、FeatureGraph/LabelSpec/code/env hashes 和 online parity digest。
- [ ] 测试相同 ancestors/code/config 得相同 content digest；任一 cutoff/policy/ancestor 改变即不同；TEST_ONLY/legacy/mixed ancestry 不能产 `DERIVED_REAL_API`。
- [ ] 测试 formal read 沿用 Phase 1 snapshot v2 的全部 file/ledger/ancestry 验证，不另造弱化的 research hash。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 derived store/materializer、partition completeness 和 row-level time proofs。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 发布不可变特征标签快照"`

## Task 4: 实现 walk-forward、purge/embargo 与 lockbox

**Files:**

- Create: `packages/domain/src/astraquant_domain/release.py`
- Create: `packages/research/src/astraquant_research/splits.py`
- Create: `packages/research/src/astraquant_research/validation_policy.py`
- Create: `packages/research/src/astraquant_research/release_policy.py`
- Create: `packages/research/src/astraquant_research/lockbox.py`
- Test: `tests/domain/test_release_contracts.py`
- Test: `tests/research/test_splits.py`
- Test: `tests/research/test_validation_policy.py`
- Test: `tests/research/test_release_policy.py`
- Test: `tests/research/test_lockbox.py`

- [ ] 先测试首个 experiment family、baseline 或 lockbox token 产生前，必须已有 SEALED 且带 digest 的 `SplitPolicy`、`ValidationPolicy` 与 `ReleasePolicy v1`；缺失、晚冻结或看到结果后修改全部 fail closed。
- [ ] 先测试全 universe 共用交易时间轴，同日多证券不能因拼行顺序拆进不同 fold；任何 label interval `[t0,t1]` 相交都 purge。
- [ ] embargo 从 horizon、entry/exit latency 和 policy 计算；固定跳过 5 rows 的实现必须在 test 中失败。
- [ ] lockbox runner 看不到最终 labels，只向评估 service 提交 sealed predictions 并收到预声明 aggregate metrics；每次访问 append-only 计数。
- [ ] 测试一次提交后 lockbox 立即进入 `CONSUMED`；揭盲后修改 code/model/config/threshold 会使旧 attempt 保留但不可复用，必须创建只覆盖未来时期的新 lockbox，不能删除失败尝试再重开。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 immutable/versioned policy contracts、nested walk-forward/purged CV、one-time lockbox token 与 access ledger contract；`ReleasePolicy v1` 预先固定 comparator、统计/压力阈值、trial denominator、允许的状态转换以及失败时 HOLD，不包含任何首轮结果。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 冻结验证发布策略与锁箱"`

## Task 5: 建立 append-only Trial Ledger 和 0014 schema

**Files:**

- Create: `packages/research/src/astraquant_research/trial_ledger.py`
- Create: `packages/api/migrations/versions/0014_research_v3.py`
- Create: `packages/api/src/astraquant_api/research_v3_repository.py`
- Modify: `packages/api/src/astraquant_api/schema_registry.py`
- Test: `tests/research/test_trial_ledger.py`
- Test: `tests/api/test_research_v3_repository.py`
- Modify: `tests/api/test_schema_registry.py`

- [ ] 前置门：本 Task 可以在 Phase 1 后设计，但 `0014` 的实现/合并必须等待 Phase 2c 的 `0013_execution_journal` 已合并；禁止从并行分支伪造 `down_revision`。
- [ ] 先测试 experiment family 在看到结果前冻结 folds、budget、seeds、metrics/gates；trial 成功/失败/取消都计入 denominator，预算先 reserve 后运行。
- [ ] 测试同一 family 超 HPO/wall-clock/GPU budget 拒绝，失败记录不可覆盖；manifest/input/artifact/log digests 完整。
- [ ] 运行目标 tests，确认红灯。
- [ ] 0014 创建 experiment families、trial records、folds、run manifests、feature/label snapshots、forecast/model artifacts、sealed policy artifacts、lockbox access/consumption；`down_revision="0013_execution_journal"`，并同步更新 schema registry 与 head parity test。
- [ ] 实现 append-only ledger/repository 与 idempotent background result ingestion，Worker 不直接写 SQLite。
- [ ] 重跑 tests/migration smoke，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 持久化正式试验账本"`

## Task 6: 实现公平 baseline matrix 与统计/压力协议

**Files:**

- Create: `packages/research/src/astraquant_research/execution_protocol.py`
- Create: `packages/api/src/astraquant_api/research_execution_adapter.py`
- Create: `packages/research/src/astraquant_research/baselines/no_skill.py`
- Create: `packages/research/src/astraquant_research/baselines/linear.py`
- Create: `packages/research/src/astraquant_research/baselines/trees.py`
- Create: `packages/research/src/astraquant_research/experiment.py`
- Create: `packages/research/src/astraquant_research/metrics.py`
- Create: `packages/research/src/astraquant_research/statistics.py`
- Create: `packages/research/src/astraquant_research/stress.py`
- Create: `packages/research/src/astraquant_research/offline_gate.py`
- Test: `tests/research/test_baselines.py`
- Test: `tests/research/test_walk_forward.py`
- Test: `tests/research/test_statistics.py`
- Test: `tests/research/test_stress.py`
- Test: `tests/research/test_offline_gate.py`
- Test: `tests/research/test_execution_protocol.py`
- Test: `tests/integration/test_research_execution_adapter.py`

- [ ] 先测试 research 只依赖 domain/data 暴露的 `ExecutablePriceCostProtocol`，不能 import `astraquant_execution`；API composition root 注入 Phase 2 matcher/cost adapter，并用同一 sealed RuleBook/cost/matcher policy digest 做 integration test。
- [ ] 先测试 baseline matrix 在 `SplitPolicy`、`ValidationPolicy`、`ReleasePolicy v1` 任一未 SEALED 时拒绝启动；执行期间 policy digest 不可变化。
- [ ] 先测试 no-skill/截面均值/行业中性/简单动量反转、Ridge/Lasso、LightGBM/XGBoost/CatBoost 使用相同 rows/folds/costs/seeds/trial/wall-clock budget。
- [ ] threshold/calibration 只能 inner valid；outer OOS/lockbox 不能回头调参；所有 folds/seeds/failures 计入报告。
- [ ] 对 CPCV paths、PSR/Deflated Sharpe、PBO/CSCV、White Reality Check/SPA 用冻结权威数值案例测试。
- [ ] stress 固定 base/adverse/severe costs、0/1/2 bar latency、participation/capacity/regime；净收益经注入的 Phase 2 executable-price/matcher/cost adapter 计算，不用 close-to-close 幻想成交。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 baseline/metrics/statistics/stress/offline gate；Phase 4 最高只到 OFFLINE_VALIDATED，不直接 SHADOW/CHAMPION。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 建立公平基线与统计验证"`

## Task 7: 建立 versioned external runner contract

**Files:**

- Create: `contracts/research-runner/v1/request.schema.json`
- Create: `contracts/research-runner/v1/response.schema.json`
- Create: `packages/research/src/astraquant_research/runners/contract.py`
- Create: `packages/research/src/astraquant_research/runners/subprocess.py`
- Create: `packages/data/src/astraquant_data/exports/__init__.py`
- Create: `packages/data/src/astraquant_data/exports/qlib.py`
- Create: `packages/data/src/astraquant_data/exports/vnpy_alpha.py`
- Test: `tests/research/test_runner_contract.py`
- Test: `tests/research/test_runner_subprocess.py`
- Test: `tests/data/test_qlib_export.py`
- Test: `tests/data/test_vnpy_alpha_export.py`

- [ ] 先测试 request 固定 exact export/input/feature/label/fold/budget/seed/env/upstream hashes，response 固定 prediction/artifact/log/failure hashes；version/evidence/hash 不匹配全部拒绝。
- [ ] 两种 export 消费同一 canonical row set/content digest，显式记录 row order、calendar、processor、dtype/precision mapping。
- [ ] subprocess 运行在 declared cwd/env，禁止继承 secrets 和 network download；timeout/cancel/partial output 记失败 trial，不吞掉。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 Arrow/Parquet export 与 versioned JSON subprocess adapter。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 建立隔离模型运行契约"`

## Task 8: 固定 Qlib 与 vnpy.alpha 独立 Runner

**Files:**

- Create: `runners/qlib/pyproject.toml`
- Create: `runners/qlib/uv.lock`
- Create: `runners/qlib/.python-version`
- Create: `runners/qlib/src/astraquant_qlib_runner/__main__.py`
- Create: `runners/qlib/src/astraquant_qlib_runner/data_adapter.py`
- Create: `runners/qlib/src/astraquant_qlib_runner/models.py`
- Create: `runners/qlib/README.md`
- Create: `runners/qlib/tests/test_data_adapter.py`
- Create: `runners/qlib/tests/test_models.py`
- Create: `runners/vnpy-alpha/pyproject.toml`
- Create: `runners/vnpy-alpha/uv.lock`
- Create: `runners/vnpy-alpha/.python-version`
- Create: `runners/vnpy-alpha/src/astraquant_vnpy_alpha_runner/__main__.py`
- Create: `runners/vnpy-alpha/src/astraquant_vnpy_alpha_runner/data_adapter.py`
- Create: `runners/vnpy-alpha/src/astraquant_vnpy_alpha_runner/models.py`
- Create: `runners/vnpy-alpha/README.md`
- Create: `runners/vnpy-alpha/tests/test_data_adapter.py`
- Create: `runners/vnpy-alpha/tests/test_models.py`
- Test: `tests/research/test_external_runner_manifests.py`

- [ ] Qlib 固定 `79633dd...`，vn.py 固定 `fa5206f...`；各自记录 Python/uv lock/upstream/patch/env hash，不加入 root workspace。
- [ ] Runner 禁止使用上游 sample/bundle/download；只能读取 Astra export request，输出相同 forecast contract。Qlib adapter 明确实现 Alpha158 handler 与共同 Lasso/LightGBM；vnpy.alpha adapter 明确实现共同 Lasso/LightGBM 及其 MLP，模型名、processor 与 dtype 都进入 response manifest。
- [ ] 先在各自隔离环境测试 `data_adapter.py` 的 exact row/content digest 与 `models.py` 的共同 Lasso/LightGBM prediction contract，再测试 `--version-manifest` 和 synthetic TEST_ONLY roundtrip；main pytest 不要求 runner dependencies。
- [ ] 运行 `uv lock --project runners/qlib` 与 `uv lock --project runners/vnpy-alpha`，人工审核 lock。
- [ ] 运行：

```powershell
uv run --project runners/qlib --frozen python -m astraquant_qlib_runner --version-manifest
uv run --project runners/qlib --frozen pytest runners/qlib/tests -q
uv run --project runners/vnpy-alpha --frozen python -m astraquant_vnpy_alpha_runner --version-manifest
uv run --project runners/vnpy-alpha --frozen pytest runners/vnpy-alpha/tests -q
uv run pytest tests/research/test_external_runner_manifests.py -q
```

- [ ] 提交：`git commit -m "build(research): 固定Qlib与vnpy研究环境"`

## Task 9: 建立 formal research API/CLI 和桌面审计页

**Files:**

- Create: `packages/api/src/astraquant_api/research_v3_schemas.py`
- Create: `packages/api/src/astraquant_api/research_v3_routes.py`
- Create: `packages/api/src/astraquant_api/research_v3_service.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Create: `tools/research/run_baseline_matrix.py`
- Create: `tools/research/compare_runners.py`
- Create: `tools/research/compare_repeatability.py`
- Create: `tools/research/submit_lockbox.py`
- Test: `tests/api/test_research_v3_routes.py`
- Modify: `apps/desktop/src/api/research-contracts.ts`
- Modify: `apps/desktop/src/api/queries.ts`
- Create: `apps/desktop/src/components/ResearchRunAudit.tsx`
- Create: `apps/desktop/src/components/ResearchRunAudit.test.tsx`
- Modify: `apps/desktop/src/pages/StrategyLabPage.tsx`
- Modify: `apps/desktop/src/pages/StrategyLabPage.test.tsx`

- [ ] 先测试 FORMAL 请求只收 exact data/feature/label/split/validation/release/rule/cost IDs；direct instruments/dataset path/latest、legacy、未 SEALED policy、lockbox 越权和 AS_DELIVERED-only release evidence 全拒绝。
- [ ] 测试 train/evaluate/compare 都是 cancellable/idempotent background tasks，API process 不同步训练，Worker 不写 SQLite。
- [ ] UI 显示 lineage、fold/budget/seed、失败 trials、PIT fidelity、runner versions 和 lockbox access，不把 legacy/formal 成绩混排。
- [ ] 运行 API/frontend tests，确认红灯。
- [ ] 实现 service/routes/CLI/UI，拆分现有大 StrategyLab page，所有 mutation 经 authenticated API command。
- [ ] 重跑 tests/check/build，期望全绿。
- [ ] 提交：`git commit -m "feat(research): 编排正式研究与审计界面"`

## Task 10: 真实 API baseline matrix 与 Phase 4 sign-off

**Files:**

- Create: `tests/integration/test_research_lineage.py`
- Create: `tests/integration/test_runner_parity.py`
- Create: `tools/verification/verify_phase_4.py`
- Create: `docs/verification/quant-core-v3/phase-4-signoff.md`

- [ ] 以 Phase 1 exact Eastmoney API 日线 snapshot（不是开源数据）和首次结果前 SEALED 的 Split/Validation/ReleasePolicy 运行 no-skill/Ridge/Lasso/LGBM/XGB/CatBoost；同一 folds/costs/seeds/trial budget 的 `run-a`/`run-b` 稳定 input/fold/prediction/report digests 必须相同，publication UUID/时间戳不进入稳定 digest。
- [ ] Qlib/vnpy.alpha 共同模型读取同一 export content digest；row set/order/processor/precision 差异全部进入机器报告，不允许无法解释差异。
- [ ] 验证 outer/lockbox labels 参与 fit/threshold=0，未成熟 label=0，失败 trials 记录率=100%；先完成非 lockbox repeatability，再只提交一次 sealed predictions，提交后 lockbox=`CONSUMED`。任何后续 code/model/config/threshold 变化必须登记新 family 并使用未来 lockbox；结论允许 INSUFFICIENT_EVIDENCE/无模型通过。
- [ ] 用只引用 Phase 1 exact approved snapshots 与 Phase 2/3 policy/sign-off digests 的 SEALED request manifest 实际运行矩阵和 verifier；TEST_ONLY/脱敏 fixture 只用于 pytest，不得替代：

```powershell
$phase4RequestManifest = $env:ASTRAQUANT_PHASE4_REQUEST_MANIFEST
if ([string]::IsNullOrWhiteSpace($phase4RequestManifest)) { throw 'ASTRAQUANT_PHASE4_REQUEST_MANIFEST is required' }
$phase4LockboxManifest = $env:ASTRAQUANT_PHASE4_LOCKBOX_MANIFEST
if ([string]::IsNullOrWhiteSpace($phase4LockboxManifest)) { throw 'ASTRAQUANT_PHASE4_LOCKBOX_MANIFEST is required' }
$phase4RunId = [guid]::NewGuid().ToString('n')
$phase4ResultRoot = "artifacts/research/phase-4/$phase4RunId"
$phase4VerificationRoot = "artifacts/verification/phase-4/$phase4RunId"
uv run python tools/research/run_baseline_matrix.py --request-manifest $phase4RequestManifest --output-root "$phase4ResultRoot/run-a"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python tools/research/run_baseline_matrix.py --request-manifest $phase4RequestManifest --output-root "$phase4ResultRoot/run-b"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python tools/research/compare_repeatability.py --left "$phase4ResultRoot/run-a" --right "$phase4ResultRoot/run-b" --output "$phase4ResultRoot/repeatability.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python tools/research/compare_runners.py --request-manifest $phase4RequestManifest --results-root "$phase4ResultRoot/run-a" --output "$phase4ResultRoot/runner-diff.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python tools/research/submit_lockbox.py --request-manifest $phase4RequestManifest --lockbox-manifest $phase4LockboxManifest --predictions "$phase4ResultRoot/run-a/predictions" --output "$phase4ResultRoot/lockbox-result.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python tools/verification/verify_phase_4.py --request-manifest $phase4RequestManifest --results-root $phase4ResultRoot --output "$phase4VerificationRoot/verification.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```
- [ ] 运行：

```powershell
uv run pytest tests/domain/test_research_contracts.py tests/domain/test_release_contracts.py tests/data/test_derived_store.py tests/data/test_qlib_export.py tests/data/test_vnpy_alpha_export.py tests/research tests/api/test_research_v3_repository.py tests/api/test_research_v3_routes.py tests/api/test_schema_registry.py tests/integration/test_research_execution_adapter.py tests/integration/test_research_lineage.py tests/integration/test_runner_parity.py -q
uv run ruff check packages/domain/src packages/data/src packages/research/src packages/api/src tools/research tools/verification tests
uv run ruff format --check packages/domain/src packages/data/src packages/research/src packages/api/src tools/research tools/verification tests
uv run mypy
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

- [ ] sign-off 引用真实 matrix repeatability/lockbox-consumption artifact digest、预冻结 policy digests、Phase 2/3 executable-price/cost/oracle sign-offs 和所有 known fidelity limits；未获得这些证据时 Phase 4 不通过。
- [ ] 提交：`git commit -m "test(research): 完成真实数据基线矩阵验收"`

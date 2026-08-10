# Quant Core v3 Phase 7 L2 and Live Readiness Stage Roadmap

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 证明 L2 数据、queue replay、盘口模型与券商 gateway/reconciliation 是否具备进入下一份 Live 设计的条件，并产出明确 READY_FOR_LIVE_DESIGN 或 NOT_READY 结论；本计划绝不发送真实委托。

**Architecture:** L2 先做 endpoint qualification/continuous capture，再跑 OFI/queue baseline，只有有效独立历史/MinTRL 足够才评估 DeepLOB/TLOB。vn.py TORA/XTP 只作为隔离 gateway/report adapter，Broker reports 驱动 Astra journal；默认 build 继续没有真实下单 capability。任何 LIVE rollout 必须在本计划 sign-off 后由用户另行批准并新写 spec/plan。

**Tech Stack:** Phase 1 capture/snapshot、L2 Arrow schema、hftbacktest isolated queue runner、PyTorch isolated LOB runner、vn.py 4.4 TORA/XTP adapters、synthetic/certification Broker environments、pytest fault/reconciliation tests。

---

## Task 1: 冻结 L2/Live qualification policy 与安全边界

**Files:**

- Create: `packages/domain/src/astraquant_domain/live_readiness.py`
- Create: `packages/api/src/astraquant_api/live_capabilities.py`
- Create: `docs/architecture/live-qualification-boundary.md`
- Test: `tests/domain/test_live_readiness.py`
- Test: `tests/api/test_live_capabilities.py`

- [ ] 先测试默认 capability set 只有 `READ_MARKET_DATA`、`READ_BROKER_ACCOUNT`、`SIMULATE_ORDERS`；没有 `SEND_LIVE_ORDER`，任何 route/service construction 都不能获得发送方法。
- [ ] qualification policy 固定 data continuity/timestamp/schema/permission、queue model、gateway callback/reconciliation、risk/halt/recovery/operations/evidence gates 和 reviewer approvals。
- [ ] 结论枚举只有 `NOT_READY`、`READY_FOR_LIVE_DESIGN`；没有“自动开启 Live”。缺字段、演练或真实证据默认 NOT_READY。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 immutable readiness evidence/capability factory；文档明确本阶段网络/API 只读和 certification/simulation 边界。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(governance): 冻结L2与实盘资格边界"`

## Task 2: 重新调研并资格测试 L2 endpoints

**Files:**

- Create: `tools/data/qualify_l2_provider.py`
- Create: `packages/data/src/astraquant_data/l2_schema.py`
- Create: `packages/data/src/astraquant_data/l2_quality.py`
- Test: `tests/data/test_l2_schema.py`
- Test: `tests/data/test_l2_quality.py`
- Test: `tests/research/test_l2_provider_qualification.py`

- [ ] 实施开始时重新核查当前可用官方/Broker/商业 API，实现同一资格矩阵比较 timestamps、sequence、depth、order/trade identifiers、auction、cancel flags、revisions、permission、history/retention、rate/stream limits；不因 Eastmoney 已用于日线就预选它。
- [ ] 先测试 L2 normalization 保存 exchange/source/receive/record times、sequence/reset, bid/ask levels+qty、order/trade events、auction/session/status、unit/tick/source row；缺/倒退/重复/gap 可检测。
- [ ] 资格 CLI 沿用 Phase 1 identity/report/approval/capture，不把 API 自带样例或录制公开数据当 formal。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 schema/quality/qualification probes；每个 endpoint/capability 单独批准，原始 L2/凭据不进 Git。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 建立L2数据源资格与规范"`

## Task 3: 建立连续 L2 capture、coverage 与 replay snapshots

**Files:**

- Create: `packages/data/src/astraquant_data/l2_capture.py`
- Create: `packages/api/src/astraquant_api/l2_data_worker.py`
- Create: `packages/api/migrations/versions/0017_l2_qualification.py`
- Modify: `packages/api/src/astraquant_api/schema_registry.py`
- Create: `tests/data/test_l2_capture.py`
- Create: `tests/api/test_l2_data_worker.py`
- Modify: `tests/api/test_schema_registry.py`
- Create: `tests/integration/test_l2_snapshot_lineage.py`

- [ ] 先测试 reconnect/sequence reset/gap/duplicate/out-of-order/backpressure/clock drift/day rollover；gap 区间明确，不以重连后最新 book 静默补历史。
- [ ] 0017 保存 L2 qualification/capture/coverage/readiness summaries 与 digest，`down_revision="0016_intraday_t"`；同步更新 schema registry 与真实 0016→head parity test；不复制 raw payload。
- [ ] Worker 只产 sealed chunks/result message，API 单写 catalog；磁盘/队列阈值触发 fail-closed pause 和 alert，不丢数据后继续宣称 continuous。
- [ ] L2 snapshot 固定 reconstruction policy、gap map、latency distribution、clock calibration 和 Phase 1 evidence chain。
- [ ] 运行目标 tests，确认红灯后实现 capture/worker/migration，最终全绿。
- [ ] 提交：`git commit -m "feat(data): 持续采集并发布L2回放快照"`

## Task 4: 先建立 OFI/queue baseline 与 hftbacktest 差分

**Files:**

- Create: `packages/research/src/astraquant_research/l2_features.py`
- Create: `packages/research/src/astraquant_research/baselines/order_book.py`
- Create: `runners/oracles/hftbacktest/pyproject.toml`
- Create: `runners/oracles/hftbacktest/uv.lock`
- Create: `runners/oracles/hftbacktest/.python-version`
- Create: `runners/oracles/hftbacktest/runner-manifest.json`
- Create: `runners/oracles/hftbacktest/src/astraquant_hftbacktest_oracle/__main__.py`
- Create: `tests/research/test_l2_features.py`
- Create: `tests/research/test_order_book_baselines.py`
- Create: `tests/differential/test_queue_replay.py`

- [ ] 先测试 OFI/queue imbalance/microprice/spread/depth/arrival-cancel features 只使用 decision-time reconstructed book；gap/reset/uncertain queue 产生 mask/fidelity，不 forward-fill。
- [ ] 先跑 no-trade、top-of-book、OFI/imbalance、simple queue/latency baselines；复杂 LOB 模型必须击败这些净成本基线。
- [ ] 固定 hftbacktest official commit/env/lock/queue assumptions；它只裁判明确的 queue/latency invariants，不裁判 A 股 T+1/费用/账户。
- [ ] 运行目标 tests，确认红灯后实现 features/baselines/isolated runner/recorded diffs。
- [ ] 提交：`git commit -m "feat(research): 建立盘口与队列回放基线"`

## Task 5: 在数据成熟后评估 DeepLOB/TLOB challenger

**Files:**

- Create: `packages/research/src/astraquant_research/l2_readiness.py`
- Create: `runners/lob-models/runner-manifest.json`
- Create: `runners/lob-models/pyproject.toml`
- Create: `runners/lob-models/uv.lock`
- Create: `runners/lob-models/.python-version`
- Create: `runners/lob-models/src/astraquant_lob_runner/__main__.py`
- Create: `tests/research/test_l2_readiness.py`
- Create: `tests/research/test_lob_tournament.py`

- [ ] readiness gate 至少要求 policy 冻结的连续 session 数、gap/clock/coverage/fidelity、有效独立样本/MinTRL 和 post-release holdout；设计中的 60/10/next5 只是启动下限，证据不足不启动深度模型。
- [ ] 重新核查并固定 MLPLOB/DeepLOB/TLOB 官方实现 full commits、locks、patch/checkpoint/training cutoffs；禁止从论文榜单或公开样例成绩推断 Astra alpha。
- [ ] 同 OFI baselines 使用 exact snapshots/folds/cost/latency/capacity/seeds/budgets；所有结果通过 Phase 4 Trial Ledger/lockbox。
- [ ] 先写 readiness/tournament tests；数据不足时预期结果是 skipped+INSUFFICIENT_EVIDENCE，而不是失败后放宽门。
- [ ] 实现 isolated runner/tournament adapters，主 runtime 不安装模型依赖。
- [ ] 提交：`git commit -m "feat(research): 受控评估盘口深度模型"`

## Task 6: 资格测试 vn.py TORA/XTP gateway report adapters

**Files:**

- Create: `runners/gateways/vnpy/runner-manifest.json`
- Create: `runners/gateways/vnpy/pyproject.toml`
- Create: `runners/gateways/vnpy/uv.lock`
- Create: `runners/gateways/vnpy/.python-version`
- Create: `runners/gateways/vnpy/src/astraquant_vnpy_gateway_runner/__main__.py`
- Create: `runners/gateways/vnpy/src/astraquant_vnpy_gateway_runner/report_mapper.py`
- Create: `packages/execution/src/astraquant_execution/gateways/contracts.py`
- Create: `packages/execution/src/astraquant_execution/gateways/vnpy_report_adapter.py`
- Create: `tests/fixtures/broker_certification/tora/manifest.json`
- Create: `tests/fixtures/broker_certification/xtp/manifest.json`
- Create: `tests/execution/test_vnpy_report_adapter.py`
- Create: `tests/integration/test_gateway_certification_replay.py`
- Create: `runners/gateways/vnpy/tests/test_report_mapper.py`

- [ ] 隔离 runner 内 `report_mapper.py` 可以 import vn.py；主 runtime 的 `vnpy_report_adapter.py` 只消费 versioned neutral report JSON/domain events，repository test 明确断言 `packages/execution` 无 vnpy import。两边都不调用 send/cancel API，真实 command gateway interface 不在默认 package export。
- [ ] 用券商 certification/synthetic 录制覆盖 fill-before-ACK、late/duplicate、cancel race、reject、partial、disconnect/reconnect、four-table same watermark、external orders/cash/corporate action。
- [ ] 映射 sellable/frozen/yd volume、fees/taxes、timestamps/ids 不全时进入 reconciliation/fidelity reason，不猜值。
- [ ] 运行 runner-local mapper tests 与 `python -m astraquant_vnpy_gateway_runner --record-certification ...`，candidate trace 经脱敏、schema/digest 校验和人工批准后才写 must-not-exist/superseding certification fixture；再运行主 adapter/recorded replay tests。TORA/XTP 未取得真实 certification evidence 时各自 NOT_READY。
- [ ] 提交：`git commit -m "test(gateway): 验证vn.py券商回报适配"`

## Task 7: 演练 halt、恢复、只读对账与操作告警

**Files:**

- Create: `packages/api/src/astraquant_api/live_readiness_service.py`
- Create: `packages/api/src/astraquant_api/live_readiness_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Create: `tests/api/test_live_readiness_service.py`
- Create: `tests/api/test_live_readiness_routes.py`
- Create: `tests/integration/test_live_readiness_drills.py`
- Create: `docs/operations/live-readiness-drills.md`

- [ ] 先测试 data stale/time reversal/schema drift、policy/hash mismatch、journal imbalance、report duplication/gap、Broker discrepancy、disk/clock/process failure 触发 no-new-orders/read-only reconciliation/HALTED。
- [ ] 只读 Broker 对账、进程重启、snapshot+journal replay、manual compensation approval、credential revoke、alert acknowledgement 全部在 certification/simulation 环境演练并保存 evidence digest。
- [ ] routes 只查询 readiness/启动演练/确认告警，不暴露真实 submit/cancel；测试尝试发送真实 order 返回 capability unavailable。
- [ ] 实现 service/routes/runbook，任何自动 fallback 或在线改参均禁止。
- [ ] 运行 API/integration tests，期望全绿。
- [ ] 提交：`git commit -m "test(operations): 演练实盘前故障与对账恢复"`

## Task 8: 生成 Live 设计审批包并停止

**Files:**

- Create: `tools/verification/verify_phase_7.py`
- Create: `docs/verification/quant-core-v3/phase-7-signoff.md`
- Create: `docs/operations/live-design-approval-package.md`

- [ ] 运行：

```powershell
uv run pytest tests/data/test_l2_schema.py tests/data/test_l2_quality.py tests/data/test_l2_capture.py tests/research/test_l2_provider_qualification.py tests/research/test_l2_features.py tests/research/test_order_book_baselines.py tests/research/test_l2_readiness.py tests/research/test_lob_tournament.py tests/differential/test_queue_replay.py tests/execution/test_vnpy_report_adapter.py tests/integration/test_l2_snapshot_lineage.py tests/integration/test_gateway_certification_replay.py tests/integration/test_live_readiness_drills.py tests/api/test_schema_registry.py tests/api/test_l2_data_worker.py tests/api/test_live_readiness_service.py tests/api/test_live_readiness_routes.py tests/api/test_live_capabilities.py -q
uv run ruff check packages tools tests
uv run ruff format --check packages tools tests
uv run mypy
```

- [ ] 用 SEALED evidence manifest 运行 verifier；缺 L2/provider/coverage/queue/model/gateway/certification/drill 任一 required evidence 时返回 NOT_READY：

```powershell
$phase7EvidenceManifest = $env:ASTRAQUANT_PHASE7_EVIDENCE_MANIFEST
if ([string]::IsNullOrWhiteSpace($phase7EvidenceManifest)) { throw 'ASTRAQUANT_PHASE7_EVIDENCE_MANIFEST is required' }
$phase7RunId = [guid]::NewGuid().ToString('n')
uv run python tools/verification/verify_phase_7.py --evidence-manifest $phase7EvidenceManifest --output "artifacts/verification/phase-7/$phase7RunId/verification.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

- [ ] approval package 固定 L2/provider/coverage/model/queue/gateway/Broker certification/risk/drill/operations digests、未闭合风险、支持账户/市场边界和建议结论。
- [ ] 结论为 NOT_READY 时列出未通过机器门，不提出临时绕过；结论为 READY_FOR_LIVE_DESIGN 时也不创建 send-order capability、不连接生产账户、不改运行开关。
- [ ] 将结果交给用户单独审批；只有收到明确批准后，另用 brainstorming+writing-plans 新建 LIVE architecture spec、最小资金 canary、权限分离、kill switch 和 rollback plan。
- [ ] 提交：`git commit -m "docs(operations): 完成L2与实盘设计资格包"`

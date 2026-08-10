# Quant Core v3 Phase 1c RuleBook and Reference Data Stage Roadmap

> **Execution gate:** 本文件是阶段路线图，不是可直接执行的 micro implementation plan。开始任何 Task 前，必须先用 `superpowers:writing-plans` 为该 Task 编写并审阅独立微计划，至少给出精确 symbol/signature/DDL、完整红灯测试、命令及预期失败、最小实现和原子提交；随后才可用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。本文 checkbox 只表示里程碑，不授权按未展开描述直接编码。

**Goal:** 建立带生效期、官方来源和不可变 hash 的 A 股 RuleBook/Fee/Tax/Settlement/Valuation 输入，以及真实 API 驱动的历史 universe、证券状态、公司行动和每日动态交易事实。

**Architecture:** 静态政策与每日事实分离：RuleBook 保存公式/申报单位/回转类别/条款状态，`InstrumentSessionSnapshot` 保存前收、实际涨跌停、ST/停牌/阶段和可交易状态。所有 policy/reference data 都作为 snapshot v2 角色进入递归 evidence gate；缺失、冲突或暂缓条款默认禁止相关 instrument 新单。

**Tech Stack:** Python 3.12、immutable domain contracts、snapshot v2、SQLite/Alembic catalog、official-source evidence records、pytest canonical date scenarios。

---

## Task 1: 冻结 RuleBook/Fee/Tax/Settlement/Valuation 契约

**Files:**

- Create: `packages/domain/src/astraquant_domain/rules.py`
- Create: `packages/domain/src/astraquant_domain/corporate_actions.py`
- Create: `packages/domain/src/astraquant_domain/valuation.py`
- Create: `packages/domain/src/astraquant_domain/fees.py`
- Test: `tests/domain/test_rules.py`
- Test: `tests/domain/test_policy_contracts.py`

- [ ] 先测试每个 policy 有 market/instrument scope、effective interval、clause status、source record/hash、version/hash；overlap 冲突、缺 source、open-ended guessed rule 和客户端传入 exemption 全部拒绝。
- [ ] 定义 `RuleBook`、`InstrumentSessionSnapshot`、`CashSettlementRule`、`FeeProfile/FeeRule`、`TaxProfile/TaxCollectionPolicy`、`ValuationPolicy`，但本阶段不实现账户扣账。
- [ ] 先测试 T+N/sellability/settlement 是独立属性，不允许用 `market_tplus` 一个布尔值覆盖全部证券类型。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 immutable contracts；FeeRule 固定 scope/timing/rounding/rates，某笔订单的 FeeChargeUnit 留给 Phase 2。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(domain): 建立版本化市场政策契约"`

## Task 2: 实现 official rule evidence 与 rulebook store

**Files:**

- Create: `packages/data/src/astraquant_data/official_rules.py`
- Create: `packages/data/src/astraquant_data/official_document_store.py`
- Create: `packages/data/src/astraquant_data/rulebook_store.py`
- Create: `packages/api/migrations/versions/0012_rulebook_reference_data.py`
- Modify: `packages/api/src/astraquant_api/schema_registry.py`
- Test: `tests/data/test_official_rules.py`
- Test: `tests/data/test_official_document_store.py`
- Test: `tests/data/test_rulebook_store.py`
- Modify: `tests/api/test_migration_config.py`
- Modify: `tests/api/test_schema_registry.py`

- [ ] 先测试官方网页/PDF/券商费率确认书保存不可变原始 bytes/text、MIME、source URL/document digest、retrieved/official publication/effective times、clause locator、reviewer 和 supersedes；只存 URL/digest 或今天抓到就声称今天生效都必须失败。原文进入受保护 evidence store，不提交 Git。
- [ ] 先测试同一 market/instrument/date/session 必须解析到唯一完整 rule set；冲突、暂缓、无历史版本、source 被撤销均返回 fail-closed reason。
- [ ] 先测试 `formal_history_start` 至当前日期的 RuleBook/Fee/Tax/Settlement coverage map 连续；首批正式回放若从 2010 开始，就必须导入覆盖 2010→现在的所有实际生效版本，不能只导入当前费税规则。缺口必须列出日期/角色并 fail closed。
- [ ] 运行目标 tests，确认红灯。
- [ ] 在 `0012_rulebook_reference_data.py` 创建 official evidence/document、RuleBook/Fee/Tax/Settlement/Valuation policy、historical coverage、instrument lifecycle/universe/status、corporate action 和 session snapshot catalog tables，`down_revision="0011_snapshot_v2"`；实现 append-only evidence record/importer 与 resolver，政策修改创建新版本，不覆盖历史；同步更新 schema registry 与真实 0011→head parity test。
- [ ] 首批只导入上交所/深交所普通现金账户已核实条款；北交所、港股通、融资融券显式 `UNSUPPORTED`。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 持久化官方交易规则证据"`

## Task 3: 资格测试并采集真实 reference endpoints

**Files:**

- Create: `packages/data/src/astraquant_data/reference_capture.py`
- Create: `packages/data/src/astraquant_data/adapters/eastmoney_reference.py`
- Modify: `packages/data/src/astraquant_data/eastmoney_protocol.py`
- Modify: `packages/data/src/astraquant_data/eastmoney_client.py`
- Modify: `tools/eastmoney_bridge.py`
- Create: `tools/data/qualify_reference_endpoints.py`
- Create: `tools/data/capture_reference_data.py`
- Test: `tests/data/test_reference_capture.py`
- Test: `tests/data/test_eastmoney_reference.py`
- Modify: `tests/data/test_eastmoney_protocol.py`
- Modify: `tests/data/test_eastmoney_client.py`
- Modify: `tests/repository/test_eastmoney_bridge.py`
- Create: `tests/research/test_reference_endpoint_qualification.py`

- [ ] 先测试 security master/lifecycle、historical universe/constituents、ST/停复牌、exchange calendar、corporate actions 与 daily session facts 都是独立 provider endpoint/capability；行情 endpoint approval 不能自动覆盖它们。
- [ ] 先测试每类响应必须经过 Phase 1a ProviderQualification→CaptureEnvelope/Store，保存 request/raw/page/schema/unit/time/revision lineage；本地 YAML/CSV、开源数据包或人工表不能成为 formal reference ancestor。
- [ ] 对 Eastmoney 当前 interface 逐 endpoint 真实 probe；它无法提供或无法证明 PIT/vintage/退市覆盖的角色保持 UNQUALIFIED，并用同一矩阵核查官方/Broker/其他真实 API，不以静态常识补值。
- [ ] 运行 `uv run pytest tests/data/test_reference_capture.py tests/data/test_eastmoney_reference.py tests/research/test_reference_endpoint_qualification.py -q`，确认红灯。
- [ ] 扩展现有 protocol/client/bridge 的 security master/status/calendar/corporate-action request methods、分页与 `PROVIDER_RAW_BYTES|SDK_OBJECT_CANONICAL` evidence fields；再实现 generic reference capture 与 Eastmoney adapter/CLI。adapter 只产 L0 capture，不直接写 normalized tables 或 SQLite。
- [ ] 重跑 tests；没有每个 required role 的实际 approval/capture digest 时，Phase 1 final verifier 必须返回 NOT_READY。
- [ ] 提交：`git commit -m "feat(data): 采集真实接口参考对象证据"`

## Task 4: 建立历史 instrument lifecycle/universe/status

**Files:**

- Create: `packages/data/src/astraquant_data/instruments.py`
- Create: `packages/data/src/astraquant_data/universe.py`
- Create: `packages/data/src/astraquant_data/instrument_status.py`
- Test: `tests/data/test_instruments.py`
- Test: `tests/data/test_universe.py`
- Test: `tests/data/test_instrument_status.py`

- [ ] 先测试上市、退市、代码/市场映射、ST interval、停复牌、指数成分/权重都按 source effective/available/vintage 时间版本化。
- [ ] 测试 2018 universe 不能由 2026 当前列表回填；delisted instrument 仍能出现在历史 snapshot 与 coverage denominator。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 normalized reference tables 和 snapshot materialization，全部保留 capture row lineage。
- [ ] 缺 historical universe/status 的区间降低 `pit_fidelity` 或阻止要求该角色的 formal run，不用“通常可交易”补值。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 建立历史证券与样本空间真相"`

## Task 5: 建立公司行动与研究复权输入

**Files:**

- Create: `packages/data/src/astraquant_data/corporate_actions.py`
- Create: `packages/data/src/astraquant_data/adjustment.py`
- Test: `tests/data/test_corporate_actions.py`
- Test: `tests/data/test_adjustment.py`

- [ ] 先测试 record/ex/pay dates、cash/stock dividend、split/rights、entitlement、source vintage 和 revision lineage；raw OHLCV 始终不复权。
- [ ] 先测试研究复权只从 raw price+point-in-time corporate action 生成派生 snapshot，训练/推理使用同一 frozen processor；不得将 adjusted vendor bars 伪装 raw。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 company-action canonical records 与 deterministic adjustment processor；cash distribution 与 price mark 不双计。
- [ ] tax holding lot/FIFO/补扣金额的执行处理留给 Phase 2，但当前输出完整 entitlement/tax-base evidence 或明确 `TAX_BASE_UNKNOWN`。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 建立公司行动与研究复权输入"`

## Task 6: 生成 InstrumentSessionSnapshot

**Files:**

- Create: `packages/data/src/astraquant_data/session_snapshots.py`
- Test: `tests/data/test_session_snapshots.py`
- Modify: `packages/api/src/astraquant_api/snapshot_publication_service.py`

- [ ] 先测试 session snapshot 包含 previous close、官方/真实 API limit up/down、ST、suspension、new-listing stage、trading state、lot/tick/cage inputs、visible/effective times、source/hash。
- [ ] 测试动态实际涨跌停缺失时不能只用静态公式猜测并允许下单；reference revision 创建新 vintage，不改旧 replay。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 session materializer，把 RuleBook 与当日 reference roles 绑定到 exact parent snapshots；结果通过 snapshot v2 publication ledger 发布。
- [ ] API publication service 校验 role completeness，缺一角色只发布 quarantine/exploratory report。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(data): 发布每日动态交易事实快照"`

## Task 7: 建立账户级 FeeProfile/TaxProfile 审批 API

**Files:**

- Create: `packages/api/src/astraquant_api/policy_repository.py`
- Create: `packages/api/src/astraquant_api/policy_schemas.py`
- Create: `packages/api/src/astraquant_api/policy_routes.py`
- Modify: `packages/api/src/astraquant_api/app.py`
- Test: `tests/api/test_policy_repository.py`
- Test: `tests/api/test_policy_routes.py`

- [ ] 先测试用户真实券商费率以 evidence-backed version 创建，佣金/最低佣金/印花税/过户费/规费按 market/instrument/date/side 条件保存；symbol 前缀和客户端 `stamp_duty_exempt` 不可决定政策。
- [ ] 先测试 policy 只能 append/supersede/revoke，已 sealed run 继续引用旧 hash；无生效 policy 的 formal order/replay fail closed。
- [ ] 运行目标 tests，确认红灯。
- [ ] 实现 authenticated command/query 和 audit log；secret/account identifiers 使用现有 SecretStore/opaque account id，不写文档或日志。
- [ ] UI 配置晚于 execution projection，本阶段只提供 API 与明确 evidence status。
- [ ] 重跑 tests，期望全绿。
- [ ] 提交：`git commit -m "feat(api): 管理真实账户费用与税务政策"`

## Task 8: Phase 1 总证据闭包验收

**Files:**

- Create: `tests/integration/test_rulebook_snapshot_lineage.py`
- Create: `tools/verification/verify_phase_1.py`
- Create: `docs/verification/quant-core-v3/phase-1-signoff.md`
- Modify: `docs/research/open-source-comparison.md`

- [ ] 用合格真实 API capture + official rule evidence 生成 exact market/reference/rule/session snapshot set，递归验证每个 role 的 lineage、visible time 和 hash chain。
- [ ] 注入缺 RuleBook、冲突 effective interval、当前 universe 回填、动态 limit 缺失、adjusted raw、公司行动 revision 和 unknown tax base，全部产生规定的 fail-closed/fidelity 状态。
- [ ] 运行：

```powershell
uv run pytest tests/domain/test_rules.py tests/domain/test_policy_contracts.py tests/data/test_official_rules.py tests/data/test_official_document_store.py tests/data/test_rulebook_store.py tests/data/test_reference_capture.py tests/data/test_eastmoney_reference.py tests/data/test_eastmoney_protocol.py tests/data/test_eastmoney_client.py tests/repository/test_eastmoney_bridge.py tests/data/test_instruments.py tests/data/test_universe.py tests/data/test_instrument_status.py tests/data/test_corporate_actions.py tests/data/test_adjustment.py tests/data/test_session_snapshots.py tests/research/test_reference_endpoint_qualification.py tests/api/test_migration_config.py tests/api/test_schema_registry.py tests/api/test_policy_repository.py tests/api/test_policy_routes.py tests/integration/test_rulebook_snapshot_lineage.py -q
uv run ruff check packages/domain/src packages/data/src packages/api/src tools/verification tests
uv run ruff format --check packages/domain/src packages/data/src packages/api/src tools/verification tests
uv run mypy
```

- [ ] 用只包含 exact approved capture/snapshot/policy IDs 的 SEALED manifest 调用 verifier；缺 manifest 或任一 required reference role 时必须失败：

```powershell
$phase1InputManifest = $env:ASTRAQUANT_PHASE1_INPUT_MANIFEST
if ([string]::IsNullOrWhiteSpace($phase1InputManifest)) { throw 'ASTRAQUANT_PHASE1_INPUT_MANIFEST is required' }
$phase1RunId = [guid]::NewGuid().ToString('n')
uv run python tools/verification/verify_phase_1.py --input-manifest $phase1InputManifest --output "artifacts/verification/phase-1/$phase1RunId/verification.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

- [ ] 核对 Phase 1 总退出门：formal roles 祖先合格=100%；`formal_history_start`→现在 RuleBook/Fee/Tax/Settlement coverage=100%；RuleBook/session/policy 缺失仍交易=0；历史 universe/status 被当前状态回填=0；同 snapshot 可复现；所有未实证 endpoint/capability 保持未批准。
- [ ] 更新开源比较文档，明确开源项目不提供产品真实数据，训练/回放只消费 Astra 从真实 API 发布的 snapshots。
- [ ] 提交：`git commit -m "test(data): 完成规则与参考数据证据闭包"`

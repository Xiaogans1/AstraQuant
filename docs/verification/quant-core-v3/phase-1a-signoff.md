# Quant Core v3 Phase 1a Sign-off

## 当前结论

`PENDING_REAL_EVIDENCE`。Phase 1a 的 provider identity、qualification、approval、不可变 raw capture、正式采集 worker、增量血缘与 capture reconciliation 实现已经具备，但当前工作区没有受控环境生成的真实 Eastmoney evidence manifest，因此本文件不声称 Phase 1a 已通过。

## 明确缺失

- 没有可供本地签核的外部 `REAL_API` evidence manifest。
- 没有同时覆盖 `DAILY_BARS` 与 `MINUTE_BARS` 的真实 qualification probe captures、人工 approval、sealed formal captures 和 `MATCH` reconciliation reports。
- `CORPORATE_ACTIONS` 与 `INSTRUMENT_STATUS` 在 Phase 1c 接入真实 reference endpoint 前保持 `UNQUALIFIED`。

## 已实现的机器门

`tools/verification/verify_phase_1a.py` 会：

- 拒绝 `TEST_ONLY`、仓库内 fixture、相对路径、mutable/sentinel digest 和 secret-like manifest 字段；
- 重验 qualification probe CaptureStore 正文，并把报告中的每个 request/response digest 追溯到 sealed probe chunk；
- 重算 QualificationReport、ProviderApproval、formal CaptureEnvelope、chunk 与 reconciliation report 摘要；
- 要求日报与分钟能力均完成批准和 sealed capture，且 reconciliation 为 `MATCH`；
- 生成统一 verification JSON 与 sealed TEST RunManifest；任一检查失败均返回非零。

## 正式运行方式

```powershell
$phase1aEvidenceManifest = $env:ASTRAQUANT_PHASE1A_EVIDENCE_MANIFEST
if ([string]::IsNullOrWhiteSpace($phase1aEvidenceManifest)) { throw 'ASTRAQUANT_PHASE1A_EVIDENCE_MANIFEST is required' }
$phase1aRunId = [guid]::NewGuid().ToString('n')
uv run python tools/verification/verify_phase_1a.py --evidence-manifest $phase1aEvidenceManifest --output "artifacts/verification/phase-1a/$phase1aRunId/verification.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

输出目录必须不存在；`artifacts/` 不提交 Git。只有真实运行返回 0 后，才允许用独立 docs-only commit 补充 implementation commit、verification artifact digest、RunManifest digest、覆盖范围和 PASS 检查表。

## 权限边界

当前状态不授权 FORMAL snapshot publication、模型晋级或 LIVE 委托。fixture 与 pytest 生成物只能证明验证器行为，永远不能替代真实 API 证据。

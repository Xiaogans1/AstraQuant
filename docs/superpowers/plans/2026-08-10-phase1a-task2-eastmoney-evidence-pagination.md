# Phase 1a Task 2 Eastmoney Evidence and Pagination 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development task-by-task.

**Goal:** 在不破坏旧实时行情调用的前提下，为 Eastmoney bridge/client 增加版本化 NDJSON、SDK canonical-object 证据、显式区间分页和 fail-closed 完整性校验。

**Architecture:** bridge 每个请求/响应携带 `astraquant.eastmoney-bridge/v1` 和 correlation id；成功响应返回 `result + evidence`，其中 SDK 未提供 HTTP bytes 时固定声明 `SDK_OBJECT_CANONICAL`、serialization version、observed schema、SDK build、permission tier、requested/received timestamps。client 公开低层 `call_with_evidence()`，旧 `current/history_n` 仍只投影 result。历史批量读取使用显式 `[start,end]` page specs；页集合校验 cursor、边界、重复/遗漏、declared total、schema/units/adjust 一致性，任何无法证明的情况抛 typed completeness error。

**Tech Stack:** Python 3.12、NDJSON、frozen dataclasses、SHA-256 canonical JSON、pytest、Ruff、mypy。

---

## Task 1: 冻结 bridge envelope 与证据对象

**Files:**

- Modify: `tools/eastmoney_bridge.py`
- Modify: `packages/data/src/astraquant_data/eastmoney_protocol.py`
- Modify: `packages/data/src/astraquant_data/eastmoney_client.py`
- Modify: `tests/repository/test_eastmoney_bridge.py`
- Modify: `tests/data/test_eastmoney_protocol.py`
- Modify: `tests/data/test_eastmoney_client.py`
- Modify: `tests/fixtures/eastmoney/fake_bridge.py`

- [ ] 红灯：请求缺/错 contract version、response correlation/version 不匹配、未知 representation/schema 立即 `EastmoneyBridgeProtocolError`。
- [ ] 红灯：`BridgeCallEvidence` 包含 canonical request digest、canonical SDK response digest、`SDK_OBJECT_CANONICAL`、serialization version、SDK build、permission、requested/received UTC 时间、observed schema；token/secret 不进入证据或 stdout。
- [ ] 实现 `BridgeResponse`/`BridgeCallEvidence` 解析和稳定 digest；bridge 从已配置上下文报告 build/permission，SDK object 经版本化 JSON serializer 后才 hash。
- [ ] 保持 `current/history_n/search_symbols/trading_dates` 的返回类型兼容。
- [ ] 运行目标 tests、Ruff、mypy，提交 `feat(data): 版本化Eastmoney调用证据`。

## Task 2: 显式区间分页与完整性状态机

**Files:**

- Modify: `tools/eastmoney_bridge.py`
- Modify: `packages/data/src/astraquant_data/eastmoney_protocol.py`
- Modify: `packages/data/src/astraquant_data/eastmoney_client.py`
- Modify: `tests/repository/test_eastmoney_bridge.py`
- Modify: `tests/data/test_eastmoney_protocol.py`
- Modify: `tests/data/test_eastmoney_client.py`
- Modify: `tests/fixtures/eastmoney/fake_bridge.py`

- [ ] 红灯：`history_range` 必须显式 symbol/frequency/start/end/adjust/page cursor；禁止空边界、反向区间和非法 adjust。
- [ ] 红灯故障矩阵：重复页、遗漏 cursor、边界越界/重叠、静默截断、success+空数据、out-of-order、schema/单位/adjust drift 分别抛稳定 typed failure code。
- [ ] 实现 immutable `HistoryPage`、`PageEvidence`、`HistoryBatch` 和 `validate_history_pages()`；完整性只来自显式 expected page specs + 每页证据/declared count，不以短页猜最后一页。
- [ ] bridge 调 `gm.history(start_time,end_time,...)`；结果 envelope 带 page index/count/range/returned count/declared total（不可得则 null 并标 availability），client 只在外部 expected rows/calendar proof 或 provider declared total闭合时 seal complete。
- [ ] 运行四组目标 tests、Ruff、format、mypy，提交 `feat(data): 实施Eastmoney显式区间分页`。

## Task 3: Probe 安全回归与阶段交付

**Files:**

- Modify: `tools/eastmoney_probe.py`（仅在协议适配必要时）
- Modify: `tests/repository/test_eastmoney_probe.py`
- Modify: `docs/superpowers/plans/2026-08-10-quant-core-v3-phase-1a-provider-capture.md`

- [ ] 确认 aggregate probe 仍不输出 symbol/price/token/raw payload；正式 raw evidence 只走后续 formal qualification/capture root。
- [ ] 运行 `uv run pytest tests/repository/test_eastmoney_bridge.py tests/repository/test_eastmoney_probe.py tests/data/test_eastmoney_protocol.py tests/data/test_eastmoney_client.py -q`。
- [ ] 运行 `uv run ruff check tools/eastmoney_bridge.py tools/eastmoney_probe.py packages/data/src tests/repository tests/data`、format check、mypy。
- [ ] 勾选路线图 Task 2，范围检查后推送 `codex/quant-core-v3-phase1a-task2`，确认远端 SHA 和 CI；不创建/合并 PR。

## Acceptance

- 每个调用都有 contract/correlation/build/permission/schema/representation/timestamps/digests。
- SDK canonical object 不被标成 provider raw bytes；serializer/schema 变化会改变 evidence digest。
- 缺页、重复页、越界、截断、漂移均 fail closed；空区间与合法空结果必须通过显式 coverage proof 区分。
- 旧实时行情 API 与 aggregate probe 回归全绿，secret 仍不出现在 argv、日志、证据或 hash input。

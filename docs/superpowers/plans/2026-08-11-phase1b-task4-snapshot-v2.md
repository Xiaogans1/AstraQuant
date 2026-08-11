# Phase 1b Task 4 Snapshot v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立内容身份与发布身份分离、可原子落盘的正式 canonical snapshot v2。

**Architecture:** legacy `SnapshotManifest/ParquetSnapshotStore` 保持 v1 行为；v2 使用独立 `SnapshotManifestV2/CanonicalSnapshotStoreV2`。`content_digest` 绑定规范行情值、区间、规则、cutoff、coverage/quality、代码/环境和 parent content，但排除本地接收时间与 capture lineage；`snapshot_id` 再绑定具体 capture/raw/file/publication lineage。

**Tech Stack:** Python 3.12、frozen dataclasses、SHA-256、canonical JSON、PyArrow/Parquet、pytest、Ruff、mypy。

---

### Task 1: 冻结双身份 Manifest v2

**Files:**
- Create: `packages/data/src/astraquant_data/snapshot_v2.py`
- Modify: `packages/data/src/astraquant_data/manifests.py`
- Create: `tests/data/test_snapshot_v2.py`

- [x] 红灯：相同区间/OHLCV/source revision 的重抓保持 `content_digest`，不同 capture/file/publication 产生不同 `snapshot_id`。
- [x] 红灯：修改 cutoff、availability/revision policy、vintage mode、coverage/quality、代码/环境或 parent content 改变 `content_digest`；修改任一 file byte/hash 改变 `snapshot_id`。
- [x] 红灯：v2 固定 captures/raw/files、parents/supersedes、evidence、PIT/revision/availability、coverage/quality、code/environment；未知/缺失/sentinel digest fail closed。
- [x] 实现 `SnapshotContentV2`、`SnapshotPublicationV2`、`SnapshotFileV2`、`SnapshotManifestV2.create()/to_json()/from_path()` 与稳定 observation content projection。
- [x] 保持 v1 `SnapshotManifest.from_path()` 和 `to_evidence_ref()` 返回 legacy，不自动升级。

### Task 2: 原子 Canonical Parquet Store

**Files:**
- Modify: `packages/data/src/astraquant_data/parquet_store.py`
- Modify: `tests/data/test_parquet_store.py`

- [x] 红灯：v2 writer 只接受 canonical observations 和已冻结 content/publication metadata；写入 canonical Arrow schema。
- [x] 红灯：manifest 写完并 fsync 后才 atomic rename；写盘/manifest 失败只留不可见 staging，queryable snapshot path 不出现。
- [x] 红灯：相同 publication 幂等返回；相同 snapshot id 的不同 manifest/file 触发 collision；未 seal staging 永不视为 published。
- [x] 实现 `CanonicalSnapshotStoreV2.publish()`、分区 writer、file hash/row count 重验和原子 commit；不切换 legacy API/UI store。
- [x] 运行 snapshot/parquet/evidence/query legacy tests、Ruff、mypy、全仓门禁；更新路线图，提交并推送。

## Self-review

- Stable content 不包含 `observed_received_time/recorded_time/first_received_time/capture lineage`，否则重抓会错误地产生新内容；exact source revision 和值必须包含。
- File byte hash 属于 publication identity；canonical logical row digest 属于 content identity。
- Task 5 才将 v2 publication 接入 ledger/Merkle trusted head；Task 4 只提供不可变原子 artifact，不提前声明 formal read 已受可信锚保护。

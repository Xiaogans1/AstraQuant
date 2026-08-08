# 本地行情数据运维

本文说明 AstraQuant Phase 2 的本地行情目录、导入方式、备份恢复与隐私边界。
当前仅支持开发环境；没有安装包、云端数据同步或自动保留策略。

## 最简单的启动方式

在仓库根目录执行：

```powershell
.\start.ps1
```

脚本会准备尚未安装的项目依赖，并启动 Tauri 桌面、本地 FastAPI 和 Worker。关闭桌面
窗口时，本地服务会一同受控关闭。默认数据目录是仓库根目录下的 `.astraquant/`。

如需把运行数据与源码彻底分开，可在启动前指定一个绝对目录：

```powershell
$env:ASTRAQUANT_STATE_DIR = "D:\AstraQuant-local"
.\start.ps1
```

## 分步开发命令

以下命令用于排障和单独开发组件，不是日常推荐启动方式：

```powershell
uv sync --all-packages
$env:ASTRAQUANT_STATE_DIR = "D:\AstraQuant-local"
$env:ASTRAQUANT_SESSION_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
uv run astraquant-api
```

另开一个位于仓库根目录的 PowerShell：

```powershell
pnpm --filter @astraquant/desktop dev
```

单独启动 Vite 不会管理本地 API 生命周期；完整桌面联调仍应使用 `.\start.ps1`。

## 本地目录结构

```text
<ASTRAQUANT_STATE_DIR>/
├─ state/
│  └─ astraquant.sqlite3        # 任务、目录、质量记录和本地设置
├─ data/
│  ├─ datasets/
│  │  └─ <dataset-id>/snapshots/<snapshot-id>/
│  │     ├─ manifest.json       # 内容寻址清单、来源和质量摘要
│  │     └─ market=cn/.../*.parquet
│  └─ features/snapshots/<feature-snapshot-id>/
│     ├─ manifest.json
│     └─ features.parquet
└─ logs/
   └─ *.jsonl
```

行情和特征快照均为不可变、内容寻址目录。同一输入、版本和参数会生成相同 ID；修改
已发布文件会使清单哈希校验失败。DuckDB 只能读取清单批准且位于数据根目录内的
Parquet 路径，调用方不能提交任意 SQL 或文件路径。

## 导入样例数据

打开桌面“数据中心”，选择：

- `浦发银行 · 600000.SSE`，用于 A 股日线闭环；
- `螺纹连续 · RB0.SHFE`，用于国内期货日线闭环。

选择日期范围和复权方式后点击“导入示例数据”。导入在独立 Worker 中运行，进度与
结果同时出现在数据中心和任务中心。fixture 数据离线生成，不访问互联网。

## 可选 AKShare

AKShare 默认关闭，因为其上游网页接口可能变化。仅在理解数据口径和合规要求后，
于启动前显式启用：

```powershell
$env:ASTRAQUANT_ENABLE_AKSHARE = "1"
$env:ASTRAQUANT_DATA_INSTRUMENTS = "600000.SSE,RB0.SHFE"
.\start.ps1
```

该开关只允许只读行情导入，不增加账户、资金、持仓或下单能力。生产研究前需自行
验证授权、交易日历、复权、连续合约和数据延迟。

## 备份与恢复

备份前先关闭 AstraQuant，确保 SQLite 与快照均已落盘，然后复制整个状态目录：

```powershell
Copy-Item -LiteralPath "D:\AstraQuant-local" `
  -Destination "E:\Backups\AstraQuant-local-2026-07-28" -Recurse
```

恢复时不要把两份状态目录混合覆盖。将完整备份复制到一个空目录，再通过
`ASTRAQUANT_STATE_DIR` 指向它并启动。恢复后先在数据中心核对数据集、快照数量和
质量报告，再进行研究。

Phase 2 不支持手工删除单个快照。不要直接删除 Parquet、清单或 SQLite 目录行；
这会破坏目录一致性。后续保留策略将以“先检查引用、再原子归档/删除”的工作流提供。
当前若要清空开发状态，应先关闭程序，并仅对用户明确选择的整个状态目录执行备份后
清理。

## 永久安全边界

- 数据只保存在用户选择的本地目录，不上传 AstraQuant 服务器。
- API 仅监听 `127.0.0.1`，并使用每次桌面会话随机生成的 Bearer 令牌。
- 仓库策略拒绝提交 Parquet、DuckDB、SQLite、下载 CSV、模型权重和状态目录。
- AstraQuant 永久不保存券商/期货账户凭据，不连接 CTP/券商交易接口，不发送真实
  委托。
- AI 后续只生成结构化买卖点、仓位和风险提示；真实交易由用户在外部软件人工完成。

## 常见故障

- “本地数据服务暂时离线”：确认桌面仍在运行；查看 `.astraquant/logs/` 或自定义
  状态目录下的 `logs/`。
- 导入被拒绝：检查标的是否在 `ASTRAQUANT_DATA_INSTRUMENTS` 白名单内，以及
  AKShare 是否已显式启用。
- 快照未出现：在任务中心确认 `data.import` 是否到达 `SUCCEEDED`；数据中心会每
  3 秒刷新本地目录。
- 清单或 Parquet 哈希错误：停止使用该快照，从完整备份恢复；不要修改已发布文件。

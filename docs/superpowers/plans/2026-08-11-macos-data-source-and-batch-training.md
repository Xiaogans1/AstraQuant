# macOS 数据源与批量训练数据计划

日期：2026-08-11
状态：P0 已完成，进入 P1 认证数据源资格验证
适用范围：macOS 开发运行、A 股/ETF/指数行情、全市场批量分钟数据、后续训练数据扩展与未来 Broker Gateway

## 1. 结论摘要

AstraQuant 已能在 Apple Silicon macOS 上安装完整工具链并启动 Tauri、FastAPI、Python
数据科学依赖与本地 SQLite/Parquet 运行时。当前阻塞不是桌面平台，而是实时行情入口在
`astraquant_api.cli`、配置、凭据和 UI 中仍绑定东财 `gm` SDK。

数据和执行必须拆成两条独立通道：

```text
热路径：认证实时行情/Broker 行情 → 在线特征 → Signal/Target → Paper/未来 Broker Gateway
冷路径：AKShare 批量采集 → EXPLORATORY 快照 → 质量门 → Qlib/LightGBM 候选训练
```

AKShare 冷路径用于低成本扩大历史和市场状态覆盖；它不能因数据量大而自动成为 Formal
真相。候选模型可先在探索数据上预训练或筛选，但晋级、Shadow/Paper 和未来 LIVE 必须在
通过资格测试的正式 Provider 快照上重跑。

## 2. macOS 调研记录

### 2.1 当前东财 `gm` 路径

- 东财掘金官方 FAQ 明确要求 `gm` 在无法连接终端服务时检查并启动本地量化终端；当前未
  找到官方 macOS 掘金量化终端包。
- 东方财富普通 Mac 看盘/交易客户端不等同于掘金量化终端，不能向 AstraQuant 提供当前
  `gm` 契约。
- 保留现有东财 Provider 作为 Windows bootstrap，但不得继续让它定义通用 Provider 配置、
  凭据命名、UI 文案或研究入口。

参考：

- [东财掘金 FAQ](https://emquant.18.cn/help/doc/faq/book.pdf)
- [东财掘金实盘说明](https://www.myquant.cn/docs2/operatingInstruction/trading/%E5%AE%9E%E7%9B%98%E4%BA%A4%E6%98%93.html)

### 2.2 东方财富 Choice Mac API

- 东方财富 Choice 提供官方 `EMQuantAPI C++ Mac`，含数据、交易日历、资讯和组合接口。
- 当前文档仍描述 `libEMQuantAPIx64.dylib`；Apple Silicon 上必须先实测架构、权限、延迟、
  数据字段和 Rosetta/x86_64 独立桥接可行性。
- 文档中的组合下单是组合管理能力，不能在没有 Broker 账户、委托、成交回报与对账证据时
  宣称为真实证券交易接口。

参考：[EMQuantAPI C++ Mac 官方文档](https://quantapi.eastmoney.com/Upload/EMQuantAPI_CPP_Mac.pdf)

### 2.3 `VeKiner/akshare-stock-data-fetcher`

该项目适合作为批量采集实现参考，不适合作为新的权威数据源或直接 vendoring：

- 数据仍由 AKShare 调用东财公开网页接口；不会比上游更早或天然更完整。
- 当前范围主要是全市场 A 股快照和当日 5 分钟线，不覆盖完整指数、ETF、期货、Tick/L2、
  公司行动、PIT 标的状态与 Broker 事实。
- 32 进程、超时、重试和代理轮转提升的是收盘后批量吞吐，不是实时行情延迟。
- 默认 15:50 获取一次全市场快照、16:00 获取当日 5 分钟线，不是连续实时订阅。
- MongoDB 每标的一集合、全局 patch `requests.get`、空连接配置、无测试/CI，不符合 Astra
  不可变快照、schema fingerprint、质量门与审计要求。
- MIT 许可证允许参考实现；只吸收并发、超时、重试、checkpoint/upsert 思路，自主实现
  Astra Provider/Worker，不复制其存储与全局请求补丁。

参考：

- [项目仓库](https://github.com/VeKiner/akshare-stock-data-fetcher)
- [分钟批量脚本](https://github.com/VeKiner/akshare-stock-data-fetcher/blob/main/stock_zh_a_hist_min_em.py)
- [全市场快照脚本](https://github.com/VeKiner/akshare-stock-data-fetcher/blob/main/stock_zh_a_spot_em.py)

## 3. 优先级与任务

### P0：解除 macOS 数据阻塞，支撑 S6（立即实施）

- [x] 在 Apple Silicon macOS 安装并验证 Python 3.12、uv、Node 24、pnpm、Rust 1.96、
  `libomp`、Tauri 和本地 FastAPI。
- [x] 将桌面本地 API 首次握手超时从 10 秒放宽到 30 秒，并使 `scripts/dev.sh` 可执行；
  变更在合并前仍需通过完整质量门。
- [x] 引入通用 `ProviderRegistry`；首个 CLI 通过 `provider_id` 选择 AKShare，注册表拒绝重复
  ID 和未知 Provider。实时行情配置/UI 的迁移仍在下一项处理。
- [x] 实时服务按 Provider 声明决定是否需要凭据，健康状态与 UI 使用动态 `provider_id`；
  Mac 无 `gm` SDK 时默认选择 AKShare，东财专属配置端点仍只服务东财注册项。
- [x] 新增 Mac 延迟行情 Provider：30 秒有界轮询全市场 A 股与核心指数快照，支持搜索、
  1/5/15/30/60 分钟及日/周/月/年图表；所有 Quote 明确标为 `DELAYED`，UI 显示
  “公开网页延迟行情”，量化信号门不把它视为交易级 LIVE。
- [x] 扩展已有 AKShare Adapter：A 股日线、SSE/SZSE/BSE 5 分钟线、全市场股票快照与
  核心指数快照已实现；ETF 可按 A 股代码搜索和看盘，完整指数/ETF 资格矩阵留到 P1。
- [x] 实现 Astra 原生批量 Worker：有界线程并发、指数退避、按标的原子 checkpoint、resume、
  失败清单与幂等发布已完成；CLI 中断可安全退出，下次从已落盘标的恢复。
- [~] 以交易日/venue 分区写入不可变 Parquet，并记录 AKShare 版本、实际底层接口、复权口径、
  行数与质量报告；schema fingerprint 和更细的 request/received 时间仍待 v2 manifest 集成。
- [x] 所有 AKShare 批量产物固定为 `EXPLORATORY_ONLY`/`run_class=EXPLORATORY`；现有
  `EvidenceGate` 已测试拒绝其进入 Formal。
- [x] CLI 输出明确 snapshot ID，可供 S6 pin；完整批次存在失败时退出码为 2 且不发布，
  禁止训练任务把缺标的批次当作完整数据。

P0 验收：Mac 无东财终端也能完成“批量抓取 → checkpoint → 不可变 Parquet → 质量报告
→ 固定 snapshot_id 训练”纵向切片；网络失败可恢复，不出现重复 bar、静默缺口或证据等级
升级；离线 fake client 测试和一组真实小样本验收均通过。

P0 验收状态：**通过**。批量链路与 Mac 延迟看盘链路均已接入；后者只解决观察体验，
不会把公开网页轮询升级为认证实时证据或实盘行情。

### 3.1 已完成纵向切片（2026-08-12）

运行命令：

```bash
uv run astraquant-data collect-5m \
  --date 2026-08-11 \
  --instrument 600000.SSE \
  --checkpoint .local/checkpoints/akshare-2026-08-11 \
  --data-root .local/data \
  --max-workers 1
```

真实网络验收结果：`600000.SSE` 返回并发布 48 根 5 分钟 Bar，时间范围为北京时间
09:35–15:00；checkpoint 重跑不再次抓取，并返回同一已发布 snapshot。该样本只验证链路，
不代表 AKShare 已通过完整性、授权或 Formal 资格认证。

### P1：引入第二个认证数据源，建立交叉验证

- [ ] 实测 Tushare Pro 的日线、历史分钟、实时分钟、指数、ETF、标的状态、权限、频次、
  修订和授权，按 endpoint 生成 `ProviderQualificationReport`。
- [ ] 实测 Choice `EMQuantAPI C++ Mac` 在 Apple Silicon 的 native/Rosetta 运行、字段、历史
  深度、实时延迟和权限；如只能 x86_64，使用独立 NDJSON/RPC bridge，主 ARM64 Python
  不直接加载异构 dylib。
- [ ] 对重叠标的/日期抽样比较 AKShare、Tushare/Choice 与现有东财 `gm` 的 OHLCV、分钟边界、
  停牌、复权和交易日差异；冲突进入 quarantine，不静默选值。
- [ ] 只有资格、授权和质量门通过的 endpoint 才可进入 `REAL_API_MARKET` 或
  `REAL_API_REFERENCE`。

P1 验收：至少一个 macOS 可用的认证 Provider 能独立生成 Formal 日线/分钟快照；相同
canonical 请求可重现，差异报告有来源、时间和处置结论。

### P2：为未来实盘保留跨平台执行边界

- [ ] 新增独立 `BrokerGateway` 契约，覆盖账户、资金、持仓、委托、撤单、成交回报、重连、
  幂等 client order id 与对账；行情 Provider 不拥有下单能力。
- [ ] 评估 Windows/Linux Gateway 节点承载东财掘金、QMT/PTrade、vn.py/CTP；Mac 仅作为
  控制面和研究端，通过认证 RPC/WebSocket 通信。
- [ ] LIVE 默认永久关闭；先完成只读 Broker 事实、Mirror、Paper 差分和人工审批，再讨论
  任何真实委托。

P2 验收：Mac 控制面可在不保存 Broker 密钥、不发送真实委托的情况下读取脱敏账户事实并
完成 Paper/Mirror 对账；LIVE 适配必须另立安全计划和发布门。

## 4. 与现有任务的关系

- 本计划的 P0 是 Strategy Fast Lane `S6 更长历史与更多标的` 的前置数据任务，与 S6 同级
  最高优先；没有 pinned snapshot 和质量报告时不得直接扩大训练。
- P1 可与 `S7 策略信号改进` 并行准备，但 Formal 模型比较必须等待认证数据源通过。
- P2 不阻塞研究与 Paper；位于 Shadow/Paper 治理收口之后、任何 LIVE 讨论之前。
- 现有东财 Phase 1a/1b capture 与 snapshot 工作不删除；Provider Registry 复用其资格、
  capture、vintage 和证据门，而不是建立第二套旁路数据库。

## 5. 不可妥协边界

1. 开源采集工具解决吞吐，不授予数据版权，也不提高证据等级。
2. 不默认使用代理池绕过限流；速率、缓存和并发必须可配置、可审计并符合上游条款。
3. 探索源失败时不向实时页或 Formal 任务伪造、前向填充或静默切换数据。
4. 原始价格事实与复权研究视图分离；训练快照必须显式记录 adjustment 和 available time。
5. 任何训练都 pin snapshot、代码版本、feature/label spec 和 universe，不读取可变“最新数据”。

# AstraQuant 状态交接：秒级 ML 基线里程碑完成

> 更新时间：2026-08-07（晚）
> 用途：交给下一位 AI/开发者继续开发。
> 重要：本文以当前本地工作树为准。接手者必须先保护未提交改动，禁止直接执行 `git reset --hard`、`git checkout -- .` 或删除工作树。

## 0. 接手后先做这五件事

```powershell
cd D:\AstraQuant\.worktrees\phase-1-desktop-platform
git status --short
git branch --show-current
git log -5 --oneline
git diff --stat
```

当前开发位置与分支：

- 项目主目录：`D:\AstraQuant`
- 实际开发工作树：`D:\AstraQuant\.worktrees\phase-1-desktop-platform`
- 当前分支：`feature/phase-1-desktop-platform`
- 远端基线提交：`043aa7b`（fix: 修复 CI mypy 测试目录类型错误）
- GitHub：`Xiaogans1/AstraQuant`
- 最近 CI：`31151532025` 成功（4 job 全绿，13m14s）
- 工作树应为干净状态；如有未提交改动，先审查再决定，不要丢弃。

## 1. 一句话产品定义

**AstraQuant 是一套面向中国 A 股与国内期货的、本地优先、桌面优先、AI 主导的实时量化研究与决策辅助软件。**

真实只读行情 → 秒级特征/策略/模型 → 目标仓位与风控 → 本地虚拟撮合 → 持仓/现金/收益/回撤 → 研究、复盘与模型版本管理。LLM/DeepSeek 只产出当日策略约束与情报，不进入逐 Tick 下单热路径。

## 2. 当前已完成的功能

### 2.1 桌面与本地服务

- Tauri 管理本地 FastAPI（随机端口、会话认证、安全关闭），`start.ps1` 一键启动。
- 首页：真实大盘/核心指数/自选/证券搜索（`InstrumentSearchPicker` 复用组件）。
- 专业行情图：分时/日/周/月/年 K、MA/BOLL/VOL/MACD/KDJ/RSI、十字光标、量化信号与模拟成交图层。

### 2.2 模拟盘产品闭环（本会话完成）

- 期初持仓用真实证券搜索选择器（输入代码/名称 → 选择 → 规范 `instrument_id`，名称自动填充，未选择不可提交，连续添加）。
- 持仓实时盯市（**修复 SQLite 时区剥离 bug**：repository 存储层统一 UTC，含一次性迁移工具 `tools/migrate_paper_timezones.py`）。
- 当日盈亏 = Σ 数量 × (最新价 − 昨收)，相对昨收显示（不受历史录入成本影响）。
- 持仓表：最新价大字在上、成本小字在下。
- 现金按外部入金/出金处理（`PATCH /cash`），不伪造策略盈亏。
- **费用可配置**：`GET/PUT /v1/paper/fee-config`，默认免最低佣金 + 万 2.5 + 印花税万 5（ETF 免征）+ 过户费万 0.1；前端"模拟费用设置"面板。
- **账户重置**：`DELETE /v1/paper/accounts/{id}` 级联清空订单/成交/持仓/快照/策略记录并重建默认账户；前端"重置模拟账户"按钮（二次确认）。
- 策略结果持久化（`paper_strategy_runs` 表，刷新/重启恢复，显示最近检查时间）。
- 盘中自动循环检查：行情 LIVE 时每 5 秒并发扫描全部持仓，结果落库。
- 布局：量化操作核心置顶（检查全部持仓 + 逐只结果明细），图表区带持仓切换器，持仓表与录入沉底。

### 2.3 秒级 ML 基线里程碑（本轮 12 个提交，`ea3c650..043aa7b`）

按文档《AI 量化、模拟账户与策略平台设计》阶段 4 落地：

1. **研究数据录制**：`tools/research/fetch_minutes.py` — 东财分钟线 → 领域 `Bar` → `ParquetSnapshotStore` 不可变快照（多交易日分区）。
2. **防泄漏特征**：`packages/quant/src/astraquant_quant/research_features.py` — `build_feature_rows`（窗口 30，只用历史数据；10 特征：return_1/3/5/10、volatility_5、vwap_deviation、volume_ratio、day_high_position、ma5_gap、ma20_gap）+ `label_future_return`（未来完成区间标签，不足返回 -1）。
3. **训练与评估**：`tools/research/train_model.py` — `purged_train_test_split`（Purged/Embargo 切分）、`evaluate_model`（LightGBM，AUC + 含费用净收益 + 交易次数）。依赖 `lightgbm>=4,<5`、`pandas>=2,<3`、`scikit-learn>=1.5,<2`（已入 lockfile）。
4. **模型注册表**：迁移 `0005_model_registry`，`model_registry` 表；API `POST/GET/PATCH /v1/paper/models`、`POST /v1/paper/models/{id}/approve`；**发布门槛：AUC > 0.55 且含费用净收益 > 0 才可批准**；已批准模型不可修改、不可重复注册。
5. **策略分层**：`packages/quant/src/astraquant_quant/strategy_layer.py` — `PortfolioConstructor`/`RiskPolicy`/`build_target_position`（信号强度 → 目标仓位，100 股整数倍）/`side_of`/`build_model_signal`/`MODEL_FEATURE_COLUMNS`（特征列单一来源，训练端与在线端共用）。
6. **模型接入实时环**：`paper_strategy_service.run()` 已批准模型优先（LIVE 行情 → 特征 → LightGBM 推理 → BUY/SELL/HOLD 阈值 0.6/0.4 → 目标仓位 → 幂等 → 风控 → 模拟成交）；推断异常/工件缺失/非 LIVE 回退规则策略（`evaluate_intraday_signal`）。SELL 目标受可用持仓约束。
7. 前端策略区显示当前策略/模型版本徽标（来自最近一次检查结果）。

## 3. 架构一致性对照（文档 vs 现状）

| 文档要求 | 状态 | 说明 |
| --- | --- | --- |
| 5.3 模型发布门槛 | ✅ | 防泄漏、Purged/Embargo、含费用评估、人工批准 |
| 5.1 策略分层 | 🟡 | PortfolioConstructor/RiskPolicy/目标仓位已实现；**AlphaEnsemble、UniverseSelector、ExecutionPolicy 未做** |
| 研究环（数据→特征→训练→评估→注册） | ✅ | 代码闭环完成，待真实数据跑通 |
| 已批准模型接入实时环 | ✅ | 影子信号优先，规则回退 |
| 4.1 秒级事件总线/快车道 | ❌ | 仍是 5 秒轮询，无 Tick 推送事件总线 |
| 5.2 微观结构特征（OFI/盘口不平衡） | 🟡 | 只有分钟级 OHLCV 特征，无盘口特征 |
| 11.7 Qlib/RD-Agent 研究自动化 + 每天微调 | ❌ | 未做 |
| Deflated Sharpe、压力测试、REPLAY 回放模式 | ❌ | 未做 |
| 真实模型上线（训练出可批准工件） | ❌ | 待执行：录真实数据 → 训练 → 注册 → 批准 |

## 4. 待完成项（按优先级）

### P0：重置虚拟盘并让真实模型上线

- [ ] 用户重启应用（`cd D:\AstraQuant; .\start.ps1`，先关旧窗口——旧后端无新接口）。
- [ ] 模拟盘点"重置模拟账户"（清掉错误策略产生的订单/成交），重新录入真实持仓与现金。
- [ ] 运行真实数据录制（需东财终端在线、Token 已配置）：
  ```powershell
  uv run python tools/research/fetch_minutes.py 159516.SZSE --count 5000
  ```
  对每只持仓标的录制足够多交易日（2000 根 ≈ 8 个交易日）。
- [ ] 特征化 + 训练：编写特征导出脚本（把 Parquet 快照转 `train_model.py` 期望的 `{"rows": [...]}` JSON，行含 `label` 与 `future_return`——**注意 `evaluate_model` 依赖 `future_return` 键，当前无生成器，需要补**），然后：
  ```powershell
  uv run python tools/research/train_model.py features.json
  ```
  确认 AUC > 0.55 且 net_return > 0。
- [ ] 保存 LightGBM 模型工件到本地路径（`booster.save_model(...)`），注册并批准：
  ```powershell
  # POST /v1/paper/models（DRAFT）→ PATCH 更新指标 → POST /approve
  ```
- [ ] 观察 5 秒自动循环使用模型信号；审计记录 `strategy_id` 应为模型 id。

### P1：架构缺口（按文档阶段 4→5 顺序）

- [ ] `evaluate_model` 的 `future_return` 数据生成器（当前测试里手工注入；真实管线缺失）。
- [ ] 研究数据查询层：用 DuckDB 从 Parquet 快照切片训练集（`astraquant_data.query` 已存在，需接入特征导出脚本）。
- [ ] 多标的录制与统一训练集（当前脚本单标的）。
- [ ] 模型指标历史与 Deflated Sharpe、参数扰动压力测试。
- [ ] REPLAY 回放模式：历史事件流驱动策略确定性验证（文档四种运行模式之一）。
- [ ] AlphaEnsemble 与 UniverseSelector（文档 5.1 剩余分层）。
- [ ] 秒级事件总线/快车道（文档 4.1）：东财 Tick 通道、事件持久化、增量特征（当前 5 秒轮询可继续作为降级路径）。
- [ ] 盘口特征（文档 5.2：OFI、买卖量不平衡等）——依赖东财免费数据实际能力评估。

### P2：研究自动化与情报

- [ ] Qlib/RD-Agent 风格研究流水线适配（文档 11.7）。
- [ ] DailyRegimePlan（DeepSeek 情报 → 当日策略约束与风险预算，文档 6）。
- [ ] 绩效归因（日/周/月/年收益、回撤、夏普、胜率、按策略/模型归因，文档 7.3）。

## 5. 启动与验证命令

### 5.1 一键启动

```powershell
cd D:\AstraQuant
.\start.ps1
```

### 5.2 前端验证

```powershell
pnpm --dir apps/desktop test -- --run
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

### 5.3 Python 验证（重要：mypy 必须全量）

```powershell
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run mypy            # ← 必须不带参数！CI 检查 137 文件（含 tests/）
                      #    `uv run mypy packages` 只查 70 文件，会漏测试目录错误（踩过坑）
```

### 5.4 Rust/Tauri 验证

```powershell
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
```

## 6. 关键代码入口

### 前端

- `apps/desktop/src/pages/PaperPage.tsx`：模拟盘（策略核心置顶、持仓切换器、费用设置、重置按钮）。
- `apps/desktop/src/components/InstrumentSearchPicker.tsx`：证券搜索选择器（首页自选 + 期初持仓共用）。
- `apps/desktop/src/components/MarketWorkspace.tsx`：共享行情工作台。
- `apps/desktop/src/api/queries.ts` / `client.ts`：TanStack Query hooks 与 API client。

### 量化与研究

- `packages/quant/src/astraquant_quant/research_features.py`：防泄漏特征与标签。
- `packages/quant/src/astraquant_quant/strategy_layer.py`：目标仓位分层 + 模型信号组装 + 特征列单一来源。
- `tools/research/fetch_minutes.py`：分钟线录制。
- `tools/research/train_model.py`：LightGBM 训练与 Purged/Embargo 评估。

### 后端

- `packages/api/src/astraquant_api/paper_strategy_service.py`：模型优先 + 规则回退 + 5 秒自动循环。
- `packages/api/src/astraquant_api/paper_routes.py`：账户/费用/模型注册表/策略路由。
- `packages/api/src/astraquant_api/paper_repository.py`：账本 + 模型注册表存储（UTC 规范化）。
- `packages/api/migrations/versions/0005_model_registry.py`：模型注册表迁移。

## 7. 注意事项与禁止事项

- 不要丢弃当前未提交改动；不要执行 `git reset --hard` / `git checkout -- .`。
- **不要在子代理会话中执行 `git checkout`/`git stash`**（曾导致 detached HEAD，需 `git branch -f` 修复）。
- 提交信息用中文 conventional commit（如 `feat:`、`fix:`）；PowerShell 中 `-m` 消息避免全角引号导致参数解析失败（用单引号）。
- 本地验证必须跑全量 `uv run mypy`（不带参数），与 CI 一致。
- 不要重新引入假行情、假 AI 情报或假收益。
- 策略必须是注册的、版本化的、经过发布门槛的；**禁止临时写死策略逻辑**（用户已明确否定无参照的临时网格策略）。
- Token、账户密码、私人持仓数据不得进入 Git。
- 未经模拟、回放和独立风控前不连接真实委托。

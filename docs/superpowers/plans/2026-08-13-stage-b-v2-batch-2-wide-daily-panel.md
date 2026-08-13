# Stage B v2 Batch 2 Wide Daily Panel Implementation Plan

> **Execution rule:** 按 Task 顺序使用 TDD 实现；每个 Task 独立提交并推送。真实 API 命令可在本地服务与 qualification 可用时执行，但测试数据只能验证程序，不得冒充正式训练结果。

**Goal:** 用东方财富真实 A 股日线 exact snapshots 构建 300–800 只历史时点动态股票池、可重复的 Alpha158/市场状态/风险特征与 D1/D5/D10 标签面板，并先用 Ridge、LightGBM/DoubleEnsemble 判断截面任务是否存在稳定扣费净优势。

**最终任务目标:** Batch 2 结束时，程序能够针对每一个历史交易日还原“当时真正可选的股票”，在完全相同的 6 个 walk-forward folds、特征、标签、费用和组合规则下输出 Ridge 与 LightGBM/DoubleEnsemble 的 IC、Rank IC、分层收益、换手、扣费净收益、回撤和跨 fold 稳定性。只有简单强基线通过冻结门槛，Batch 3 才允许 StockMixer v2 与 MASTER 参赛。

**不属于完成:** 少量 ETF、当前成分股回填历史、随机切分、当前收盘成交、仅报告 AUC/IC、在 outer test 上改阈值、或复杂模型单次正收益，都不能关闭 Batch 2。

---

## Task 1: Freeze the historical liquidity-universe policy

**Files:**

- Modify: `packages/domain/src/astraquant_domain/cross_sectional.py`
- Modify: `packages/domain/src/astraquant_domain/__init__.py`
- Modify: `tests/domain/test_cross_sectional.py`

- [x] 增加 `HistoricalUniversePolicy` frozen contract 与 canonical digest。
- [x] 固定正式值：60 日流动性窗口、120 日最短历史、目标 500 只、最少 300/最多 800、最低价格 2 元、窗口可用率 95%、排除 ST、只纳入普通 A 股。
- [x] 拒绝窗口/历史/上下限矛盾、非有限 Decimal、未知 schema。
- [x] 运行 domain tests、Ruff、mypy（`25 passed`）；提交 `feat(domain): 冻结历史流动性股票池契约`。

## Task 2: Build a leakage-safe historical dynamic universe

**Files:**

- Create: `packages/quant/src/astraquant_quant/historical_universe.py`
- Create: `tests/quant/test_historical_universe.py`

- [x] 定义 `DailyUniverseInstrument`、`DailyInstrumentStatus`、`HistoricalUniverseSnapshot`。
- [x] 每个 decision session 只使用该时点已发生的 listing/status/bar；不得用当前 universe 回填过去。
- [x] 候选必须为普通 A 股、已满足最短历史、非 ST、当日可交易、价格达标、过去 60 日覆盖率达标。
- [x] 按 trailing median turnover 降序、instrument id 次序确定性选前 500；任何正式 session 少于 300 只 fail closed。
- [x] snapshot digest 必须绑定 policy、sessions、逐日 membership、每个 exact source snapshot 和 status/lifecycle evidence。
- [x] 测试新上市、退市、ST、停牌、缺失、未来 turnover 变化、输入排列与 digest（`7 passed`；Ruff/mypy clean）；提交 `feat(quant): 构建历史时点动态股票池`。

## Task 3: Assemble exact Eastmoney daily panels

**Files:**

- Modify: `packages/data/src/astraquant_data/research_store.py`
- Create: `packages/data/src/astraquant_data/daily_panel.py`
- Create: `tests/data/test_daily_panel.py`
- Create: `tools/research/build_stage_b_v2_daily_panel.py`
- Create: `tests/data/test_stage_b_v2_daily_panel_cli.py`

- [x] 增加频率感知的 exact snapshot loader，正式路径禁止 `latest`，只接受非 sentinel SHA-256，并重验 manifest/Parquet hash/row count。
- [x] request manifest 明确列出 benchmark、所有证券 dataset/snapshot、universe snapshot、日期区间和 provider；所有 source provider 必须为 `eastmoney`。
- [x] 校验日线唯一/递增、session 对齐、adjustment policy、benchmark 全覆盖、membership 中每只股票有 exact source。
- [x] 生成与 `DailyCrossSectionalPanel` 同构的 `ExactDailyPanel`；缺失证券 bar 保留为不可用，不前向填充价格。
- [x] 两次独立构建得到相同 manifest/panel digest（33 项相关回归通过；Ruff/mypy clean）；提交 `feat(data): 组装真实日线截面面板`。

## Task 4: Materialize Stage B v2 features and labels

**Files:**

- Create: `packages/quant/src/astraquant_quant/cross_sectional_features.py`
- Create: `tests/quant/test_cross_sectional_features.py`
- Create: `packages/data/src/astraquant_data/exports/stage_b_v2.py`
- Create: `tests/data/test_stage_b_v2_export.py`

- [x] **Task 4A:** 已实现 Alpha158 之外的相对 OHLCV、流动性、风险、市场宽度/波动 context features，以及 train-only median/MAD `[-3, 3]` processor（23 项相关回归通过；Ruff/mypy clean）。
- [x] **Task 4B:** 已实现 raw daily bars + context + D1/D5/D10 labels 的不可变 Parquet request，绑定 panel/source/universe/task digests，并声明 pinned Qlib Alpha158 commit/config；独立双导出逐字节一致（18 项相关回归通过；Ruff/mypy clean）。
- [x] 首批特征固定为 Qlib 官方 Alpha158、相对 OHLCV 序列、市场宽度/波动/成交状态和个股流动性/风险；不得用标签未来区间。
- [x] train segment 单独拟合 median/MAD，clip 到 `[-3, 3]`；valid/test 只 transform（已在 Ridge/LightGBM 与隔离 DoubleEnsemble runner 串联）。
- [x] 同时物化 Batch 1 的 raw/excess/rank/downside D1/D5/D10 labels 和 train-only extreme mask。
- [x] artifact 绑定所有 source/universe/task/feature/code/fold/assignment digests；相同输入重复生成逐字节一致。
- [x] Alpha158 由 pinned Qlib runner 按证券独立计算，主环境不复制近似公式；runner 全套 `18 passed`。提交 `feat(research): 物化Stage B v2截面特征标签`。

## Task 5: Freeze six outer folds and run the baseline matrix

**Files:**

- Create: `packages/quant/src/astraquant_quant/cross_sectional_splits.py`
- Create: `tests/quant/test_cross_sectional_splits.py`
- Create: `packages/quant/src/astraquant_quant/cross_sectional_baselines.py`
- Create: `tests/quant/test_cross_sectional_baselines.py`
- Create: `tools/research/run_stage_b_v2_baselines.py`
- Create: `tests/quant/test_stage_b_v2_baseline_cli.py`

- [x] 6 个按全市场统一时间轴的 expanding folds；fit 至少 3 年、inner-valid 至少 120 sessions、outer-test 至少 60 sessions，fit/valid 与 valid/test 两侧 purge 均为 11 sessions。
- [x] 同一交易日所有股票只能落在同一 segment；outer test 永不参与特征 fit、校准、阈值或超参选择（`8 passed`；Ruff/mypy clean）。
- [x] Ridge、LightGBM、DoubleEnsemble 使用相同 rows/folds/seeds/trial budget，并统一接 Batch 1 Huber 校准与目标组合；DoubleEnsemble 固定 Qlib commit 并在 Python 3.11 隔离环境执行。
- [x] 报告 IC、Rank IC、top-bottom spread、turnover、真实费税、净收益、最大回撤、容量和每 fold/seed 明细；失败 trial 也计数；采用 horizon 间隔避免重叠收益并提供 BASE/ADVERSE/SEVERE 三档成本。
- [x] 固定信号门：至少 4/6 folds 的 Rank IC 为正、平均 Rank IC ≥ 0.02、3 seeds 方向一致；固定交易门：扣费净收益为正、至少 4/6 folds 为正、相对 Ridge 有明确改善、压力成本下不翻为严重负值。
- [x] 未过门输出 `NO_LEARNABLE_EDGE` 或 `NO_NET_EDGE`；不得自动启动复杂模型。提交 `feat(research): 运行Stage B v2强基线矩阵`。

## Task 6: Execute real-data acceptance and close Batch 2

**Files:**

- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`
- Modify: this plan
- Create under ignored artifacts root: request/panel/feature/baseline reports

- [ ] 从官方 Eastmoney API 抓取普通 A 股与 benchmark 日线；首个正式矩阵至少 300 只、5 年，目标扩到 500 只、10 年。
- [ ] 两个全新 output roots 独立运行；source/universe/feature/fold/prediction/report digests 必须一致。
- [ ] 报告真实覆盖数量、日期、缺失、训练用量、各模型和组合结果，不用测试 fixture 填空。
- [ ] 若未达门槛，明确停止在基线；若达门槛，才编写 Batch 3 StockMixer v2/MASTER implementation plan。
- [ ] 全套 pytest、Ruff、mypy、`git diff --check` 通过后提交并推送。

---

## Batch 2 exit gate

1. 至少 300 只普通 A 股、5 年真实 Eastmoney daily exact snapshots；目标 500 只、10 年。
2. 每个历史 session 的 membership 都能回溯到当时 lifecycle/status/bar 与 exact source，不存在当前成分股回填。
3. D1/D5/D10 的 feature/label/fold/portfolio 语义统一，重复运行 digest 一致。
4. Ridge、LightGBM/DoubleEnsemble 在同一协议上给出可审计结论，允许结论是无优势。
5. 未过简单基线门时，StockMixer v2、MASTER、TRA、DoubleAdapt 均不得消耗正式试验预算。

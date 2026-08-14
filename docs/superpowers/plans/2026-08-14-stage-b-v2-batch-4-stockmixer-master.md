# Stage B v2 Batch 4 StockMixer v2 / MASTER Implementation Plan

> **Execution rule:** 按 Task 顺序 TDD；每个 Task 独立提交并推送。Batch 4 只增加模型表达能力，不允许改动 Batch 2/3 冻结的 labels、folds、seeds、Huber calibration、Top-K、费用、滑点或容量规则。

**Goal:** 在同一 718 只真实 A 股、10 年、D1/D5/D10 宽市场矩阵上，让 StockMixer v2 的历史时间混合与 MASTER 的市场引导关系建模依次挑战唯一 incumbent `DOUBLE_ENSEMBLE`，用统一扣费结果判断复杂结构是否真正有增益。

**Frozen incumbent:** Batch 3 最终报告 `sha256:9d89cec7eed138df99b38d11013dc892a6e5aa49e00fe0a71df6d9c4749e8c39`。DoubleEnsemble 三周期等权聚合 RankIC `0.04918929`、base net `+2.606151%`、severe net `+1.464855%`、最差最大回撤 `33.503743%`。Batch 4 最大允许回撤为其 1.2 倍，即 `40.204491%`。

**最终任务目标:** Batch 4 结束时，程序能够把 exact 东方财富 raw bars、同日可见 context、动态 universe 与冻结 labels 组合成多日共享张量；StockMixer v2 和 MASTER 均以 6 folds × 3 seeds × D1/D5/D10 生成可恢复预测，再由主进程统一评价。未超过 incumbent 时保留可复用模型能力并明确 `NO_NET_EDGE`，不降低门槛、不回到 9 ETF demo，也不阻塞后续按证据决定是否进入 Stage C。

---

## Task 1: Freeze the temporal challenger contract

**Files:**

- Create: `contracts/research-runner/stage-b-v2-stockmixer-v2-v1/request.schema.json`
- Create: `contracts/research-runner/stage-b-v2-stockmixer-v2-v1/response.schema.json`
- Create: `tests/repository/test_stage_b_v2_stockmixer_v2_contract.py`
- Modify: `tools/research/run_stage_b_v2_baselines.py`
- Modify: `tests/quant/test_stage_b_v2_baseline_cli.py`

- [x] 增加 `STOCKMIXER_V2` external model identity；主环境只准备 request、校验 response 和统一评分，不 import PyTorch。
- [x] request 绑定 exact Stage B v2 raw export digest、materialization digest、raw bars/context/rows 文件 digest、runner identity、lookback、transform spec、fold/seed row IDs 与模型配置。
- [x] 固定 `lookback=64`；时间通道由 raw bars 确定性生成 `open/high/low/close relative-to-previous-close`、`log volume change`、`log turnover change`，当前时点 15 个 context 字段走独立 context encoder，不把未来 context 回填到历史窗口。
- [x] response 逐 trial返回 processor/model/prediction digests、inner-valid 与 outer-test 有序 scores；缺证券、重复 row、未来 bar、摘要或 device 不符时 fail closed。

## Task 2: Materialize one shared dynamic temporal panel

**Files:**

- Create: `packages/data/src/astraquant_data/exports/stage_b_v2_stockmixer.py`
- Create: `tests/data/test_stage_b_v2_stockmixer_export.py`
- Create: `tools/research/build_stage_b_v2_stockmixer_request.py`
- Create: `tests/research/test_build_stage_b_v2_stockmixer_request.py`

- [ ] 从 `stage-b-v2-export-*/request.json` 的 exact `bars.parquet/context.parquet/labels.parquet` 和 materialization `matrix.parquet` 构造共享 panel；不调用网络、不使用 StockMixer 示例数据。
- [ ] 每个 decision time 使用当日真实动态 universe；停牌/缺 bar 用显式 `presence_mask/feature_mask/tradable_mask/label_mask`，数值 0 不能代表缺失。
- [ ] panel 只保存一次 `time × instrument` 历史张量，trial 只保存行 ID 与窗口索引；不得按 54 个 trial 重复复制 lookback 数据。
- [ ] 相同输入双跑 manifest、panel、samples 文件逐字节一致；改任一 raw/context/materialization digest 必须改变 request digest。
- [ ] 在当前 718 股票真实输入上记录 row 数、文件大小、构造耗时和 32 GB Windows 峰值内存。

## Task 3: Implement the resumable StockMixer v2 runner

**Files:**

- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/stage_b_v2_stockmixer.py`
- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/temporal_panel.py`
- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/stockmixer_v2.py`
- Create: `runners/stockmixer/tests/test_stage_b_v2_stockmixer.py`
- Create: `runners/stockmixer/tests/test_temporal_panel.py`
- Create: `runners/stockmixer/tests/test_stockmixer_v2.py`
- Modify: `runners/stockmixer/src/astraquant_stockmixer_runner/__main__.py`

- [ ] StockMixer v2 复用已验证的 causal multi-scale time mixer 与 masked stock-to-market bottleneck；增加 current-context encoder，并保持证券排列等变、masked padding 不影响有效证券。
- [ ] 每 fold 只用 training-eligible inner-train 窗口拟合 processor；fit 尾部 20% sessions 作早停，固定 11-session purge；outer-test 标签不得参与归一化、早停或阈值。
- [ ] 固定 hidden 64、market 32、context 32、scales 1/2/4、最多 80 epochs、patience 8、16 decision dates/batch；只允许首轮前冻结的一组配置。
- [ ] 每个 trial 原子写预测检查点；中断后只继续未完成 trial。相同 request/seed/device 双跑 prediction/model digests 一致，CUDA 不可用时不得伪报。
- [ ] 先完成小 fixture 全套测试，再运行真实 D1 fold-01 seed-7 smoke；测得显存/耗时满足 32 GB 单机后才放开 54-trial 正式矩阵。

## Task 4: Integrate and execute the unified StockMixer challenge

**Files:**

- Modify: `tools/research/run_stage_b_v2_baselines.py`
- Modify: `tests/quant/test_stage_b_v2_baseline_cli.py`
- Modify: `docs/verification/quant-core-v3/stage-b-v2-wide-baseline.md`
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`

- [ ] StockMixer v2 scores 进入与四模型完全相同的 Huber calibration 和 BASE/ADVERSE/SEVERE 组合评价；不得自带更有利的 Top-K 或回测器。
- [ ] 完成 D1/D5/D10 × 6 folds × 3 seeds 共 54 trials，并从检查点恢复到第二个全新 output root 验证报告 SHA-256 一致。
- [ ] 聚合晋级门固定为：base net 至少 `2.806151%`、RankIC 严格高于 `0.04918929`、每周期至少 4/6 正 folds、三 seeds 净收益均正、severe net 为正、容量违约 0、最大回撤不高于 `40.204491%`。
- [ ] 任一门失败则 `STOCKMIXER_V2=NO_NET_EDGE`；仍保留 runner、预测和失败归因，不事后调整 lookback/损失/组合。

## Task 5: Pin and run MASTER as the relation challenger

**Files:**

- Modify: `.gitmodules`
- Create: `external/MASTER`
- Create: `runners/master/upstream-manifest.json`
- Create: `runners/master/pyproject.toml`
- Create: `runners/master/src/astraquant_master_runner/`
- Create: `runners/master/tests/`
- Create: `packages/data/src/astraquant_data/exports/stage_b_v2_master.py`
- Create: `tests/data/test_stage_b_v2_master_export.py`

- [ ] 固定论文官方仓库 commit、关键源码/论文 digest 和独立 Python lock；上游只读，主环境不 import Torch。
- [ ] market-guided 输入只来自 decision time 可见的 exact context；行业/概念/关系若无历史 PIT artifact 则本轮只运行无外部关系的 market-guided 版本，不用当前关系回填历史。
- [ ] 官方样例权重或 schema 不匹配时从头训练；不得把官方示例数据/权重结果当作 AstraQuant A 股效果。
- [ ] 使用与 StockMixer v2 相同 trials、校准、组合、成本和聚合晋级门完成可恢复矩阵；输出对 incumbent 的唯一裁决。

## Task 6: Close Batch 4 and route the next complexity tier

**Files:**

- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`
- Modify: `docs/verification/quant-core-v3/stage-b-v2-wide-baseline.md`
- Create: `docs/superpowers/plans/2026-08-14-stage-c-relations-regime.md` only if Batch 4 evidence supports continuing

- [ ] 在 `DOUBLE_ENSEMBLE/STOCKMIXER_V2/MASTER` 中按同一聚合规则冻结唯一新 incumbent；不按 horizon 组合多个赢家。
- [ ] 至少一个复杂 challenger 通过才进入 HIST/显式关系增强；全部失败则保留 DoubleEnsemble，先分析信号/组合瓶颈再决定新路线。
- [ ] Batch 4 不直接进入 Shadow/Paper。Stage C/D、ForecastCombiner、风险与执行发布门仍须完成。
- [ ] Kronos 继续作为独立 K 线预测/辅助因子通道，不替换本训练主线。

---

## Batch 4 exit gate

1. StockMixer v2 与 MASTER 都在 718 只真实宽市场矩阵上完成或给出可审计失败，不缩回 9 ETF/10 股票演示集。
2. 所有模型使用同一 labels、folds、seeds、校准、组合、真实费率、压力成本和容量语义。
3. 每个小时级 trial 可恢复；32 GB Windows 单作业稳定运行；两个全新输出根的最终报告逐字节一致。
4. 报告明确回答时间混合、市场引导和关系建模各自是否带来额外净收益，而不只罗列训练 loss 或 IC。
5. 长期目标仍保留 Stage C HIST/关系、Stage D TRA/DoubleAdapt 路由漂移、Stage E 组合与 Shadow/Paper 闭环；任何单模型成功都不等于量化核心完成。

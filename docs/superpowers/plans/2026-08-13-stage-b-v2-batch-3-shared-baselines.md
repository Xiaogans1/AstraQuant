# Stage B v2 Batch 3 Shared Baselines Implementation Plan

> **Execution rule:** 按 Task 顺序 TDD；每个 Task 独立提交并推送。所有模型消费 Batch 2 冻结的 exact materialization、folds、seeds、校准、组合和成本，不为新模型改标签、Top-K 或费用。

**Goal:** 在已通过标签可学习门的 10 年真实 A 股宽市场矩阵上，完成动态全市场 Shared MLP 与可恢复 DoubleEnsemble 挑战，选出 Batch 4 StockMixer v2/MASTER 必须战胜的最强 incumbent。

**Architecture:** Shared MLP 在隔离 PyTorch runner 中按同一决策日聚合股票表示：每只股票共享一个 feature encoder，使用 masked market mean 形成市场上下文，再由共享 head 输出逐股票 rank score。它不使用时间窗口 mixer 或显式股票关系，因此能单独测量“共享神经网络 + 市场上下文”的增益。DoubleEnsemble 继续使用固定 Qlib commit。两者只返回 inner-valid/outer-test score，由主进程统一 Huber 校准、组合构建与真实成本评价。

**最终任务目标:** Batch 3 结束时，程序能在 718+ 股票、D1/D5/D10、6 folds、3 seeds 上可靠恢复地比较 Ridge、LightGBM、Shared MLP、DoubleEnsemble；输出不仅有 IC，还必须有扣费净收益、压力成本、回撤、换手、容量和跨 fold/seed 稳定性。Batch 4 明确保留 StockMixer v2 与 MASTER：它们不是被简单模型替代，而是必须在同一冻结协议下证明其时间混合或关系建模确有额外价值。

---

## Task 1: Freeze the Shared MLP experiment contract

**Files:**

- Modify: `packages/quant/src/astraquant_quant/cross_sectional_baselines.py`
- Modify: `tests/quant/test_cross_sectional_baselines.py`
- Create: `contracts/research-runner/stage-b-v2-shared-mlp-v1/request.schema.json`
- Create: `contracts/research-runner/stage-b-v2-shared-mlp-v1/response.schema.json`
- Create: `tests/repository/test_stage_b_v2_shared_mlp_contract.py`

- [ ] 增加 `SHARED_MLP` 模型身份，只允许通过 external score contract 进入主评价，主环境不得 import PyTorch。
- [ ] 固定 request：source materialization digest、feature columns、rows digest、逐 trial fit/inner-valid/outer-test row ids、seed、模型配置和 runner identity。
- [ ] 固定模型配置：hidden 64、market 32、两层共享 encoder、dropout 0、masked market mean、最多 80 epochs、patience 8、batch 为完整 decision-date cross-section。
- [ ] response 必须逐 trial 返回 processor/model/prediction digests 和有序 valid/test scores；未知字段、缺 trial、重复 row、摘要不符 fail closed。

## Task 2: Implement the isolated Shared MLP runner

**Files:**

- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/stage_b_v2_shared_mlp.py`
- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/shared_mlp.py`
- Modify: `runners/stockmixer/src/astraquant_stockmixer_runner/__main__.py`
- Create: `runners/stockmixer/tests/test_shared_mlp.py`
- Create: `runners/stockmixer/tests/test_stage_b_v2_shared_mlp.py`

- [ ] 共享 encoder 对证券排列等变；增加一个 masked 股票不改变其他输出；任意日期股票数可变。
- [ ] 每 fold 只用 training-eligible fit rows 拟合 median/MAD；outer label 修改不能改变 normalization、模型选择、预测摘要。
- [ ] fit 尾部 20% sessions 作为内部早停段并保持 purge；inner-valid 只供主进程校准，outer-test 只在模型冻结后预测一次。
- [ ] 每个 trial 原子写稳定检查点；中断后只重跑未完成 trial；CUDA 不可用时可在 CPU 正确运行但不得伪报 device。
- [ ] 相同 request/seed/device 双跑逐字节一致；runner 全套 pytest、Ruff 通过。

## Task 3: Add Shared MLP to the common baseline matrix

**Files:**

- Modify: `tools/research/run_stage_b_v2_baselines.py`
- Modify: `tests/quant/test_stage_b_v2_baseline_cli.py`

- [ ] CLI 增加 `--shared-mlp-project` / `--skip-shared-mlp`，Shared MLP 与 DoubleEnsemble 使用相同 rows/folds/seeds。
- [ ] 主进程验证 response identity，用 inner-valid Huber 校准，并复用 BASE/ADVERSE/SEVERE 组合评价。
- [ ] horizon checkpoint 绑定模型集合；已有 Ridge/LightGBM checkpoint 不得被错误当成包含 Shared MLP 的完整结果。
- [ ] 相对门以 Ridge 为 incumbent：Shared MLP 平均净收益至少高 `0.2%`、至少 4/6 正 folds、3 seeds 方向一致且 severe net 为正才可标 `NET_EDGE`。

## Task 4: Execute Shared MLP and resumable DoubleEnsemble

**Files:**

- Modify: `docs/verification/quant-core-v3/stage-b-v2-wide-baseline.md`
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`
- Artifacts: ignored `.astraquant/research/stage-b-v2-*`

- [ ] 在冻结的 `sha256:d56feb…` materialization 上运行 Shared MLP D1/D5/D10、6 folds、3 seeds，失败 trial 计入结果。
- [ ] 使用逐 trial checkpoints 恢复并完成 DoubleEnsemble，不允许再因后续组合错误丢失已训练预测。
- [ ] 两个新 output roots 重复运行；trial/prediction/report digests 可复现，恢复路径必须实际命中且不重新训练已完成 trial。
- [ ] 报告训练时间、峰值内存/device、RankIC、净收益、压力、回撤、换手与容量；允许两个 challenger 都失败。

## Task 5: Freeze the Batch 4 incumbent and open complex challengers

**Files:**

- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`
- Create: `docs/superpowers/plans/2026-08-13-stage-b-v2-batch-4-stockmixer-master.md`

- [ ] 以 Batch 3 聚合扣费净收益最强且通过稳定性门的模型作为唯一 incumbent；不得按 horizon 为同一 challenger 单独调规则。
- [ ] Batch 4 StockMixer v2 使用 raw OHLCV/context 的历史 lookback、动态 universe masks 和同一 labels/folds/portfolio。
- [ ] Batch 4 MASTER 固定官方 commit，市场引导/关系输入必须来自 exact PIT artifact；schema 不匹配时只允许从头训练，不加载官方样例权重冒充可迁移。
- [ ] StockMixer v2/MASTER 必须同时改善 RankIC 与净收益，至少 4/6 folds 为正、3 seeds 同方向、回撤不超过 incumbent 1.2 倍，并通过延迟/滑点/容量压力；否则保留工程能力但裁决 `NO_NET_EDGE`。
- [ ] Batch 4 通过后才进入 HIST/TRA/DoubleAdapt 和 Shadow/Paper；Kronos 继续作为 K 线预测/辅助因子独立通道，不替换统一训练主线。

---

## Batch 3 exit gate

1. Shared MLP 与 DoubleEnsemble 都在同一 718+ 股票真实矩阵上完成或给出可审计失败，不缩小成十只演示数据。
2. 每个小时级 trial 可恢复、可观察，32 GB Windows 单作业稳定运行。
3. 所有模型的预测由统一主进程校准与组合评价，任何模型不得自带更有利的 Top-K、费用或回测器。
4. 明确冻结 Batch 4 incumbent；StockMixer v2/MASTER 长期目标写入可执行计划，不因简单模型当前领先而取消。

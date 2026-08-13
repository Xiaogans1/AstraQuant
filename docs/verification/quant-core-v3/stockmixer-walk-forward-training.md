# StockMixer 真实 Walk-forward 训练验收

**验收日期：** 2026-08-13  
**状态：** `TRAINING_VALIDATED / EXECUTION_EVALUATION_PENDING`  
**发布决定：** 尚不进入 Shadow/Paper，不宣称存在可交易净优势。

## 这次程序获得的能力

- 从已验收的共享 `panel.parquet + samples.parquet` 懒加载 fold 窗口，不再为每个样本复制 K 线。
- 每折训练段尾部单独切出 inner-valid，并在 train/valid 之间 purge；outer-test 不参与归一化、早停或权重选择。
- 归一化只统计 inner-train 中真实存在的行情，停牌/缺 bar/补零行不进入均值方差。
- 损失只消费 `label_mask=True` 的标签，并组合收益回归与同一时点截面排序。
- CUDA 确定性训练、早停、最佳权重恢复、pickle-free 模型文件和 canonical response 已完成。
- 每折输出不可变 `model-state.bin`、`predictions.parquet`、`response.json`；response 固定请求、训练配置、代码、模型和预测 digest。

## 冻结实验

- 输入：Stage B 启动批次的相同 9 个 Eastmoney exact ETF snapshots，108,000 根 1 分钟 K 线。
- 请求：26,037 个共享样本、10,200 个 timestamps、3 个 walk-forward folds、lookback 16。
- 模型：DynamicStockMixer，hidden 64、market 32、scale 1/2/4，共 14,748 参数。
- 训练：seed `20260813`、AdamW、batch 1024、学习率 0.001、weight decay 0.0001、ranking weight 0.1。
- 选模：每折 500 个 timestamps inner-valid，边界 purge 6，最多 50 epochs，patience 8。
- 环境：Python 3.11.15、PyTorch 2.7.1+cu128、NVIDIA GeForce RTX 4060 Ti。

## 双跑可重复性

Run A 为 309.02 秒，Run B 为 308.94 秒。两个独立输出目录的三折模型文件、预测文件和 response 均逐字节一致。

| Fold | 最佳 epoch / 实跑 | Model state digest | Prediction digest | Response digest |
|---|---:|---|---|---|
| fold-01 | 48 / 50 | `sha256:f08bb121fa978dc69c0cd3da7faf2f9873b2c6915586bd45c71856a90cd49c05` | `sha256:2d50ce64c2bb5562c357613add837253881bb2027dc774413177d9bc3291e9ba` | `sha256:e8894a6a343dcbc1ca29d9ee16ed4e471b84eab313106006d9f7b0d3b0ac0c97` |
| fold-02 | 40 / 48 | `sha256:24a1d7bb9cced359f8f05350c33cb835bf0fd22a0568f805a146314e1d535875` | `sha256:15f120022f02c5333b89565c05f1880b259250ee1eb789a5591f8864e347f613` | `sha256:3ce8896dae52fc9d76c8528ef70fce9637ea913de3bb5466af97acf571cebd03` |
| fold-03 | 39 / 47 | `sha256:dbb61197ca69cb1b2df77fc2912a432f793e650225caa1a55e634dffa85e8b78` | `sha256:566f914039ed6800291ebbf3af5d05900c8628bdd78afa7bd3d9e46289132fe8` | `sha256:390766e4eb6d9fb11b80f19cf1bf41a49ee4cb972c3ec8d16008cc89407a8a10` |

## 冻结后的 outer-test 诊断

这些结果在训练方案冻结后才读取，不能用于回改本次超参数、损失权重或 early stopping。

| Fold | 有效标签 | MSE | 方向准确率 | Mean Rank IC | Median Rank IC |
|---|---:|---:|---:|---:|---:|
| fold-01 | 13,479 | 0.00001644 | 43.71% | 0.0707 | 0.1333 |
| fold-02 | 13,482 | 0.00001536 | 41.22% | 0.0202 | 0.0667 |
| fold-03 | 13,476 | 0.00000974 | 37.98% | 0.0074 | 0.0167 |

StockMixer 在第一折出现弱截面排序信息，但后两折明显衰减；方向准确率低于 50%。这不足以证明可交易优势，也不能据此反向、换阈值或挑选折。

## 下一关键节点

训练链路已经从“模型能前向”升级为“真实数据可规范训练并确定性产出”。下一步不是继续堆模型，而是写一个很小的 StockMixer prediction adapter：将三折 `EXPECTED_RETURN` 预测映射回原 panel 行，复用 DoubleEnsemble/Ridge 已冻结的 next-open、持有 5 bars、手续费、滑点、容量和 100 股整数手执行器。

统一执行报告完成后才能做二选一：

1. 扣费后稳定优于 Ridge/DoubleEnsemble，进入扩大历史与动态全 A 股 universe 的 Stage B 正式实验；
2. 无净优势或跨折不稳定，固定为 `NO_NET_EDGE`，保留工程能力，重新梳理标签、horizon 和共享表征实验，而不是事后调参。


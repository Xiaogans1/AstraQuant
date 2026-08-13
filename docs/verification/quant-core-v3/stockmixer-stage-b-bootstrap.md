# StockMixer Stage B 启动验收

**验收日期：** 2026-08-13  
**状态：** 工程底座完成，尚无模型效果结论。

## 程序获得的能力

- 固定官方 `SJTU-DMTai/StockMixer@cce13598afd3ff33ae317700a85ae08db0554652`，并锁定官方 `model.py`、`train.py` 与论文 SHA-256。
- 使用 AstraQuant exact Eastmoney snapshots；官方 NASDAQ、NYSE、S&P500 样例数据明确禁止进入训练。
- 一个模型同时处理完整证券横截面，不为每只证券单独训练模型。
- 分离 `feature_mask`、`presence_mask`、`tradable_mask` 和 `label_mask`；停牌、缺 bar、新上市和 padding 不会用假零值污染其他证券。
- 保留官方 indicator mixing、因果 multi-scale time mixing 与 stock-to-market-to-stock 语义；将固定股票数线性层替换为与证券数量无关的 masked market bottleneck。
- PyTorch 只存在于 `runners/stockmixer` 独立环境，主程序没有 Torch 依赖。

## 真实数据规模测量

输入为 Kronos/DoubleEnsemble 验收所用的相同 9 个 Eastmoney exact ETF snapshots，共 108,000 根 1 分钟 K 线。按最少 5,500 个训练 timestamps、每折 1,500 个测试 timestamps、3 折、lookback 16 生成：

- 共享样本：26,037
- 证券：9
- 市场 timestamps：10,200
- `panel.parquet`：1,270,930 bytes
- `samples.parquet`：321,331 bytes
- `request.json`：2,468 bytes
- 总计：1,594,729 bytes
- content digest：`sha256:1c0ea21bab55165539145bbe1e2027fd69aca006cda14c13cf0790584704f48f`

压缩前每个窗口重复存储 lookback 行，文件总计约 19.43 MB；改为“共享行情 + 样本区间索引”后缩小到 1.59 MB。这个格式不会把当前 9 个证券写死，也不会随着 lookback 重复行情。

## GPU 测量

环境：Python 3.11.15、PyTorch 2.7.1+cu128、NVIDIA GeForce RTX 4060 Ti。模型配置为 lookback 16、5 个输入指标、hidden 64、market 32、scale 1/2/4，共 14,748 参数。

| 场景 | Batch | 每步耗时 | 峰值显存 |
|---|---:|---:|---:|
| 当前 9 ETF | 1024 | 6.40 ms | 137.75 MB |
| 全 A 股压力测 5000 证券 | 16 | 55.30 ms | 1063.40 MB |

测量证明当前 RTX 4060 Ti 足以进入真实 walk-forward 训练，不需要退回逐证券模型或简化 demo。

## 已通过验证

- StockMixer runner tests：12 passed，包括 CUDA 前向、证券排列等变、masked padding 不变、masked time slot 不变、因果时间约束和损坏请求拒绝。
- Data/Panel regressions：16 passed。
- Ruff：全部通过。
- 新 exporter mypy：通过。
- Root environment：`torch` 不可 import，隔离边界成立。

## 下一步

进入独立微计划：实现每折 train/inner-valid/outer-test 的正式 runner、masked regression + ranking loss、早停与确定性 artifact；再对同一 9 ETF exact snapshots 双跑，并通过现有执行器与 Ridge、DoubleEnsemble 同口径比较。任何外层测试结果都不能反向修改训练、阈值或超参数。

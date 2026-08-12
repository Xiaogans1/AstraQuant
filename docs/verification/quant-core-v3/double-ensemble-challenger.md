# DoubleEnsemble 真实多标的挑战验收

**验收日期：** 2026-08-12  
**结论：** `NO_NET_EDGE`，不晋级、不替换现有模型，但 Stage A 的统一回归模型评价链路验收通过。

## 验收对象

- 数据：9 个 Eastmoney 真实 API ETF 1 分钟 exact snapshots，共 108,000 根原始 K 线，覆盖 `2026-05-28..2026-08-07`。
- 特征行：91,507 行；10,200 个统一 decision timestamps。
- 模型：固定 Qlib commit `79633dd9506ea689e5400dea0197717b5b3d74b7` 的 `DEnsembleModel`，对照为 native Ridge。
- 切分：3 个 walk-forward folds，最少 5,500 个训练 timestamps、每折 1,500 个测试 timestamps、6 timestamps purge。
- 执行：next-open、100 股整数手、10 万元/标的/折、万 2.5 佣金、2 bps 滑点、10% participation、持有 5 bars。
- 选股：两模型都输出 `EXPECTED_RETURN`，统一使用 `score >= 0.0005`；没有把回归值冒充概率。

9 个 `dataset_id@snapshot_id` 全部写入生成的报告 `sources`，正式工具只允许 exact 64 位 snapshot ID，不读取 `latest`。

## 可重复性

在两个独立输出目录完整执行 prepare、Qlib train/predict 和 executable evaluate，结果如下：

| 证据 | Run A | Run B |
| --- | --- | --- |
| input digest | `sha256:1c461f1b7e1d0846468562c07854b3213b753075525a38a7869582cf9ad0a709` | 相同 |
| fold digest | `sha256:d7bf21cad0a37898e0acb3a054a893d5d681d48863bc16410ab56bcccb483b27` | 相同 |
| prediction digest | `sha256:d4a9a95bd2cb61d83f5ef6b77a02f91b4dfa94aa6d4aa37db9fb47a5ba874eff` | 相同 |
| report digest | `sha256:8f8393694cf686f9bee7a99d370a4146ac32a433aa93aa0590e1d0a4ce08d504` | 相同 |

验收过程中发现 Qlib 上游 `feature_selection()` 使用 `pd.Index(set(...))`，导致不同 Python 进程的特征顺序漂移。AstraQuant adapter 现在既固定 NumPy 随机状态，也按输入列恢复 canonical feature order；两次全量训练已经逐预测复现。

## 真实结果

| 模型 | 扣费净收益 | 成交 | 胜率 | 正收益 folds | 最差单标的回撤 | 换手 | 状态 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| DoubleEnsemble | `-2.5082%` | 1,450 | `41.52%` | `0/3` | `19.87%` | `87.73` | `NO_NET_EDGE` |
| Ridge | `-1.8550%` | 631 | `37.56%` | `0/3` | `15.41%` | `39.23` | `NO_NET_EDGE` |

DoubleEnsemble 三折净收益为 `-4.5155% / -2.4946% / -0.5144%`；全部折在本次事后规则下归类为 `SIDEWAYS`。高流动性 4 标的共 889 笔，低流动性 5 标的共 561 笔；成交最多的 `512480.SSE` 为 401 笔（27.66%），净收益 `-9.4559%`。总佣金 `59,217.36` 元、滑点 `47,373.97` 元，模型增加的信号和换手没有转化为净优势。

## 判定与后续

这不是“模型没训练成功”，而是模型在当前短周期 ETF 分钟样本、统一执行约束下没有可交易优势。程序保留 DoubleEnsemble adapter 作为生产 challenger 基线，但禁止进入 Shadow/Paper。

Task 4 关闭后，下一批次按总路线启动 Kronos zero-shot 微计划；同时继续扩大真实 API 历史和市场状态。Kronos 使用官方预训练权重并复用本验收的 snapshot/fold/费用/执行报告协议，不替换自有模型，也不直接下单。

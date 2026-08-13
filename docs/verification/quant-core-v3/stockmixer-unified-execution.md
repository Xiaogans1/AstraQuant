# StockMixer 真实 9 ETF 统一执行验收

**验收日期：** 2026-08-13  
**状态：** `NO_NET_EDGE`  
**发布决定：** 不进入 Shadow/Paper；冻结本轮结果，不做事后阈值或超参数修改。

## 对程序的意义

StockMixer 已不是 demo：程序可以在一个共享模型中同时训练动态证券池，按 walk-forward fold 做无泄漏选模，并把预测交给与 Ridge、DoubleEnsemble、Kronos 相同的 A 股 ETF 执行器。训练、权重、预测和执行报告都能独立双跑复现。

这轮也给出了明确淘汰结论：当前 9 ETF、1 分钟、5 bars 标签和冻结阈值下，共享模型没有形成扣费后优势。工程能力保留，但该模型版本不能下单。

## 冻结口径

- 数据：9 个 Eastmoney exact snapshots，108,000 根 1 分钟 K 线，覆盖 `2026-05-28..2026-08-07`。
- Folds：3 个 walk-forward outer-test，每折 1,500 timestamps；训练内部另有 500 timestamps valid 和 6 timestamps purge。
- Score：`EXPECTED_RETURN`，冻结选择规则 `score >= 0.0005`。
- 执行：next-open 买入、持有 5 bars 后 next-open 卖出、100 股整数手、每标的每折 10 万元。
- 成本：万 2.5 佣金、最低佣金 0、ETF 免印花税/过户费、2 bps 滑点、10% participation。

Run A / Run B 的统一执行报告逐字节一致：

- 文件 SHA-256：`6baf96b2de966743b74916398151d151cd205629c215263522cb8b8d1214dee4`
- report digest：`sha256:7384942136aae84bcb10bc5b3071e074f1cb1b1e4e4fc82d54de7edded94b1ae`

## 真实执行结果

| 指标 | StockMixer |
|---|---:|
| 扣费净收益 | `-4.0930%` |
| 成交 | 2,123 |
| 选中信号 | 7,671 |
| 胜率 | `34.06%` |
| 正收益 folds | `0/3` |
| 最差单标的回撤 | `14.99%` |
| 换手 | `106.06` |
| 佣金 | `71,592.77` 元 |
| 滑点成本 | `57,274.66` 元 |

| Fold | 净收益 | 成交 | 胜率 | 最差单标的回撤 |
|---|---:|---:|---:|---:|
| fold-01 | `-5.8364%` | 850 | `34.12%` | `14.99%` |
| fold-02 | `-1.5596%` | 393 | `35.88%` | `7.71%` |
| fold-03 | `-4.8829%` | 880 | `33.18%` | `11.57%` |

## 与已冻结模型比较

| 模型 | 扣费净收益 | 成交 | 胜率 | 正收益 folds | 状态 |
|---|---:|---:|---:|---:|---|
| Ridge | `-1.8550%` | 631 | `37.56%` | `0/3` | `NO_NET_EDGE` |
| DoubleEnsemble | `-2.5082%` | 1,450 | `41.52%` | `0/3` | `NO_NET_EDGE` |
| StockMixer | `-4.0930%` | 2,123 | `34.06%` | `0/3` | `NO_NET_EDGE` |
| Kronos zero-shot | `-9.1663%` | 4,257 | `34.25%` | `0/3` | `NO_NET_EDGE` |

StockMixer 好于 Kronos，但差于简单 Ridge 与 DoubleEnsemble；复杂共享结构没有覆盖更多交易带来的费用与错误信号。本轮结果不支持进入 Stage C 或直接扩大模型复杂度。

## 重新梳理节点

下一轮先重新冻结 Stage B v2 实验设计，再写代码。重点不是换一个更大的网络，而是同时解决三个证据缺口：

1. 当前仅约两个半月、9 个 ETF，无法代表全 A 股和多市场状态；先扩大真实 API 历史、证券覆盖与 regime。
2. 重新比较不同任务与 horizon，确认 1 分钟 `next-open + 5 bars` 是否具有可学习且可交易的信噪比。
3. 保留统一模型方向，但要求任一新共享/关系/专家架构继续在相同 fold、成本和容量下战胜 Ridge；不允许只看训练 loss、IC 或单折盈利。

在新的数据范围、标签矩阵、预算和 release gate 预先冻结前，不启动 StockMixer v2 调参、Transformer 堆叠或正式 UI。


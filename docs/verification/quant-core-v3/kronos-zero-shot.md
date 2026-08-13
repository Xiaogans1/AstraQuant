# Kronos 真实 9 ETF Zero-shot 验收

**验收日期：** 2026-08-13  
**状态：** `NO_NET_EDGE`  
**发布决定：** 不进入 Shadow/Paper，不作为下单信号，不启动事后调参或微调。

## 这次完成了什么

AstraQuant 已经完整接入官方 `Kronos-base` 预训练模型，并让它直接消费东方财富真实 A 股分钟 K 线。模型源码、权重、输入窗口、GPU 环境、预测摘要和统一执行报告均有固定版本与 SHA-256 身份；官方源码未被修改，自有模型不依赖 Kronos 环境。

本次不是 demo 抽样。程序在 9 个 ETF、3 个 walk-forward folds 上生成并评价了 40,437 个真实预测窗口，每个窗口保留 3 条独立采样路径、5 分钟 horizon。两次完整 CUDA 推理与两次报告逐字节一致。

## 冻结输入与执行规则

- 数据：9 个 Eastmoney exact snapshots，共 108,000 根 1 分钟 K 线，覆盖 `2026-05-28..2026-08-07`。
- 标的：`159819.SZSE`、`159992.SZSE`、`512170.SSE`、`512480.SSE`、`512660.SSE`、`512690.SSE`、`512800.SSE`、`515030.SSE`、`515790.SSE`。
- 模型：`NeoQuasar/Kronos-base@2b554741eca47781b64468546e77fef3e85130e6`。
- Tokenizer：`NeoQuasar/Kronos-Tokenizer-base@0e0117387f39004a9016484a186a908917e22426`。
- 上游源码：`shiyu-coder/Kronos@67b630e67f6a18c9e9be918d9b4337c960db1e9a`。
- 切分：最少 5,500 个训练 timestamps、每折 1,500 个测试 timestamps、6 timestamps purge，共 3 折。
- 执行：next-open 买入、5 bars 后 next-open 卖出、100 股整数手、10 万元/标的/折、万 2.5 佣金、2 bps 滑点、10% participation。
- 选股：三模型统一使用 `score >= 0.0005`，并共享完全相同的 eligible rows、folds 和执行器。

Kronos 的 score 是模型预测的“decision close 到第 5 根未来 close”的 terminal-return 中位数；它作为 predeclared signal 进入 next-open 执行回测。DoubleEnsemble/Ridge 直接拟合 next-open holding return。因此这里公平比较的是三种信号在同一真实执行环境下的最终交易价值，不声称三者的原始回归 target 完全相同。

## 可重复性

| 证据 | Run A | Run B |
|---|---|---|
| 官方 GPU 推理耗时 | 43 分 59 秒 | 44 分 57 秒 |
| Kronos response 文件 SHA-256 | `2d9dc473498da0ff9acbd879cf3597628db9239f0e376b66395331fe4c0dc3ef` | 相同 |
| 修正后 report 文件 SHA-256 | `5e985e9720b7898cd5665a119ca361a8dad68d740bb6c7046e05c8163f6244cf` | 相同 |
| Kronos input digest | `sha256:37ccc18996c3003a52cee095911067772be82b225a37e92d1c2884b465b91d86` | 相同 |
| Fold digest | `sha256:aca9c6d91d996217709dcd1ec02da89ee21a1418c4fff4e1689deef393b59221` | 相同 |
| Kronos prediction digest | `sha256:c5a752064117bdc0245e85f358bfecbb473972cef4186cd625b6c55c83d56b31` | 相同 |
| Unified report content digest | `sha256:5c732e5b70443f97fa38699ab21291dae7567d8449df0d122554dcbcc828a9af` | 相同 |

运行环境为 Python `3.11.15`、PyTorch `2.7.1+cu128`、`cuda:0`、NVIDIA GeForce RTX 4060 Ti。推理进程只加载显式本地权重，不联网下载或解析 `latest`。

## 统一真实结果

| 模型 | 扣费净收益 | 成交 | 胜率 | 正收益 folds | 最差单标的回撤 | 换手 | 成交集中度 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Kronos zero-shot | `-9.1663%` | 4,257 | `34.25%` | `0/3` | `29.84%` | `203.34` | `12.43%` |
| DoubleEnsemble | `-2.5082%` | 1,450 | `41.52%` | `0/3` | `19.87%` | `87.73` | `27.66%` |
| Ridge | `-1.8550%` | 631 | `37.56%` | `0/3` | `15.41%` | `39.23` | `31.54%` |

Kronos 三折净收益依次为 `-10.7511% / -9.1676% / -7.5801%`，没有一个正收益 fold。它选择了 11,175 个信号，实际成交 4,257 笔，总佣金 `137,251.44` 元、滑点成本 `109,801.17` 元；更多信号和更高换手没有转化成净优势。

## 路径预测质量

校准真值严格使用与 Kronos 路径相同的 `DECISION_CLOSE_TO_TERMINAL_CLOSE` 五根 bar 收益，不再用 next-open 执行标签作代理：

- 方向准确率：`51.12%`
- Terminal return MAE：`0.2698%`
- p10–p90 路径区间覆盖率：`29.61%`
- 平均路径区间宽度：`0.2680%`

方向略高于 50% 但不足以覆盖费用与错误交易；名义 80% 的采样区间只覆盖约 29.6% 的真实 terminal returns，说明当前 zero-shot 路径对 A 股分钟 ETF 明显欠校准。未来任何 K 线图层只能称为“模型采样路径范围”，不能包装成统计置信区间。

## 决定与后续

1. Kronos 工程集成验收通过：官方权重、真实 K 线、CUDA 批量推理、可重复结果和统一 evaluator 均可用。
2. Kronos 交易模型验收失败：状态固定为 `NO_NET_EDGE`，不得进入 Shadow/Paper，也不得通过反向信号、降低阈值或挑选窗口事后包装。
3. 保留独立 runner、权重工具和研究报告；当前不开发“核预测”正式 UI，不接 ForecastCombiner，不阻塞自有模型。
4. 不立即微调。当前证据既显示域偏差/欠校准，也没有显示可利用的 zero-shot 净信息；只有扩大真实历史、horizon 和市场状态后出现稳定信息量，才另写 A 股适配计划。
5. 训练主线立即转入 StockMixer + dynamic universe 的全市场共享表征，不为当前 9 个 ETF 各训练一套独立模型。

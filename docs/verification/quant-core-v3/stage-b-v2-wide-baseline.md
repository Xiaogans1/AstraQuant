# Stage B v2 真实宽市场强基线验收

日期：2026-08-14

## 用户可用能力

程序已经能从东方财富真实 API 批量引导多年 A 股日线，在每个历史交易日动态选择当时满足历史长度、价格、流动性与交易状态条件的股票，并在统一 D1/D5/D10 标签、6 个时间外推 folds、3 个 seeds、真实费税/滑点/容量约束下比较模型。训练不再写死十只 ETF，也不会为每只股票维护独立模型。

## 冻结输入

- 原始引导：800 只普通 A 股候选 + `SHSE.000985` benchmark，10 年东方财富 API 日线，摘要 `sha256:b59a9d274ba91d7b3a5c331f2146fd0a534c09d6e5e29f739a59a9704495ada1`。
- 动态面板：2,427 个 sessions、690,335 条 context rows、2,065,164 条 D1/D5/D10 labels，摘要 `sha256:93405cdb9a0494aeadcf957f88db2b1e79e558ce39f57c8a31dd17ef575f827a`。
- Qlib 物化：718 只实际入选股票、2,058,999 行、173 个特征（15 个 AstraQuant context + 158 个官方 Alpha158），固定 Qlib commit `79633dd9506ea689e5400dea0197717b5b3d74b7`，摘要 `sha256:d56feb9ef1cc86f810ab99ba183db59a2282f6a4885b2f768e679d497093d972`。
- 运行语义：`EXPLORATORY_REAL_API_CURRENT_STATUS`。历史 ST/status 暂由当前名称与当日真实 bar 近似，不能标记为 FORMAL 或进入 Shadow/Paper。

## 结果

Ridge、LightGBM、Shared MLP、DoubleEnsemble 共 216/216 trials 完成，失败 0。传统基线两个全新训练运行的 trial identities、prediction digests 和全部核心指标一致；Shared MLP、DoubleEnsemble 均按逐 trial 检查点从真实中断处恢复。最终四模型报告从同一检查点恢复到两个全新输出目录后文件 SHA-256 一致。

| Horizon | Model | Mean RankIC | Positive folds | Base net | Adverse net | Severe net | Max drawdown | Gate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| D1 | Ridge | 0.04985 | 6/6 | +3.2949% | +2.5953% | +0.5017% | 30.11% | `NET_EDGE` |
| D1 | LightGBM | 0.04893 | 6/6 | +3.2764% | +2.5531% | +0.3892% | 33.45% | `NO_NET_EDGE` |
| D1 | Shared MLP | 0.05094 | 6/6 | +3.8179% | +3.1431% | +1.1226% | 28.28% | `NET_EDGE` |
| D1 | DoubleEnsemble | 0.04036 | 5/6 | +4.6667% | +3.9564% | +1.8307% | 33.50% | `NET_EDGE` |
| D5 | Ridge | 0.05623 | 6/6 | +1.9977% | +1.8969% | +1.5917% | 16.40% | `NET_EDGE` |
| D5 | LightGBM | 0.06299 | 6/6 | +1.4415% | +1.3204% | +0.9538% | 16.34% | `NO_NET_EDGE` |
| D5 | Shared MLP | 0.05544 | 6/6 | +2.1452% | +2.0118% | +1.6078% | 16.52% | `NO_NET_EDGE` |
| D5 | DoubleEnsemble | 0.04872 | 6/6 | +2.1728% | +2.0706% | +1.7611% | 12.45% | `NO_NET_EDGE` |
| D10 | Ridge | 0.05945 | 6/6 | +0.7859% | +0.7264% | +0.5460% | 9.92% | `NET_EDGE` |
| D10 | LightGBM | 0.07238 | 6/6 | +0.4318% | +0.3656% | +0.1649% | 8.31% | `NO_NET_EDGE` |
| D10 | Shared MLP | 0.05553 | 6/6 | +0.9690% | +0.8972% | +0.6795% | 11.58% | `NO_NET_EDGE` |
| D10 | DoubleEnsemble | 0.05848 | 6/6 | +0.9790% | +0.9353% | +0.8028% | 7.62% | `NO_NET_EDGE` |

Shared MLP 合并报告摘要：`sha256:536907f451f0aa29cf24738333dccfcb832af3d57d0c20e7ed00b31aaee0584f`；报告文件 SHA-256：`3AEC1012429C58341F78B8AE6FA962A62404B00A82637E14F83A00D0945757BD`。

最终四模型报告摘要：`sha256:9d89cec7eed138df99b38d11013dc892a6e5aa49e00fe0a71df6d9c4749e8c39`；报告文件 SHA-256：`43D61F8327FCA60EDF9CC0DBF33D673BA737A46964E1412158083ECC9B45D84D`。

| Aggregate model | Mean RankIC | Mean base net | Mean severe net | Worst drawdown | Delta net vs Ridge | Stable gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Ridge | 0.05518 | +2.0262% | +0.8798% | 30.11% | 0 | `NET_EDGE` |
| LightGBM | 0.06143 | +1.7166% | +0.5026% | 33.45% | -0.3096% | `NO_NET_EDGE` |
| Shared MLP | 0.05397 | +2.3107% | +1.1366% | 28.28% | +0.2845% | `NET_EDGE` |
| DoubleEnsemble | 0.04919 | +2.6062% | +1.4649% | 33.50% | +0.5800% | `NET_EDGE / INCUMBENT` |

## 裁决

真实宽市场截面标签通过可学习门。Shared MLP 在 D1 同时提高 RankIC、净收益和重压净收益，并把最大回撤从 Ridge 的 30.11% 降到 28.28%。DoubleEnsemble 的 D1 净收益最强，D5/D10 也保持正的压力净收益；按首轮结果前冻结的“D1/D5/D10 等权聚合、全周期至少 4/6 正 folds、三 seeds 净收益同方向、severe net 为正、容量无违约、相对 Ridge 聚合净收益至少提高 0.2%”唯一规则，程序选择 `DOUBLE_ENSEMBLE` 为 Batch 4 incumbent。不得按 horizon 另选对手或为 StockMixer 改组合/费用。

上述 net 为各 walk-forward trial 的平均组合收益，不是年化收益、未来收益承诺或实盘发布证据。下一阶段 StockMixer v2、MASTER 必须在同一矩阵上同时超过 DoubleEnsemble 的聚合 RankIC 与扣费净收益，且最大回撤不得超过 40.20%；不能只提高 IC 或只挑一个 horizon 宣称成功。

## 工程容量

- 优化前本地矩阵约 86 分钟；按 horizon 分片、fold 预处理复用及 Ridge 去重后约 47.5 分钟。
- D1/D5/D10 分别原子写检查点；同一检查点恢复到全新 output root 用时 4.87 秒且报告文件 SHA-256 一致。
- DoubleEnsemble 每个 trial 原子写检查点；任一后续 trial 失败时，已完成 trial 不重训。
- DoubleEnsemble 54 个 Qlib CPU trials 从 2026-08-13 21:19 至 2026-08-14 00:07 分段完成；两次进程中断后均只继续未完成 trial。
- Shared MLP 54 个真实 CUDA trials 约 40.7 分钟完成；按 16 个交易日 masked batch 并行，动态股票数不改变网络宽度。
- Shared MLP 完整 checkpoint 恢复到全新 output root 用时 7.61 秒，报告文件 SHA-256 一致。
- 四模型 216-trial 统一成本重评分约 14.1 分钟；完成后仅从检查点生成新输出用时 13.1 秒，第二次独立恢复用时 9.4 秒且报告文件 SHA-256 一致。
- Batch 4 共享时序面板已从同一 raw export/materialization 生成：718 股票、2,427 sessions、1,742,586 个 `time × instrument` 槽位和全部 2,058,999 个 D1/D5/D10 标签行。64 日 OHLCV/turnover 相对变化与 15 个同日 context 字段只保存一份，panel `154,143,661` bytes，实测 46.4–50.6 秒、峰值 working set `1.806 GB`。
- StockMixer v2 真实 D1 fold-01 seed-7 smoke 已在 RTX 4060 Ti 上完成两个全新输出根：628,603 fit、35,880 inner-valid、17,972 outer-test rows，分别耗时 434.97/439.20 秒，观察显存约 3.6 GB；response SHA-256 同为 `3EE3A31B51F35004B738426FF48D6D5F009780833F0006475CF382283B6A1D29`。该单 fold RankIC `0.035166`、base/adverse/severe net 为 `-9.8483%/-10.4779%/-12.3608%`，只作为工程 smoke 和早期风险信号，必须等待 54 trials 才能裁决。
- StockMixer v2 正式矩阵 54/54、0 失败。D1/D5/D10 RankIC 为 `0.041641/0.054960/0.064369`，base net 为 `+1.7308%/+3.2970%/+1.7308%`，severe net 为 `-0.7072%/+2.7350%/+1.4830%`，最差最大回撤 `27.4637%`、容量违约 0。三周期聚合 RankIC `0.053657` 高于 DoubleEnsemble，但聚合 base net `+2.2528%`、severe net `+1.1703%` 均低于 incumbent，最终状态 `NO_NET_EDGE`；D5 增益作为后续组合研究证据保留，不按周期拼接赢家。
- 三个全新输出根的面板 SHA-256 均为 `2F92FE7BFAF5C22A4D377AAEE289C2D2DB297941B61DD6C66F7AB1162075966F`，完整 manifest SHA-256 均为 `003E11044ECF13979109B898EBBD0B2D920A4DDBE300063D6F271B277801F5DC`。
- 32 GB Windows 机器单作业可运行；本地模型峰值约 20.5 GB，DoubleEnsemble 主/子合计约 18 GB，禁止并发两套训练矩阵。

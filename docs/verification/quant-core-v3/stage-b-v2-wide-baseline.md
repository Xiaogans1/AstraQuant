# Stage B v2 真实宽市场强基线验收

日期：2026-08-13

## 用户可用能力

程序已经能从东方财富真实 API 批量引导多年 A 股日线，在每个历史交易日动态选择当时满足历史长度、价格、流动性与交易状态条件的股票，并在统一 D1/D5/D10 标签、6 个时间外推 folds、3 个 seeds、真实费税/滑点/容量约束下比较模型。训练不再写死十只 ETF，也不会为每只股票维护独立模型。

## 冻结输入

- 原始引导：800 只普通 A 股候选 + `SHSE.000985` benchmark，10 年东方财富 API 日线，摘要 `sha256:b59a9d274ba91d7b3a5c331f2146fd0a534c09d6e5e29f739a59a9704495ada1`。
- 动态面板：2,427 个 sessions、690,335 条 context rows、2,065,164 条 D1/D5/D10 labels，摘要 `sha256:93405cdb9a0494aeadcf957f88db2b1e79e558ce39f57c8a31dd17ef575f827a`。
- Qlib 物化：718 只实际入选股票、2,058,999 行、173 个特征（15 个 AstraQuant context + 158 个官方 Alpha158），固定 Qlib commit `79633dd9506ea689e5400dea0197717b5b3d74b7`，摘要 `sha256:d56feb9ef1cc86f810ab99ba183db59a2282f6a4885b2f768e679d497093d972`。
- 运行语义：`EXPLORATORY_REAL_API_CURRENT_STATUS`。历史 ST/status 暂由当前名称与当日真实 bar 近似，不能标记为 FORMAL 或进入 Shadow/Paper。

## 结果

108/108 Ridge/LightGBM trials 与 54/54 Shared MLP trials 完成，失败 0。传统基线两个全新训练运行的 trial identities、prediction digests 和全部核心指标一致；Shared MLP 的完整报告从检查点恢复到全新输出目录后文件 SHA-256 一致。

| Horizon | Model | Mean RankIC | Positive folds | Base net | Adverse net | Severe net | Max drawdown | Gate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| D1 | Ridge | 0.04985 | 6/6 | +3.2949% | +2.5953% | +0.5017% | 30.11% | `NET_EDGE` |
| D1 | LightGBM | 0.04893 | 6/6 | +3.2764% | +2.5531% | +0.3892% | 33.45% | `NO_NET_EDGE` |
| D1 | Shared MLP | 0.05094 | 6/6 | +3.8179% | +3.1431% | +1.1226% | 28.28% | `NET_EDGE` |
| D5 | Ridge | 0.05623 | 6/6 | +1.9977% | +1.8969% | +1.5917% | 16.40% | `NET_EDGE` |
| D5 | LightGBM | 0.06299 | 6/6 | +1.4415% | +1.3204% | +0.9538% | 16.34% | `NO_NET_EDGE` |
| D5 | Shared MLP | 0.05544 | 6/6 | +2.1452% | +2.0118% | +1.6078% | 16.52% | `NO_NET_EDGE` |
| D10 | Ridge | 0.05945 | 6/6 | +0.7859% | +0.7264% | +0.5460% | 9.92% | `NET_EDGE` |
| D10 | LightGBM | 0.07238 | 6/6 | +0.4318% | +0.3656% | +0.1649% | 8.31% | `NO_NET_EDGE` |
| D10 | Shared MLP | 0.05553 | 6/6 | +0.9690% | +0.8972% | +0.6795% | 11.58% | `NO_NET_EDGE` |

Shared MLP 合并报告摘要：`sha256:536907f451f0aa29cf24738333dccfcb832af3d57d0c20e7ed00b31aaee0584f`；报告文件 SHA-256：`3AEC1012429C58341F78B8AE6FA962A62404B00A82637E14F83A00D0945757BD`。

## 裁决

真实宽市场截面标签通过可学习门。Shared MLP 在 D1 同时提高 RankIC、净收益和重压净收益，并把最大回撤从 Ridge 的 30.11% 降到 28.28%，相对净收益提高 0.5231 个百分点，成为 D1 challenger。D5/D10 虽略增净收益，但 RankIC 下降且相对净提升分别只有 0.1475/0.1830 个百分点，未达到冻结的 0.2% 门，不晋级。LightGBM 虽在 D5/D10 有更高 RankIC，但没有转化为更高扣费净收益。

上述 net 为各 walk-forward trial 的平均组合收益，不是年化收益、未来收益承诺或实盘发布证据。下一阶段允许 Shared MLP、DoubleEnsemble、StockMixer v2、MASTER 依序挑战，但必须在同一矩阵上同时改善净收益与风险，不能只提高 IC。

## 工程容量

- 优化前本地矩阵约 86 分钟；按 horizon 分片、fold 预处理复用及 Ridge 去重后约 47.5 分钟。
- D1/D5/D10 分别原子写检查点；同一检查点恢复到全新 output root 用时 4.87 秒且报告文件 SHA-256 一致。
- DoubleEnsemble 每个 trial 原子写检查点；任一后续 trial 失败时，已完成 trial 不重训。
- Shared MLP 54 个真实 CUDA trials 约 40.7 分钟完成；按 16 个交易日 masked batch 并行，动态股票数不改变网络宽度。
- Shared MLP 完整 checkpoint 恢复到全新 output root 用时 7.61 秒，报告文件 SHA-256 一致。
- 32 GB Windows 机器单作业可运行；本地模型峰值约 20.5 GB，DoubleEnsemble 主/子合计约 18 GB，禁止并发两套训练矩阵。

# Alpha158 公平特征对照设计

## 目标

在不改变东方财富数据来源、标签、walk-forward folds、模型参数、交易阈值和费用口径的前提下，用 Qlib 官方 Alpha158 特征替换现有十特征，判断样本外扣费净收益是否改善。

## 选择

采用“官方表达式引擎 + 东方财富内存数据源”。Host 导出原始 OHLCV/VWAP、训练行与每行对应的 bar index；隔离 runner 注册只读内存 `FeatureProvider`，直接读取固定 commit `79633dd9506ea689e5400dea0197717b5b3d74b7` 的 `Alpha158DL.get_feature_config()` 并由 Qlib expression engine 计算 158 个特征。

不采用 Qlib 示例数据，因为它会改变研究样本；不自行复刻 158 个 pandas 公式，因为难以证明与官方实现一致；不使用 Qlib 自带收益回测，因为它的成交和费用口径不同于 AstraQuant。

## 数据流

1. `build_training_set` 在现有训练行之外保存原始 bars 和 `row_bar_indices`。每个训练行只能引用当前或历史 bar。
2. Alpha158 export 将 `rows.parquet`、`bars.parquet`、folds、snapshot identity 和两个文件摘要冻结到 request。
3. Runner 校验全部摘要，调用官方 Alpha158 表达式，按 `row_bar_indices` 对齐训练行，逐 fold 训练同参数 Qlib LightGBM。
4. Host 使用现有 `score_fold_predictions()` 计算 AUC、毛收益、扣费净收益和交易数，报告 Alpha158 相对现有十特征的差值。

## 失败语义

- snapshot、request、rows、bars、commit 或 feature config digest 任一不符即拒绝。
- row/bar 映射越界、非单调、引用未来 bar 或预测覆盖不完整即拒绝。
- 允许滚动窗口不足产生 NaN，由 LightGBM 原生处理；不得因此删除测试行或改变 folds。
- Alpha158 特征名/数量必须与固定 Qlib commit 官方配置完全一致。

## 验收

- 同一 request 重复运行，特征摘要、预测和报告一致。
- 158 个特征由官方 config 与 expression engine 生成，使用东方财富 bars，不下载 Qlib 样例数据。
- Alpha158 与现有十特征的 test row/fold coverage 完全一致。
- 结论只看相同费用后的 OOS 结果，允许 Alpha158 不优于现有特征。


# Stage B v2 全市场截面训练设计

**日期：** 2026-08-13  
**状态：** 已批准，进入实施  
**上位约束：** `2026-08-12-production-training-architecture-design.md`

## 1. 决策背景

StockMixer 首轮已经完成真实数据训练、确定性双跑和统一执行评价，但在 9 个 ETF、约两个半月 1 分钟数据、5 bars 标签下得到 `-4.0930%` 扣费净收益、`0/3` 正收益 folds，正式状态为 `NO_NET_EDGE`。

这轮失败不能简单解释为“网络不够大”。当前输入只有五列 OHLCV，主评价却要求模型输出可直接按固定收益阈值交易的数值；同时模型的截面排序损失没有对应一个正式的截面组合策略。继续调学习率、阈值或扩大 StockMixer 层数会变成事后救结果。

官方 Qlib 基准将 Alpha158 定义为人工设计因子数据，将 Alpha360 定义为原始价量时序；其公开结果也表明模型复杂度本身不保证优于线性、MLP 或树模型。官方 MASTER 使用约 158 个个股因子和 63 个市场信息特征，并明确实施截面标签处理。Qlib 策略文档则明确指出：排序 score 不应自动解释为预期收益，score 的尺度处理属于策略或校准层。

因此 Stage B v2 不再是“StockMixer 第二次调参”，而是建立可持续的全市场截面 alpha 训练与组合链路，再让 StockMixer v2、MASTER 和强基线公平竞争。

## 2. 最终任务目标

Stage B v2 必须交付以下闭环：

`东方财富真实历史数据 → 动态 A 股 universe → 多 horizon 可执行标签 → 因子/价量/市场状态特征 → 全市场共享训练 → 截面 rank 与收益校准 → 长仓目标组合 → A 股真实执行评价`

完成标准不是某个模型能收敛，而是：

1. 所有模型在同一真实数据、universe、labels、folds、组合规则和成本下比较；
2. 至少一个共享模型在跨时期评价中稳定战胜 Ridge/LightGBM/DoubleEnsemble 最强基线；
3. 扣费后优势在延迟、滑点、容量和换手压力下仍成立；
4. 结果能进入后续 MASTER/HIST/TRA/DoubleAdapt 路线，而不是形成独立 demo。

允许最终结果为 `NO_LEARNABLE_EDGE`。若基础标签在强基线上都没有稳定信号，必须停止增加深度模型。

## 3. 方案选择

### 方案 A：继续调首轮 StockMixer

优点是代码最少。缺点是保留原始 OHLCV、短历史、分钟 ETF 和收益阈值错配，无法回答共享表征是否真正有效。拒绝。

### 方案 B：直接加载 MASTER 官方权重

MASTER 官方权重来自特定 CSI300/CSI800 数据、158 因子、63 个市场特征、截面处理和时间范围。未复现输入语义时直接加载，输出没有可比意义。只允许未来作为 exact-schema exploratory run，不作为 Stage B v2 主路径。

### 方案 C：信号底座 + 公平模型竞赛

先建立真实宽历史、执行一致的多 horizon 标签、Alpha158/价量/市场状态特征和 rank-aware 组合；然后依次比较线性/树/MLP、StockMixer v2 与 MASTER。采用此方案。

## 4. 数据与 universe

### 4.1 第一主战场

- 第一批正式任务使用 A 股日线截面选股，不再以 1 分钟 ETF 作为 BaseTarget 主训练集。
- 日线覆盖至少 5 年，目标 10 年；不足 5 年不得对共享深度模型作正式效果结论。
- 每个交易日使用当时已知的 trailing 60 日成交额和交易状态构建动态流动性 universe，目标 top 800；有效证券不足 300 时该日期不进入正式训练。
- 新股、退市、停牌、ST/风险警示和价格限制状态必须按当时可见信息处理，禁止用当前股票列表回填历史。
- 数据仍来自已锁定的东方财富真实 API snapshots；开源项目的数据只用于理解格式和复现实验，不进入 AstraQuant 模型。

### 4.2 后续周期

- 日线 Stage B v2 通过后，增加 5 分钟 `6/12/24 bars` 的轮动与短趋势任务。
- 1 分钟数据保留给 `INTRADAY_T` 专家，不承担统一 BaseTarget 的首轮证明。
- 不把日线、5 分钟和 1 分钟样本混为同一个无语义标签；共享 backbone 可以复用，但每个 task head 独立声明周期和执行策略。

## 5. 特征与标签

### 5.1 特征组

每个样本保留版本化 `FeatureSetSpec`，首批包括：

1. `ALPHA158_OFFICIAL`：由固定 Qlib commit 的官方表达式从东方财富 raw bars 计算；
2. `RELATIVE_OHLCV_SEQUENCE`：收益率、振幅、相对均线、量比、换手和波动序列，不直接输入不可比的绝对价格；
3. `MARKET_STATE_63`：复现 MASTER 的 CSI300/CSI500/全市场收益、成交额和多窗口均值/标准差语义；
4. `LIQUIDITY_RISK`：当时可见的成交额、波动、停牌/涨跌停和可执行容量；
5. Stage C 才加入行业、概念、图关系和潜在关系，不提前混入本轮归因。

特征预处理只拟合 inner-train。个股时序特征使用训练期 median/MAD robust normalization 并裁剪到 `[-3, 3]`；需要截面可比的特征按日期进行 `CSZScore/CSRank`。所有缺失、停牌和 universe presence 使用显式 mask。

### 5.2 标签矩阵

首批 `BASE_TARGET` 与 `CROSS_SECTIONAL_ROTATION` 共用以下真实执行区间：

- `D1`：下一交易日 open 到再下一交易日 open；
- `D5`：下一交易日 open 到第 5 个交易日后的 open；
- `D10`：下一交易日 open 到第 10 个交易日后的 open。

每个 horizon 同时产生：

- `RAW_RETURN`：真实可执行区间收益；
- `MARKET_EXCESS_RETURN`：减去同区间市场基准；
- `CS_RANK`：同日 eligible universe 内的分位 rank；
- `DOWNSIDE_RISK`：持有区间不利波动与最大不利移动。

训练时允许共享 backbone 加多任务 heads，但每个输出必须保持 `EXPECTED_RETURN`、`CROSS_SECTIONAL_RANK` 或 `RISK_SCORE` 语义，禁止混用阈值。

训练标签在每个日期只删除截面最低 2.5% 与最高 2.5% 的极端值；valid/test/inference 必须覆盖全部 eligible 股票，不得因为训练去极值而删除评价或预测对象。

## 6. 统一训练方式

- 默认把同一日期的全部 eligible 股票作为一个截面批次，全市场一起训练。
- 不按个股单独训练，也不在首批按板块拆模型。
- 板块、风格和流动性只作为特征及评估切片；只有统一模型在某类股票上持续出现可重复盲区时，Stage D 才允许轻量 specialist/adapter。
- 随机模型至少运行 3 个 seeds；所有 seeds 和失败 trial 都计入结果。
- 每个实验至少 6 个 chronological outer folds；每折 outer-test 不少于 60 个交易日，inner-valid 不少于 120 个交易日，训练历史不少于 3 年，purge 为最大 horizon 加 1 个交易日。
- outer-test 只允许一次冻结评价，不能用于选择 horizon、特征、loss 权重、Top-K 或校准参数。

## 7. 模型竞赛

按以下顺序执行，前一层没有信号时停止：

1. `Ridge / Linear Ranker`；
2. `LightGBM / DoubleEnsemble`；
3. `Shared MLP`；
4. `StockMixer v2`：使用相同因子/相对价量序列，保留动态 universe masks；
5. `MASTER`：固定官方源码/commit，复现 market-guided feature selection 与 momentary/cross-time correlation；
6. Stage B v2 通过后才进入 HIST、TRA、DoubleAdapt。

StockMixer 不再是默认生产 backbone，而是共享时序/截面结构的一个 challenger。MASTER 是本轮主要复杂 challenger，但必须战胜简单基线才能继续。

## 8. Rank-aware 目标组合

首轮统一组合策略冻结为：

- 只做多；每个再平衡日选择 rank top 10%，最多 50 只；
- 预测对象必须同时具有非负的 inner-valid Huber 线性校准预期收益；校准器只拟合 inner-valid 的 score→raw return 映射；
- 按 trailing volatility 反比形成初始权重，单证券目标权重不超过 3%；
- 每日组合换手上限 20%，并服从成交额 participation、涨跌停、停牌、T+1、费用和整数手约束；
- 所有模型使用同一 PortfolioPolicy，不能为不同模型单独挑 Top-K 或阈值。

`CROSS_SECTIONAL_RANK` 决定相对选择，`EXPECTED_RETURN` 只经过 inner-valid 校准后用于正收益过滤和组合强度。模型原始 rank score 不再直接与 `0.0005` 比较。

## 9. 晋级与停止门

### 9.1 标签可学习门

在启动 StockMixer v2/MASTER 前，至少一个 Ridge、LightGBM 或 DoubleEnsemble 必须同时满足：

- 6 个 outer folds 中至少 4 个 median daily Rank IC 为正；
- 6 个 folds 中至少 4 个扣费净收益为正；
- 聚合扣费净收益为正；
- 结果不是由单一股票、单一月份或单一行业贡献超过 35%。

否则本轮标记 `NO_LEARNABLE_EDGE`，回到数据、标签和 horizon 设计，不增加模型复杂度。

### 9.2 共享模型晋级门

StockMixer v2 或 MASTER 必须：

- 在完全相同的 task/folds/portfolio 下，聚合扣费净收益和 median Rank IC 同时超过最强基线；
- 至少 4/6 folds 扣费为正，且不能比最强基线少；
- 最差回撤不高于最强基线的 1.2 倍；
- 1/2 bar 延迟、2 倍滑点、participation 减半后仍保持聚合净收益为正；
- 三个 seeds 的结论方向一致。

达到这些条件只能进入 Shadow/Paper 候选准备，不能直接 Live。

## 10. 分批实施

### Batch 1：Task/Label/Portfolio contracts

实现多 horizon label contract、截面 rank/calibration 语义和统一 long-only target portfolio，先用已有数据完成确定性与无泄漏测试。

### Batch 2：真实日线宽历史矩阵

使用东方财富 API 批量构建动态 A 股日线 universe、Alpha158、相对价量与市场状态快照，输出 coverage 和 regime 报告。

### Batch 3：强基线与标签可学习性

在同一 6-fold matrix 上运行 Ridge、LightGBM、DoubleEnsemble、Shared MLP。若标签门失败，Stage B v2 在这里停止并重新设计。

### Batch 4：StockMixer v2 与 MASTER

只有 Batch 3 通过才实现/运行复杂 challenger；两者消费同一 immutable feature/label/fold artifacts。

### Batch 5：压力、组合与发布决定

统一运行延迟、滑点、容量、行业/月份/股票集中度和 seed 稳定性报告，决定 `NO_NET_EDGE`、`INSUFFICIENT_EVIDENCE` 或 `SHADOW_CANDIDATE`。

## 11. 明确不做

- 不在当前 9 ETF 首轮结果上降低阈值、反向信号或筛选表现最好 fold；
- 不立即堆叠更大的 Transformer；
- 不直接把 MASTER 官方样例数据或错误 schema 权重混入正式训练；
- 不按股票维护独立模型；
- 不在 Stage B v2 通过前开发正式选股 UI、自动下单或 Live 接口。

## 12. 参考实现

- [Microsoft Qlib benchmark](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)
- [Qlib portfolio score semantics](https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst)
- [Qlib processors](https://github.com/microsoft/qlib/blob/main/qlib/data/dataset/processor.py)
- [SJTU-DMTai MASTER](https://github.com/SJTU-DMTai/MASTER)
- [SJTU-DMTai StockMixer](https://github.com/SJTU-DMTai/StockMixer)
- [Qlib TRA](https://github.com/microsoft/qlib/tree/main/examples/benchmarks/TRA)
- [SJTU-DMTai DoubleAdapt](https://github.com/SJTU-DMTai/DoubleAdapt)

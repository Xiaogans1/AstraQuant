# StockMixer 全市场共享表征设计

## 1. 目标

在 AstraQuant Stage B 中增加一个真正跨证券共享训练的模型通道。模型一次接收同一决策时点的多只证券，学习指标、时间和市场横截面信息，输出语义为 `EXPECTED_RETURN` 的逐证券预测；不为每只证券训练独立模型。

首轮目标不是承诺 StockMixer 一定盈利，而是建立可重复、可扩展且可与 Ridge、DoubleEnsemble 公平比较的全市场共享训练能力。只有扣除统一费用和滑点后，在跨证券、跨时期和流动性分层上稳定改善，才允许进入后续 Shadow/Paper 候选。

## 2. 已确认的上游语义

官方来源固定为：

- repository: `https://github.com/SJTU-DMTai/StockMixer.git`
- commit: `cce13598afd3ff33ae317700a85ae08db0554652`
- paper: AAAI 2024, *StockMixer: A Simple yet Strong MLP-based Architecture for Stock Price Forecasting*

官方模型包含三段：

1. Indicator Mixing：在单个时间点混合 OHLCV 指标。
2. Multi-scale Causal Time Mixing：用上三角约束防止未来时间进入过去表示，并混合多个时间尺度。
3. Stock Mixing：把所有股票表示压缩为市场表示，再将市场信息回传给每只股票。

官方代码只作为只读语义标尺。官方 NASDAQ、NYSE、S&P500 样例数据不得进入 AstraQuant 正式训练或效果报告。

## 3. 为什么不直接原样运行

官方 `NoGraphMixer` 使用 `nn.Linear(stocks, hidden_dim)` 和 `LayerNorm(stocks)`，模型参数与固定股票数量及固定股票槽位绑定。这与 A 股上市、退市、停牌和动态 universe 不兼容。官方代码还存在以下研究实现限制：

- 缺失证券只在 loss 中遮罩，替代值仍进入 stock mixing。
- 同一窗口内任一日缺失就把整只证券样本遮罩，不能区分 `presence`、`tradable` 和 `label`。
- train/valid/test 索引写死，训练过程中每个 epoch 都读取 test 指标。
- 评价只包含无真实费率的研究指标，不能替代 AstraQuant 统一执行评价。

因此采用“语义移植 + 上游差分 + AstraQuant 统一评价”，不把官方训练脚本当作生产内核。

## 4. 采用的架构

### 4.1 隔离边界

- `external/StockMixer`：固定 commit 的官方只读子模块。
- `runners/stockmixer`：独立 Python/PyTorch 环境，只通过版本化 JSON + Parquet 与主进程交换。
- `packages/data/.../exports/stockmixer.py`：从 exact Eastmoney panel 和已声明 universe 生成不可变请求。
- `tools/research`：准备请求、调用 runner、接入现有统一执行评价。

主进程不 import PyTorch 或官方 StockMixer。StockMixer runner 失败时，现有 Ridge、LightGBM、DoubleEnsemble 和其他研究能力继续工作。

### 4.2 动态 universe panel

一个模型样本代表一个决策时点的完整横截面，张量语义为：

```text
features      [stock, lookback, indicator]
feature_mask  [stock, lookback]
presence_mask [stock]
tradable_mask [stock]
label_mask    [stock]
labels        [stock]
```

- `presence_mask`：证券在该时点属于已声明 universe，不能从“今天仍存在的股票列表”反推历史成员。
- `feature_mask`：对应证券和时间槽存在当时可见的真实 bar；停牌形成的空槽不会被零值伪装成行情。
- `tradable_mask`：当前执行事件具备可交易证据；停牌、缺 bar 或不可成交时为 false。
- `label_mask`：标签已经成熟且可用于指定 fold；它与是否属于 universe、是否可交易正交。

证券按稳定 `instrument_id` 排序，时间槽按共享市场时间轴对齐。缺失槽位数值填零，但任何归一化、时间混合、市场聚合、loss 和预测覆盖都必须显式使用 mask；零值本身不具有缺失语义。导出内容必须固定 source snapshot、universe identity、fold digest、特征列、lookback、label 和执行策略 identity。

### 4.3 动态 stock-to-market mixer

Indicator/Time Mixer 保留官方因果顺序和多尺度思想。固定 `N→m→N` 的 stock mixer 替换为共享参数的 masked market bottleneck：

1. 对每只有效证券表示应用相同的 `stock_to_market` 投影。
2. 只对 `presence_mask=true` 且至少有一个 `feature_mask=true` 时间槽的证券做 masked mean，形成市场表示。
3. 将市场表示广播回每只证券，与其自身表示拼接后经共享 `market_to_stock` 投影。
4. 不属于 universe 或整个窗口没有有效特征的证券输出强制为零，不参与归一化、loss 或梯度聚合。

该结构保持论文的 stock→market→stock 信息流，但参数量不依赖股票数量，并满足：

- 改变证券排列只会等价改变输出排列。
- 增加一个 masked 证券不会改变任何有效证券输出。
- 同一模型可在不同日期接收不同数量的证券。

StockMixer 本身不引入行业图、概念图或显式个股关系；这些属于 Stage C 的 MASTER/HIST，避免本阶段能力归因混乱。

## 5. 训练与评价

- 训练单位：整个 panel 一起训练，不分行业单独维护模型。
- 目标：与 Stage A 相同的未来可执行收益，输出 `EXPECTED_RETURN`。
- 切分：沿统一市场时间轴 walk-forward；同一时点所有证券只能处于同一 fold。
- 归一化：每个 fold 只用该 fold train 区间拟合，valid/test 只 transform。
- 模型选择：只使用 inner validation；outer test 在模型和阈值冻结前不可见。
- loss：masked MSE + 正确符号的 pairwise ranking loss；只有 `label_mask=true` 的证券进入。
- 执行评价：复用现有 next-open、100 股、真实费率、滑点、participation 和持仓约束，不采用论文的无成本 Sharpe 作为晋级依据。

首轮公平对照使用当前 9 个 exact Eastmoney ETF snapshots，目的仅是打通真实共享训练并验证可重复性。接口不得写死 9 或 10；随后扩大到具备足够历史覆盖的真实 A 股 universe。

## 6. 验收门

工程门：

- 官方 commit、关键源码和论文 digest 固定。
- 相同请求、seed 和设备两次产生相同 fold/prediction/report digest。
- 动态排列、masked 证券、停牌和新上市边界测试通过。
- runner 不读取官方样例数据，不从网络下载 latest 数据或代码。

效果门：

- 与 Ridge、DoubleEnsemble 消费相同 row set、folds、label、费用和执行策略。
- 报告至少包含净收益、交易数、正收益 folds、最大回撤、换手、IC、RankIC，以及按证券/流动性/时期的分层。
- 仅“能训练”、论文指标更高或单次回测盈利均不构成晋级。
- 未稳定优于简单基线时状态为 `NO_NET_EDGE` 或 `INSUFFICIENT_EVIDENCE`，但共享训练工程能力保留。

## 7. 首个实现批次边界

本批次只关闭三个可独立验收的能力：

1. 固定并验证官方上游。
2. 建立不可变动态 universe panel 请求。
3. 建立支持 mask 和任意股票数量的 StockMixer 模型核心。

完成后再进入真实训练 runner、超参数预算和 9 ETF 双跑。这个边界是重新检查显存、每折训练耗时和真实 panel 覆盖的关键节点，不提前把大规模训练参数写死。

# Multi-ETF Panel Evaluation Design

## 目标

把现有 10 只东方财富板块 ETF 分钟数据接入同一套时间样本外评估，扩大真实交易机会，并继续沿用 S3 的下一开盘成交、真实费率、滑点、容量和整数手语义。S5 只回答“跨标的后模型是否获得足够且可重复的净收益证据”，不降低阈值、不按标的调参，也不晋级模型。

## 方案选择

采用统一时间轴 panel，而不是以下两种方案：

- 不采用“每只 ETF 单独训练”：单标的数据仍短，容易得到十套互不兼容的小模型。
- 不采用“降低 0.5 阈值增加交易”：这会根据已见结果制造成交，无法说明模型真正改善。

统一 panel 将所有标的同一分钟放入相同 train/test 区间，模型跨标的学习共同的分钟结构；每个预测仍落回原标的 K 线独立成交。这样既扩大样本，又保留真实价格与流动性。

## 数据边界

首轮固定使用本地已经发布的 10 个 Eastmoney snapshot：

- `159819.SZSE`、`159992.SZSE`
- `512170.SSE`、`512480.SSE`、`512660.SSE`、`512690.SSE`、`512800.SSE`、`512880.SSE`
- `515030.SSE`、`515790.SSE`

每个输入必须保留 `dataset_id`、`source_snapshot_id`、`provider_id`、instrument 和 bar 范围。provider 不是 `eastmoney`、snapshot 缺失、行与 bar 映射不闭合时直接拒绝。首轮不调用网络，也不使用旧 `features-all.json`，而是从不可变 Parquet snapshot 重新构造 next-open 标签。

## 时间切分

`PanelObservation` 记录 global row、instrument、local row 和 decision timestamp。排序键固定为 `(timestamp, instrument_id, local_row_id)`。

fold 以唯一 decision timestamp 切分，而不是按拼接后的行号切分：

- 同一分钟的全部标的只能同时属于 train 或 test。
- 使用 expanding walk-forward。
- test 前删除 `holding_bars + 1` 个 decision timestamps，避免 next-open entry/exit 标签跨越训练边界。
- 所有模型共享完全相同的 folds、seed、threshold 和成本。

## 模型与成交

首轮比较 `NO_SKILL`、`LOGISTIC_REGRESSION`、`LIGHTGBM`。每个 fold 在 panel train rows 上训练，对 panel test rows 生成概率。随后按 instrument 将 global prediction 映射为 local row，并调用现有 `run_executable_backtest()`：

- `NEXT_OPEN_TO_NEXT_OPEN`
- ETF 免印花税和过户费
- 当前持久化佣金万 2.5、最低佣金 0
- 2 bps 滑点、10% participation、100 股整数手
- 每标的每 fold 独立 10 万元，汇总采用等资金权重

汇总报告输出每标的成交数/净收益/回撤，以及全 panel 的总交易数、等权净收益、胜率、成本和最差单标的回撤。由于当前回测器没有组合逐时权益曲线，禁止把“最差单标的回撤”冒充组合最大回撤。

## 结果门槛

- `< 30` 笔真实可执行 OOS trades：`INSUFFICIENT_EVIDENCE`。
- `>= 30` 笔但等权净收益 `<= 0`：`NO_NET_EDGE`。
- `>= 30` 笔且等权净收益 `> 0`：仅为 `CANDIDATE`，仍不能进入 Shadow/Paper。

首轮使用至少 5,000 个训练 timestamps 和三段各 1,500 timestamps 的 OOS；现有 51 个交易日经每日 feature warm-up 与标签尾部删除后共有约 10,164 个有效 decision timestamps。重复运行必须产生相同 JSON SHA-256。无论结果好坏都写入进度文档；不得改变 threshold 后覆盖原结论。

## 代码边界

- `packages/quant/src/astraquant_quant/panel_research.py`：panel、时间 fold、global/local 映射与等权执行汇总。
- `tools/research/run_panel_executable_backtest.py`：加载 exact snapshots、构建训练 bundle、运行三模型并生成确定性报告。
- `tests/quant/test_panel_research.py`：同 timestamp 不跨 fold、purge、映射和汇总。
- `tests/research/test_run_panel_executable_backtest.py`：CLI provenance、确定性和证据状态。

## 明确不做

- 不新增数据库、API、UI 或远程数据抓取。
- 不运行 Alpha158；S2 已证明 Alpha158 未优于 ASTRA10，S5 先验证多标的机会是否解决证据稀疏。
- 不优化阈值、holding bars、标的权重和每标的参数。
- 不发布模型、不自动下单。

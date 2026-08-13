# Kronos 基础模型独立集成设计

**日期：** 2026-08-12  
**状态：** 工程接入完成；zero-shot 交易验收为 `NO_NET_EDGE`
**目标：** 完整引入 Kronos 官方开源项目，并把它建设为与 AstraQuant 自有模型并存的独立 K 线基础模型能力。

## 1. 边界

- 官方源码以 Git submodule 放入 `external/Kronos`，固定上游 commit，保留完整仓库和同步能力。
- 不修改 `external/Kronos` 内的官方源码；AstraQuant 的输入转换、推理契约和预测映射放在独立的 `runners/kronos`。
- Kronos 不替换 DoubleEnsemble、StockMixer、MASTER 等自有训练路线，也不直接生成订单。
- Kronos、自有模型和未来其他模型统一输出声明过语义的 forecast，由组合层选择、比较或融合。

## 2. 数据与权重

- 直接使用官方公开的 `Kronos-base`、对应 tokenizer 和预训练权重，不进行从零预训练。
- 东方财富 API K 线作为日常推理输入、A 股评估数据及可选微调数据。
- 模型权重存放在 Git 已忽略的本地模型目录，不提交到 AstraQuant 仓库。
- 官方示例数据和 WebUI 保留在 submodule 中供理解与复现，但不作为 AstraQuant 正式行情源。

## 3. 分阶段接入

1. **上游封存：** 完整拉取源码，固定 commit，记录模型清单和目录边界。
2. **零样本推理：** 创建隔离 runner，加载官方 `Kronos-base`，把 AstraQuant OHLCVA 输入转换为官方接口。
3. **公平验证：** 在与现有 challenger 相同的数据切分、费用和 A 股执行语义下比较。
4. **可选适配：** 只有零样本结果显示明确的 A 股域偏差时，才微调 tokenizer 或 predictor。
5. **多模型融合：** 将价格路径、预期收益、波动和不确定性映射为标准 forecast，交给组合层使用。

### 3.1 未来产品能力

Kronos 验证通过后，在每个专业 K 线图提供一个独立的“核预测”按钮。默认关闭，用户主动点击后才加载预测图层，避免把模型生成路径冒充实际行情。图层至少展示：

- 多条可能的未来 K 线路径，而不是单一确定走势；
- 中位路径、上涨/下跌区间和不确定性带；
- 预测周期、输入截止时间、模型版本与数据周期；
- 对趋势、波动、支撑阻力和主要风险的结构化解释；
- 与真实行情颜色、线型和区域明确区分，并允许一键关闭。

该图层属于研究辅助能力，不直接出现“买入/卖出”指令。后续可把 Kronos 的预期收益、方向一致性、波动预测和不确定性转换成版本化因子，作为量化模型组合中的一个输入；组合层仍同时参考自有模型、市场状态、资金、基本面、风险和执行成本，Kronos 不拥有单独下单权。

### 3.2 开发优先级

上游源码封存完成后，Kronos 进入未来能力队列，暂不打断当前统一模型训练主线。当前必须先完成 DoubleEnsemble 真实多标的可执行验收，并继续推进既定的全市场共享训练架构；只有主线形成可复用的公平评价链路后，才启动 Kronos zero-shot runner。K 线预测图层排在 runner 与公平验证之后，综合因子排在预测稳定性验证之后。

## 4. 隔离保证

- 主进程不直接依赖 Kronos 的 Python 环境。
- Kronos runner 失败、缺权重或不可用时，自有量化模型仍可独立训练、回测和运行。
- Kronos 输出必须经过 AstraQuant 的真实费率、T+1、涨跌停、停牌和目标仓位评估；任何可视化未来 K 线都不直接等于交易指令。

## 5. 首批完成标准

- `external/Kronos` 能完整初始化并解析到固定官方 commit。
- AstraQuant 仓库不复制、修改或混入上游源码。
- 文档明确权重、源码、推理输入和自有模型的边界。
- 现有训练任务契约与 runner contract 测试保持通过。

## 6. 2026-08-13 验收结论

官方 `Kronos-base` 已使用 9 个 Eastmoney exact snapshots 完成 40,437 个 zero-shot 窗口的两次 CUDA 推理，两次响应逐字节一致。统一 next-open 执行回测中，Kronos 扣费净收益为 `-9.1663%`、4,257 笔成交、0/3 正收益 folds，结论为 `NO_NET_EDGE`。

因此本设计的隔离集成目标已经完成，但产品图层和组合因子条件尚未满足。当前保留 runner 与研究入口，不开发正式 UI、不进入 Shadow/Paper、不立即微调；训练主线转入 StockMixer 全市场共享表征。完整证据见 `docs/verification/quant-core-v3/kronos-zero-shot.md`。

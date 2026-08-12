# Kronos 基础模型独立集成设计

**日期：** 2026-08-12  
**状态：** 已批准  
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

## 4. 隔离保证

- 主进程不直接依赖 Kronos 的 Python 环境。
- Kronos runner 失败、缺权重或不可用时，自有量化模型仍可独立训练、回测和运行。
- Kronos 输出必须经过 AstraQuant 的真实费率、T+1、涨跌停、停牌和目标仓位评估；任何可视化未来 K 线都不直接等于交易指令。

## 5. 首批完成标准

- `external/Kronos` 能完整初始化并解析到固定官方 commit。
- AstraQuant 仓库不复制、修改或混入上游源码。
- 文档明确权重、源码、推理输入和自有模型的边界。
- 现有训练任务契约与 runner contract 测试保持通过。

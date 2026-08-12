# AstraQuant Kronos Runner Boundary

该目录是 AstraQuant 与 [Kronos](https://github.com/shiyu-coder/Kronos) 之间的独立集成边界。

## 上游源码

官方项目完整保存在 `external/Kronos` Git submodule。初始化工作区后运行：

```powershell
git submodule update --init --recursive
```

`external/Kronos` 视为只读上游代码。AstraQuant 的数据转换、进程契约、预测语义映射和测试只写在 `runners/kronos`，不得直接修改 submodule；需要升级时显式更新 gitlink 和 `upstream-manifest.json`。

## 模型权重

默认候选是官方公开的 `NeoQuasar/Kronos-base` 和 `NeoQuasar/Kronos-Tokenizer-base`。权重由 runner 下载到本地模型缓存，`.safetensors`、`.pt`、`.pth` 等文件受根 `.gitignore` 保护，不提交进 AstraQuant。

官方源码、官方示例和官方 WebUI 被完整保留用于理解与复现，但 AstraQuant 正式运行的 K 线输入来自自己的行情管线。

## 与自有模型的关系

- Kronos 是独立的 K 线基础模型 challenger，不替换 DoubleEnsemble、StockMixer、MASTER 或其他自有模型。
- 主进程不会直接安装或 import Kronos 依赖；后续 runner 使用独立 Python 环境和进程契约。
- Kronos 缺失、失败或未加载权重时，自有训练、回测和交易流程仍然可用。
- Kronos 只产生价格路径、预期收益、波动和不确定性等 forecast；它不直接产生订单。
- forecast 必须继续经过 AstraQuant 的模型组合、目标仓位、A 股费用、T+1、涨跌停、停牌和风险控制。

## 接入顺序

1. 使用官方预训练权重完成 zero-shot 批量推理。
2. 在相同 snapshot、fold、费用和执行语义下与现有 challenger 公平比较。
3. 只有验证出明确的 A 股域偏差时才进行微调，不从零重复预训练。
4. 通过研究门槛后才进入多模型组合和产品展示。

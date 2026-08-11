# Quant Core v3 当前进度（2026-08-11）

## 已完成

- Phase 0：49/49，旧 demo 数据、模型和 Paper 语义已隔离。
- Phase 1a：Tasks 1–6 已完成；真实 API 接入、资格、capture、batch 与后台任务可用。剩余真实 endpoint 最终 sign-off。
- Phase 1b：Tasks 1–4 已完成；canonical、时间可见性、coverage/quality、snapshot v2 可用。

## 当前开发

- Strategy Fast Lane S1：公平开源基线矩阵，6/6 已完成；同一 Eastmoney snapshot 可比较 no-skill、Logistic Regression 与 LightGBM 的 OOS 扣费净收益。
- 下一阶段：S2 Qlib 对照，先让 Qlib Alpha158/LightGBM 消费与 S1 相同的样本和 folds，再比较是否真正增益。

## 延后而非删除

- Phase 1b publication trusted head、Merkle、防回滚与完整故障注入。
- 完整 research registry/lockbox/UI。
- 上述内容在模型准备进入 Shadow/Paper 前恢复，不阻塞当前策略效果研究。

## 下一结果

使用同一份 Eastmoney 数据比较无模型、Logistic Regression 和 LightGBM，展示 OOS 扣费净收益并给出 `CHALLENGER` 或 `NO_EDGE`。

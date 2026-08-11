# Quant Core v3 当前进度（2026-08-11）

## 已完成

- Phase 0：49/49，旧 demo 数据、模型和 Paper 语义已隔离。
- Phase 1a：Tasks 1–6 已完成；真实 API 接入、资格、capture、batch 与后台任务可用。剩余真实 endpoint 最终 sign-off。
- Phase 1b：Tasks 1–4 已完成；canonical、时间可见性、coverage/quality、snapshot v2 可用。

## 当前开发

- Strategy Fast Lane S1：公平开源基线矩阵，6/6 已完成；同一 Eastmoney snapshot 可比较 no-skill、Logistic Regression 与 LightGBM 的 OOS 扣费净收益。
- S2a Qlib 公平对照：3/3 已完成；同一 Eastmoney 行集/folds 可在固定 commit 的独立 Qlib LightGBM runner 训练，再由 AstraQuant 统一按相同费率与阈值评分。
- 当前阶段：S2b Alpha158 特征对照；保持数据日期、walk-forward folds 和成本不变，只比较现有十特征与 Alpha158 的 OOS 净收益。

## 延后而非删除

- Phase 1b publication trusted head、Merkle、防回滚与完整故障注入。
- 完整 research registry/lockbox/UI。
- 上述内容在模型准备进入 Shadow/Paper 前恢复，不阻塞当前策略效果研究。

## 下一结果

在真实 Eastmoney snapshot 上生成 native LightGBM/Qlib LightGBM 差异报告，然后接入 Alpha158 特征组；任何模型只有 OOS 扣费净收益为正才保留为候选。

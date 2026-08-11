# Strategy Effect Fast Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在真实 Eastmoney 数据上先建立可比较、可复现、扣费后的开源模型基线，再逐步接入 Qlib 与 A 股目标仓位。

**Architecture:** 复用现有 snapshot/feature 工具，不先新建数据库和 UI。研究核心提供统一 walk-forward folds、模型 adapter 和收益报告；CLI 读取 Eastmoney 数据集生成机器可读矩阵。后续 Qlib 必须消费同一行集和 folds。

**Tech Stack:** Python 3.12、scikit-learn、LightGBM、PyArrow/Parquet、pytest，后续 Qlib isolated runner。

---

## S0 已有研究地基

- [x] Eastmoney API/bridge、batch capture 与后台任务。
- [x] canonical/PIT/coverage/quality 与 snapshot v2 原子发布。
- [x] legacy demo 模型隔离，不作为正式成绩。
- [ ] Phase 1a 真实 endpoint 实证 sign-off；不阻塞本地 Eastmoney 策略实验。
- [ ] publication trusted-head/security sign-off；延后到 Shadow/Paper。

## S1 公平开源基线矩阵（当前）

- [ ] 修正 label 与 `future_return` 使用同一 entry/exit 区间。
- [ ] 建立 expanding walk-forward folds，测试期严格晚于训练期。
- [ ] 在同一 folds 比较 `NO_SKILL`、`LOGISTIC_REGRESSION`、`LIGHTGBM`。
- [ ] 统一扣除双边费率，输出 fold 和汇总 AUC/gross/net/trades。
- [ ] 相同输入/seed 报告确定性一致；全模型无净优势时返回 `NO_EDGE`。
- [ ] 提供读取现有训练 JSON 的 CLI，随后连接 exact Eastmoney snapshot builder。

## S2 Qlib 对照

- [ ] 导出与 S1 相同的行集/folds 到 Qlib handler。
- [ ] 固定 Qlib commit/环境，运行 Alpha158 + LightGBM。
- [ ] 对比原生 LightGBM 与 Qlib 的 row set、处理器、预测和净收益差异。

## S3 A 股净收益回测

- [ ] 接入真实佣金、最低佣金、印花税、过户费和滑点。
- [ ] 使用下一可执行价格，禁止当前 close 同 bar 成交。
- [ ] 输出容量、换手、回撤、胜率和分阶段净收益。

## S4 策略落地

- [ ] 将最佳 forecast 转成目标仓位，而不是直接产生买卖按钮。
- [ ] 加入 T+1 可卖量、底仓做 T、风险减仓和目标不可达原因。
- [ ] Shadow/Paper 前恢复 publication ledger、模型 registry 与晋级门。

## 当前退出标准

S1 完成时，用户能对同一份真实数据直接看到三个模型谁更好、扣费后是否仍有优势；不能用 AUC 单指标宣称策略有效。

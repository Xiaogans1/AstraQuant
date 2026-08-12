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

- [x] 修正 label 与 `future_return` 使用同一 entry/exit 区间。
- [x] 建立 expanding walk-forward folds，测试期严格晚于训练期。
- [x] 在同一 folds 比较 `NO_SKILL`、`LOGISTIC_REGRESSION`、`LIGHTGBM`。
- [x] 统一扣除双边费率，输出 fold 和汇总 AUC/gross/net/trades。
- [x] 相同输入/seed 报告确定性一致；全模型无净优势时返回 `NO_EDGE`。
- [x] 提供读取现有训练 JSON 的 CLI，并在训练集固化 Eastmoney provider 与 source snapshot identity。

## S2 Qlib 对照

- [x] 导出与 S1 相同的行集/folds 到 Qlib handler。
- [x] 固定 Qlib commit/Python 环境，以共同十特征运行 Qlib LightGBM。
- [x] 对比原生 LightGBM 与 Qlib 的 row set、folds、预测和净收益差异。
- [x] 保持 row set/folds/成本不变，增加 Alpha158 特征组并与现有十特征比较。

## S3 A 股净收益回测

- [x] 接入真实佣金、最低佣金、印花税、过户费和滑点。
- [x] 使用下一可执行价格，禁止当前 close 同 bar 成交。
- [x] 输出容量、换手、回撤、胜率和分阶段净收益。

## S4 策略落地

- [x] 将具备足够证据的 forecast 转成目标仓位，而不是直接产生买卖按钮；证据不足时保持原目标并 HOLD。
- [x] 加入 T+1 可卖量、底仓做 T、风险减仓和目标不可达原因。
- [ ] Shadow/Paper 前恢复 publication ledger、模型 registry 与晋级门。

## S5 多标的策略证据

- [x] 任意 Eastmoney dataset IDs 可进入统一时间 panel，同一分钟不跨 train/test。
- [x] 预测回落到各标的真实 K 线，复用 next-open、费率、滑点、容量和整数手执行。
- [x] 首轮 10 ETF、44,934 OOS rows 重复运行一致；LightGBM 仍证据不足，Logistic Regression 仅形成弱候选。

## S6 跨时间稳定性与更长历史

- [x] 多标的报告增加逐 OOS fold 的日期、净收益、交易数、胜率、回撤和盈利标的数，不再只看全期汇总。
- [x] 用首轮 10 ETF 真实 Eastmoney 快照重复运行两次，报告 digest 一致。
- [x] 确认 Logistic Regression 只有 1/3 folds 为正；当前汇总正收益不能视为稳定优势，继续 HOLD。
- [ ] 通过真实 API 扩展分钟历史和标的覆盖，在相同 `0.5` 阈值、folds、费用与执行约束下重跑。

## 当前退出标准

用户能对同一份真实数据直接看到三个模型谁更好、扣费后是否仍有优势，以及优势是否跨时间段和标的分散存在；不能用 AUC 或全期总收益单指标宣称策略有效。

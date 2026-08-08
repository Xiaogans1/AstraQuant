# AstraQuant 量化核心学习文档

> 用途：给研究量化模型的朋友了解 AstraQuant 当前量化核心的模型、架构层次与开源参照。
> 更新时间：2026-08-07
> 本文档描述的是**已实现并运行**的量化核心（秒级 ML 基线里程碑），不是愿景。

---

## 1. 一句话总结

AstraQuant 量化核心 = **真实分钟级行情 → 防泄漏特征 → LightGBM 模型（经发布门槛批准）→ LEAN 式策略分层（信号→目标仓位→风控→执行）→ 本地模拟撮合**。规则策略作为回退路径，且已在真实数据上验证为亏损，改为只出建议不出手。

当前模型：**LightGBM 二分类**（预测未来 5 分钟上涨概率），特征为 10 个分钟级微观结构特征，训练/评估采用 **Purged/Embargo 时间切分**与**含费用收益**口径。

---

## 2. 架构层次（对应 QuantConnect LEAN 分层思想的落地）

```
真实行情（东财掘金，5 秒轮询）      ← 数据源
   ↓
在线特征（1 分钟 K 线 → 10 特征）    ← AlphaModel 输入
   ↓
AlphaModel（已批准 LightGBM 模型 / 规则回退）
   ↓
PortfolioConstructor（信号强度 → 目标仓位，100 股整数倍）
   ↓
RiskPolicy（现金、T+1 可用、仓位上限）
   ↓
ExecutionPolicy（目标变化 → 委托意图 → 本地虚拟撮合）
   ↓
账本（现金/持仓/订单/成交/权益/审计）
```

各层职责与当前实现：

| 层 | 职责 | 当前实现 |
| --- | --- | --- |
| UniverseSelector | 候选池（未实现，当前=账户持仓） | 计划中 |
| AlphaModel | 输出方向+强度 | `lgbm-minute-001`（AUC 0.65） |
| AlphaEnsemble | 多模型组合（未实现） | 计划中 |
| PortfolioConstructor | 信号→目标仓位 | `build_target_position`：预算=权益×仓位上限×强度/100，向下取整到 100 股 |
| RiskPolicy | 账户/组合/标的风控 | 现金不足、T+1 可用不足、单标的上限 |
| ExecutionPolicy | 目标→委托 | 模型信号自动执行；规则回退只 SUGGESTED |

**关键设计**：信号只产生"目标仓位"，不直接下具体数量；风控在委托前拦截；同一决策幂等（重复事件不重复下单）；所有决策可审计（决策 ID、信号、风控结果、订单、成交全落库）。

---

## 3. 模型详情

### 3.1 LightGBM 分类器（当前唯一生产模型）

- **任务**：二分类，预测未来 5 分钟收益 ≥ +0.5% 的概率
- **特征（10 个，均只用历史数据）**：
  - 收益：`return_1/3/5/10`（1/3/5/10 根 1 分钟 K 线收益）
  - 波动：`volatility_5`（5 根区间振幅）
  - 量价：`vwap_deviation`（现价相对 30 根 VWAP 偏离）、`volume_ratio`（当前量/30 根均量）
  - 位置：`day_high_position`（日内高低点位置）
  - 均线：`ma5_gap`、`ma20_gap`（现价相对均线偏离）
- **超参**：LGBMClassifier，n_estimators=120、lr=0.05、num_leaves=31、min_child_samples=30
- **推理阈值**（真实数据校准）：预测上涨概率 ≥ 0.5 → 买入；≤ 0.35 → 卖出；中间观望
- **样本**：4 只 ETF 的真实分钟线，16,774 行，约 20 个交易日
- **样本外评估**：AUC 0.65、含费用净收益 +0.7%（test 集）
- **历史回放**（样本内）：4 标的 20 天全盈利 +1.5%~+17.4%，胜率 63%~83%，日均 0.7-2 笔

### 3.2 规则策略 baseline-v1（对照/回退，已禁用自动交易）

- 日内动量+量能突破：5 分钟涨幅 ≥0.3% 且 MA5>MA20 且量比 ≥1.5 → 买；5 分钟跌幅 ≥0.3% 且 MA5<MA20 → 卖
- **真实数据检验结论：系统性亏损**（4 标的 20 天全部为负）→ 回退路径只出建议不成交
- 保留价值：作为模型能力的对照基线（文档要求"不因 AI 标签跳过简单基线"）

### 3.3 模型发布门槛（文档 5.3 落地）

模型必须通过以下门槛才能进入实时环产生委托：

1. 防未来泄漏（特征只用过去、标签用未来完成区间、按交易日重置窗口）
2. Purged/Embargo 时间切分（标签区间与训练集隔离）
3. 含费用评估（净收益 = 毛收益 − 双边费用×交易次数）
4. **AUC > 0.55 且含费用净收益 > 0**（硬性门槛，注册表 API 强制）
5. 人工批准（`POST /models/{id}/approve`），批准后不可修改

未批准/工件缺失/行情非 LIVE → 回退规则策略（只建议）。

---

## 4. 防泄漏与评估方法（研究重点）

- **特征防泄漏**：第 i 根 bar 的特征只用 bars[0..i]；标签用未来第 i+5 根完成后的收益，未来 bar 不足则丢弃
- **日边界重置**：特征窗口按交易日分组，隔夜跳空不污染日内统计
- **Purged/Embargo**：训练/测试按时间位置切分（7:3），测试起点额外后移 5 根（embargo），标签重叠区间不跨切分线
- **确定性**：同一输入（bars+模型+参数）→ 同一输出（决策/成交/权益曲线），回放引擎强制验证
- **口径**：回测含双边费用（佣金万 2.5 + 过户费），不做"无摩擦"假设

---

## 5. 开源项目与资料参照

AstraQuant 不 Fork 任何项目，保留自有领域契约，通过借鉴成熟项目设计（详见 `docs/research/open-source-comparison.md`）：

| 项目 | 借鉴方向 | 链接 |
| --- | --- | --- |
| QuantConnect LEAN | Universe/Alpha/Portfolio/Risk/Execution 策略分层；回测与实盘一致生命周期 | https://github.com/QuantConnect/Lean |
| Qlib（微软） | 数据/因子/模型/评估/实验记录的研究管线 | https://github.com/microsoft/qlib |
| vn.py | 国内 A 股/期货语义、事件引擎 | https://github.com/vnpy/vnpy |
| NautilusTrader | 事件驱动、确定性时钟、订单状态机、回放 | https://github.com/nautechsystems/nautilus_trader |
| hftbacktest | Tick/盘口回放、延迟与部分成交模型 | https://github.com/nkaz001/hftbacktest |
| DeepLOB | 五档盘口深度学习的 challenger 模型方向 | https://arxiv.org/abs/1808.03668 |
| RD-Agent（微软） | 因子/模型协同研究自动化（规划中） | https://github.com/microsoft/RD-Agent |
| QuantStats | 收益/回撤/风险指标定义 | https://github.com/ranaroussi/quantstats |
| OpenBB | Provider 抽象与产品体验（仅借鉴） | https://github.com/OpenBB-finance/OpenBB |

**借鉴策略**：不直接拼接多个框架，避免多套时间/订单/账户口径；外部项目通过适配器或可选 Provider 接入，许可证边界明确（Qlib MIT、vn.py MIT、LEAN Apache-2.0、NautilusTrader LGPL-3.0 谨慎评估、OpenBB AGPL 不复制核心）。

---

## 6. 数据源与工具链

- **数据源**：东财掘金量化终端（真实只读行情，分钟线 + 实时快照；股票约 3 秒、指数约 5 秒频率）
- **数据治理**：分钟线录制为不可变 Parquet 快照（按交易日分区），DuckDB 查询
- **研究工具链**（`tools/research/`）：
  - `fetch_minutes.py`：录制真实分钟线
  - `build_training_set.py`：快照 → 带标签训练集 JSON
  - `train_model.py`：训练 + Purged/Embargo 评估 + 保存模型工件
  - `calibrate_thresholds.py`：多阈值网格校准（真实数据）
  - `replay_model.py`：**任意标的/时间段的历史回放**（选股票某时段跑模型看表现）
  - `publish_model.py`：发布门槛校验 + 注册批准
  - `evaluate_rule_baseline.py`：规则策略回测检验

---

## 7. 当前局限与下一步（诚实的边界）

1. **样本内偏置**：回放结果包含训练时段，乐观；下周起的模拟盘是样本外验证
2. **AUC 0.65 是微弱预测力**：分钟级预测噪声大，需更长时间数据验证稳定性
3. **5 秒轮询**：非事件推送（文档的秒级事件总线未实现）
4. **无盘口特征**：当前只有 OHLCV 分钟特征，OFI/盘口不平衡待东财数据能力评估
5. **单模型**：无 AlphaEnsemble、无 DeepLOB challenger
6. **无 Deflated Sharpe / 压力测试 / REPLAY 完整模式**（回放引擎已就绪，未接绩效指标体系）

---

## 8. 推荐阅读路径（给研究者）

1. `docs/superpowers/specs/2026-08-06-ai-quant-portfolio-platform-design.md` — 完整产品/架构设计
2. `docs/research/open-source-comparison.md` — 开源项目评估与借鉴矩阵
3. `docs/architecture/paper-trading-ledger.md` — 账本与资金语义
4. 代码入口：
   - `packages/quant/src/astraquant_quant/research_features.py` — 特征与标签
   - `packages/quant/src/astraquant_quant/strategy_layer.py` — 分层与目标仓位
   - `packages/quant/src/astraquant_quant/replay.py` — 回放引擎
   - `tools/research/train_model.py` / `calibrate_thresholds.py` — 训练与校准
   - `packages/api/src/astraquant_api/paper_strategy_service.py` — 实时环集成

# Kronos Zero-shot Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` task-by-task. Do not modify `external/Kronos`.

**Goal:** 直接加载官方 `Kronos-base` 预训练权重，用 AstraQuant 的 Eastmoney exact snapshots 完成可重复的 A 股 zero-shot 路径预测，并接入已经验收的 expected-return executable evaluator。

**Program value:** 为每个 K 线窗口提供“未来多条可能路径 + 中位预期收益 + 不确定性”，既可独立评估，也可在未来验证通过后成为组合因子；它不替换自有模型、不直接下单，失败时不影响现有量化核心。

**Architecture:** 主 workspace 只负责 exact snapshot、窗口/fold 和执行评价；`runners/kronos` 使用独立 Python 环境，通过版本化 JSON/Parquet contract 调用只读 `external/Kronos`。官方权重显式 pin 到 revision 和本地文件 digest，正式运行禁止静默下载 `latest`。首批只做 zero-shot，不微调 tokenizer/model。

**Fairness baseline:** 复用 [DoubleEnsemble Task 4 验收](../../verification/quant-core-v3/double-ensemble-challenger.md) 的 9 个 exact snapshots、3 folds、next-open、费用、滑点、容量、持有周期和 `score >= 0.0005` 选择规则。Kronos 产生 `EXPECTED_RETURN`，不得把生成路径解释成确定价格或概率。

---

## Task 1: 冻结 Kronos 推理契约与权重身份

**Executable micro plan:** `docs/superpowers/plans/2026-08-13-kronos-task1-contracts.md`

**Files:**

- Create: `contracts/kronos-runner/v1/request.schema.json`
- Create: `contracts/kronos-runner/v1/response.schema.json`
- Create: `runners/kronos/pyproject.toml`
- Create: `runners/kronos/.python-version`
- Create: `runners/kronos/src/astraquant_kronos_runner/contracts.py`
- Create: `runners/kronos/tests/test_contracts.py`
- Modify: `runners/kronos/upstream-manifest.json`

- [x] Red：拒绝非 exact snapshot、未知 upstream commit、未 pin model/tokenizer revision、缺本地 weight digest、非法 OHLCVA schema、非正 context/horizon/sample count。
- [x] Request 固定 `schema_version`、source/fold/row digests、model/tokenizer IDs + revisions + weight digests、device policy、seed、context length、horizon、sampling config。
- [x] Response 固定逐 `fold_id/row_id/instrument_id/decision_time` 的路径摘要、`expected_return`、方向一致性、波动和不确定性，并回传全部输入/环境 identity。
- [x] 权重允许预先下载到 Git 忽略目录，但 runner 只读显式本地路径并重算 SHA-256；下载/缓存准备是独立命令，不发生在正式 evaluate 中。
- [x] 运行 runner contract tests、Ruff；提交 `feat(kronos): 冻结零样本推理契约`。

## Task 2: 导出无泄漏 K 线窗口

**Executable micro plan:** `docs/superpowers/plans/2026-08-13-kronos-task2-window-export.md`

**Files:**

- Create: `packages/data/src/astraquant_data/exports/kronos.py`
- Modify: `packages/data/src/astraquant_data/exports/__init__.py`
- Create: `tests/data/test_kronos_export.py`

- [x] Red：窗口包含 decision time 之后行情、跨午休/跨日时间戳伪连续、OHLC 不合法、volume/amount 单位缺失、context 不足、snapshot identity 漂移时 fail closed。
- [x] 从统一 panel 生成 canonical OHLCVA windows；每个窗口只含 `event_time <= decision_time`，未来 timestamps 由已 pin 交易日历 Protocol 生成并写入 request。
- [x] request `rows` 和 `KronosExport.eligible_row_ids` 已形成显式 eligibility mask；Task 4 的公平评价必须用它同步筛选 Kronos、DoubleEnsemble、Ridge。
- [x] Parquet bytes、request digest 和 window ordering 重跑一致；提交 `feat(data): 导出Kronos真实K线窗口`。

## Task 3: 实现隔离 zero-shot runner

**Executable micro plans:**

- `docs/superpowers/plans/2026-08-13-kronos-task3a-isolated-runner.md`
- `docs/superpowers/plans/2026-08-13-kronos-task3b-official-adapter.md`

**Files:**

- Create: `runners/kronos/src/astraquant_kronos_runner/__init__.py`
- Create: `runners/kronos/src/astraquant_kronos_runner/__main__.py`
- Create: `runners/kronos/src/astraquant_kronos_runner/upstream_adapter.py`
- Create: `runners/kronos/src/astraquant_kronos_runner/forecast.py`
- Create: `runners/kronos/tests/test_runner.py`
- Create: `runners/kronos/tests/fakes.py`

- [x] 先用 fake backend 测完整运行链路，不需要网络/GPU/权重；验证 row coverage、顺序、原子写入、缺权重、NaN、部分输出和 upstream import 失败均不发布半份 response。
- [ ] Adapter 只通过 `external/Kronos/model` 调用官方 `KronosTokenizer`、`Kronos`、`KronosPredictor`，不复制或修改上游实现。
- [ ] 默认 `Kronos-base`、最大 context 512、5-bar horizon；采样 seed 由全局 seed + fold/instrument/row identity 稳定派生，CPU/CUDA 的 device identity 写入 response。
- [x] 多路径输出聚合为 terminal-return 中位数、10/50/90 分位、上涨路径占比、路径波动；`expected_return` 只表示终点中位收益，不命名为 probability。
- [ ] 用固定小窗口和已准备的官方权重完成一次真实 smoke，记录 revision/weight/env/output digests；提交 `feat(kronos): 实现隔离零样本推理`。

## Task 4: 接入统一可执行评价

**Files:**

- Create: `tools/research/run_kronos_zero_shot.py`
- Create: `tests/research/test_run_kronos_zero_shot.py`
- Modify: `packages/quant/src/astraquant_quant/panel_research.py`

- [ ] `prepare` 消费 Task 4 的 exact `dataset_id@snapshot_id` 并生成 Kronos request；`evaluate` 校验 response identity 后调用同一 `run_panel_executable_expected_returns()`。
- [ ] 同一 eligibility mask 下输出 Kronos/DoubleEnsemble/Ridge 的 fold、instrument、liquidity、regime、费用、滑点、容量、成交集中度和最差回撤。
- [ ] 报告同时保存路径校准指标：方向命中、terminal return MAE、区间覆盖率和区间宽度；这些指标不能绕过 executable net-return gate。
- [ ] 训练/推理运行两次，input/fold/prediction/report digests 必须一致；随机采样如无法逐浮点复现，正式模式改用已证明可复现的 deterministic sampling policy，不能降低验收标准。
- [ ] 提交 `feat(research): 接入Kronos零样本公平评价`。

## Task 5: 真实 9 ETF zero-shot 验收与决策

**Files:**

- Create: `docs/verification/quant-core-v3/kronos-zero-shot.md`
- Modify: `docs/superpowers/plans/2026-08-11-quant-core-v3-progress.md`
- Modify: `docs/superpowers/specs/2026-08-12-kronos-foundation-model-integration-design.md`

- [ ] 在与 DoubleEnsemble 相同的 Eastmoney snapshots/folds/execution policy 上运行两次并封存全部 digests。
- [ ] 状态只能为 `INSUFFICIENT_EVIDENCE`、`NO_NET_EDGE` 或 `ZERO_SHOT_CANDIDATE`；必须同时披露净收益、回撤、稳定性、成交集中度、路径误差与不确定性校准。
- [ ] `ZERO_SHOT_CANDIDATE` 仍不进入 Shadow/Paper；先扩大历史和 regime。只有确认 A 股域偏差且 zero-shot 有可利用信息，才另写微调计划。
- [ ] 无论成败，Kronos runner 保持独立可关闭；不得让自有模型依赖其权重、环境或服务。
- [ ] 提交 `test(research): 验收Kronos零样本模型`。

## Task 6: 后续产品与组合交接（不在本批次实现）

- [ ] zero-shot 验收通过后，另写 K 线图“核预测”图层计划；默认关闭，明确区分真实 K 线与生成路径。
- [ ] 跨时期/证券稳定后，另写 Kronos forecast-to-factor 计划；使用版本化因子进入组合层，Kronos 永不直接下单。
- [ ] 若 zero-shot 不通过，保留研究入口和报告，不开发 UI、不强行微调、不阻塞 StockMixer/MASTER 主线。

## 验收命令骨架

```powershell
uv run pytest tests/data/test_kronos_export.py tests/research/test_run_kronos_zero_shot.py -q
uv run ruff check packages/data/src packages/quant/src tools/research tests/data tests/research
uv run mypy packages/data/src packages/quant/src tools/research tests/data tests/research
uv sync --project runners/kronos --frozen
uv run --project runners/kronos --frozen pytest runners/kronos/tests -q
uv run --project runners/kronos --frozen python -m astraquant_kronos_runner --help
```

真实权重 smoke 和 9 ETF 双运行必须使用本地显式 paths/revisions/digests；CI 只运行 fake backend 与 contract tests，不在 CI 自动下载大权重。

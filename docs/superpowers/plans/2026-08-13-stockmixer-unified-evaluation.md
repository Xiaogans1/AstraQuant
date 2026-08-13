# StockMixer Unified Execution Evaluation Plan

**Goal:** 将冻结的 StockMixer 三折 `EXPECTED_RETURN` 预测接入已验收的 A 股 ETF next-open 执行器，给出真实费用、滑点、容量和整数手约束后的唯一效果结论。

**Architecture:** 新工具只做身份校验、预测行映射和报告封装；行情重建、fold 本地化、委托容量与费用计算全部复用 `panel_research.run_panel_executable_expected_returns`。训练 artifact 与本次 outer-test 已冻结，执行结果不得回流修改训练配置或阈值。

**Execution status (2026-08-13):** Tasks 1–2 已完成。Run A/Run B 报告逐字节一致，StockMixer 扣费净收益 `-4.0930%`、`0/3` 正收益 folds，正式状态 `NO_NET_EDGE`。验收见 `docs/verification/quant-core-v3/stockmixer-unified-execution.md`。

### Task 1: Map sealed predictions into the shared evaluator

- [x] Add red-light tests for exact request/artifact digests, timestamp/instrument mapping, missing coverage and deterministic reports.
- [x] Implement `tools/research/evaluate_stockmixer_panel.py` without importing PyTorch or the isolated runner.
- [x] Run focused tests and relevant panel evaluator regressions (`10 passed`); run Ruff.
- [x] Commit and push the adapter (`408c152`).

### Task 2: Run the frozen 9-ETF executable evaluation

- [x] Evaluate Run A and Run B with `score >= 0.0005`, next-open, 5 bars, 0.025% commission, 2 bps slippage, 10% participation and 100-share lots.
- [x] Require byte-identical reports, compare with frozen Ridge/DoubleEnsemble results and assign `NO_NET_EDGE`.
- [x] Update verification/progress, run final checks, commit and push (`14` root regressions + `28` runner tests; Ruff clean).

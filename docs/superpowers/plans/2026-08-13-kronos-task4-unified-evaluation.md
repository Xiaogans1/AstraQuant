# Kronos Task 4 Unified Executable Evaluation Implementation Plan

> **Execution:** Use `superpowers:executing-plans` and `superpowers:test-driven-development` task-by-task.

**Goal:** Convert validated Kronos path summaries into `EXPECTED_RETURN` predictions and compare them with DoubleEnsemble and Ridge on exactly the same eligible rows, folds, fees, slippage, capacity, and next-open execution semantics.

**Program value:** The official model now runs; this phase determines whether its forecasts survive realistic A-share ETF execution costs. It prevents a visually impressive K-line forecast from bypassing the quant core's common trading gate.

## Task 1: Prepare one shared experiment

**Files:**

- Create: `tools/research/run_kronos_zero_shot.py`
- Create: `tests/research/test_run_kronos_zero_shot.py`

1. Red: reject `latest`, non-Eastmoney inputs, snapshot drift, unknown local weight digests, duplicate dataset specs, and output overwrite.
2. Build the existing panel and 3 walk-forward folds from exact `dataset_id@snapshot_id` inputs.
3. Export both a Kronos request and a DoubleEnsemble Qlib request from that same panel/fold object. Forecast timestamps come from the panel's pinned exchange-session bar timestamps; no future OHLCVA enters the Kronos window.
4. Seal a context containing both request digests, sources, fold policy, Kronos eligibility, and the existing executable policy (`next-open`, ETF, 5 bars, 0.00025 commission, 2 bps slippage, 10% participation, 100-share lots).
5. Verify deterministic bytes on two output roots.

## Task 2: Validate and adapt Kronos response

**Files:**

- Modify: `tools/research/run_kronos_zero_shot.py`
- Modify: `tests/research/test_run_kronos_zero_shot.py`

1. Red: reject response/request/upstream/model/tokenizer/environment identity mismatch, missing/duplicate/out-of-order rows, non-finite values, unordered quantiles, and `expected_return != terminal_return_p50`.
2. Convert only validated rows into `{fold_id,row_id,score=expected_return}`.
3. Derive one eligibility-restricted fold set and apply it identically to Kronos, DoubleEnsemble, and Ridge; no baseline may retain rows Kronos could not score.
4. Validate DoubleEnsemble response against its frozen Qlib request and filter by the same eligibility keys.

## Task 3: Produce one common executable report

**Files:**

- Modify: `tools/research/run_kronos_zero_shot.py`
- Modify: `packages/quant/src/astraquant_quant/panel_research.py` only if a shared helper is required
- Modify: `tests/research/test_run_kronos_zero_shot.py`

1. Run `run_panel_executable_expected_returns()` for `KRONOS_ZERO_SHOT`, `DOUBLE_ENSEMBLE`, and `RIDGE` with `minimum_score = 2 * commission + minimum_edge`.
2. Add terminal-return MAE, direction accuracy, p10/p90 interval coverage, and mean uncertainty width for Kronos. These diagnostics cannot override executable net return.
3. Report fold, instrument, liquidity, regime, fees, slippage, capacity, trade concentration, and drawdown under the same schema.
4. Run evaluation twice; response/report bytes and all input/fold/prediction/report digests must match.

## Verification

```powershell
uv run pytest tests/research/test_run_kronos_zero_shot.py tests/data/test_kronos_export.py -q
uv run ruff check tools/research/run_kronos_zero_shot.py tests/research/test_run_kronos_zero_shot.py packages/quant/src
uv run mypy tools/research/run_kronos_zero_shot.py tests/research/test_run_kronos_zero_shot.py packages/quant/src
```

**Exit gate:** One deterministic report compares all three models on identical eligible rows under the frozen executable policy. This closes plumbing only; Task 5 runs the real 9-ETF experiment and assigns the model status.

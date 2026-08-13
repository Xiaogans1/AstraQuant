# Kronos Task 3C Batched CUDA Inference Implementation Plan

> **Execution:** Use `superpowers:test-driven-development`. Do not modify `external/Kronos`.

**Goal:** Make the 9-ETF evaluation operationally feasible by batching equal-length windows through official `KronosPredictor.predict_batch()` while retaining every requested stochastic path.

**Program value:** The unified evaluator can require tens of thousands of windows. Per-window GPU dispatch is correct but wasteful; fixed batching lets the official model serve the research panel without weakening costs, folds, eligibility, or path uncertainty.

## Task 1: Add an optional batch backend contract

- Modify: `runners/kronos/src/astraquant_kronos_runner/runner.py`
- Modify: `runners/kronos/tests/test_runner.py`
- Modify: `runners/kronos/tests/fakes.py`

1. Red: a batch-capable backend receives all canonical rows, forecast timestamps, and stable row seeds once; a legacy backend still follows the existing per-row path.
2. Red: wrong batch count, wrong path count/length, non-finite output, or exception publishes no response.
3. Green: preserve request order and existing response bytes for equivalent paths.

## Task 2: Implement official fixed-size CUDA batches

- Modify: `runners/kronos/src/astraquant_kronos_runner/upstream_adapter.py`
- Modify: `runners/kronos/tests/test_upstream_adapter.py`

1. Red: official adapter calls `predict_batch`, not `predict`, for multiple rows; each call uses `sample_count=1` so no path is averaged away.
2. Use fixed chunks of 64 rows. For each chunk and sample index, derive one seed from the ordered row seeds plus sample index, seed Python/NumPy/Torch, and retain one path per row.
3. Validate equal context/horizon lengths, output row order, close columns, finite positive values, and exact path coverage.
4. A one-row request remains supported and deterministic.

## Task 3: Benchmark before the full panel

- Create: `docs/verification/quant-core-v3/kronos-batch-benchmark.md`

1. Run fixed real Eastmoney windows at batch sizes represented by 1, 16, and 64 rows on the RTX 4060 Ti.
2. Record source/model/tokenizer/device identities, elapsed time, peak GPU memory if available, and output repeatability.
3. Choose no adaptive runtime batch size in this phase: grouping is fixed by code and request order so two runs remain reproducible.

**Exit gate:** Batch tests pass and a 64-row real-data benchmark demonstrates material throughput improvement without changing path coverage or determinism. Then run the full Task 5 panel.

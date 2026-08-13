# Kronos Batched CUDA Inference Benchmark

**Status:** `PASSED_THROUGHPUT_GATE`  
**Date:** 2026-08-13  
**Purpose:** Throughput and repeatability only; no predictive-performance claim.

## Fixed inputs

- Eastmoney exact snapshot: `cn-equity-512800-sse-1m-none@b2f369056c22570a00ac10d090c7c6b8c637c4fc3a51560ff3563965d2f3c8d4`
- Upstream: `shiyu-coder/Kronos@67b630e67f6a18c9e9be918d9b4337c960db1e9a`
- Model/tokenizer revisions and weight digests: identical to `kronos-official-smoke.md`
- Context: 128 one-minute bars
- Horizon: 5 bars
- Retained paths per row: 3
- GPU: NVIDIA GeForce RTX 4060 Ti
- Runtime: Python 3.11.15, PyTorch 2.7.1+cu128, `cuda:0`

## Results

| Rows in one request | Total elapsed | Approx. rows/sec | Approx. seconds/row |
|---:|---:|---:|---:|
| 1 | 5.89 s | 0.17 | 5.89 |
| 16 | 6.32 s | 2.53 | 0.40 |
| 64, cold | 11.35 s | 5.64 | 0.18 |
| 64, warm repeat | 8.84 s | 7.24 | 0.14 |

The fixed 64-row batch improves warm per-row throughput by about 42x versus a one-row process. The result includes model loading and response serialization, so a long multi-batch process should amortize startup further.

## Repeatability and identity

| Evidence | Digest |
|---|---|
| Request file | `sha256:0ba1972af2c0d48b7e91b6f58270d35406553366f15306ad879a72d012ec820d` |
| Windows file | `sha256:5dfcf17ffcd06509237acece17ee4cef8496056c655e4e1cbdb2005629eceb1e` |
| Request content | `sha256:2aa83a45e9b33b614310cf0c20a7cc3cf5c956488718682cf68ab4693ef427c8` |
| Response content | `sha256:a149d9c0241e7982cea986c2c238ce64b2ed9dbd1bb9220cbb22e7c14b1876c6` |
| Response file, run 1 | `sha256:83b1b996e2dd1e4e9daa3d7e61650203c6fe20b8a912650754a153ecd61702b1` |
| Response file, run 2 | `sha256:83b1b996e2dd1e4e9daa3d7e61650203c6fe20b8a912650754a153ecd61702b1` |

Both 64-row runs emitted `device=cuda:0` and byte-identical responses.

## Semantics preserved

- Official `KronosPredictor.predict_batch()` receives fixed chunks of at most 64 rows.
- It is called once per retained sample path with `sample_count=1`; upstream averaging cannot erase path dispersion.
- Batch seeds are deterministically derived from ordered row seeds plus sample index.
- Runner response order remains request order; wrong row/path coverage and non-finite values fail closed.
- Legacy per-row backends remain supported for unit tests and diagnostics.

## Decision

The throughput gate is closed. Proceed to the full unified 9-ETF Task 5 run. Operational estimates based on this benchmark place the 40k-window inference in the roughly 1–2 hour range on this workstation, rather than tens of hours; the real run duration must be measured, not assumed.

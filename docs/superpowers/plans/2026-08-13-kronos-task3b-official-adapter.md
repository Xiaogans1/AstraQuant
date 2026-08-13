# Kronos Task 3B Official Adapter And Weight Smoke Implementation Plan

> **Execution:** Use `superpowers:executing-plans` and `superpowers:test-driven-development`. Do not modify `external/Kronos`.

**Goal:** Replace the injected test backend with a fail-closed adapter over the pinned official Kronos source and weights, then prove one real Eastmoney K-line window can complete CUDA inference.

**Program value:** This closes the gap between “our contract can run” and “the official 102.3M parameter model actually runs on AstraQuant data.” It is a functional smoke only; it cannot promote Kronos or make a performance claim.

## Task 1: Freeze adapter and CLI behavior

**Files:**

- Create: `runners/kronos/tests/test_upstream_adapter.py`
- Create: `runners/kronos/tests/test_cli.py`
- Create: `runners/kronos/src/astraquant_kronos_runner/upstream_adapter.py`
- Create: `runners/kronos/src/astraquant_kronos_runner/__main__.py`
- Modify: `runners/kronos/src/astraquant_kronos_runner/runner.py`

1. Red: require exact upstream source root, local weight files, device policy, per-row seed, six-column OHLCVA input, timezone-aware timestamps, and one retained close path per requested sample.
2. Red: reject CUDA-unavailable requests when CPU fallback is false; reject import/load/predict/OOM/non-finite failures without publishing a response.
3. Green: import the official classes only from `external/Kronos/model`, load with `from_pretrained(local_parent_directory)`, and never call Hugging Face during inference.
4. Green: seed Python/NumPy/Torch for each path, call the official predictor with `sample_count=1`, and return all terminal paths to AstraQuant aggregation.
5. Green: CLI accepts only explicit `--request`, `--output`, `--root`, and `--upstream-root`; the validated request remains the source of model, tokenizer, sampling, and device policy.
6. Verify:

```powershell
uv run --project runners/kronos pytest runners/kronos/tests/test_upstream_adapter.py runners/kronos/tests/test_cli.py -q
uv run --project runners/kronos ruff check runners/kronos/src runners/kronos/tests
```

## Task 2: Pin runtime dependencies and prepare exact weights

**Files:**

- Modify: `runners/kronos/pyproject.toml`
- Modify: `runners/kronos/uv.lock`
- Create: `tools/research/prepare_kronos_weights.py`
- Create: `tests/research/test_prepare_kronos_weights.py`

1. Red: the preparation tool rejects any unpinned revision and any repository outside the frozen model/tokenizer IDs.
2. Green: download exact revisions into `.astraquant/models/kronos/<artifact>/<revision>/`, verify the required config and `model.safetensors`, compute SHA-256, and atomically write an ignored local manifest.
3. Keep downloading separate from the runner; inference remains offline and read-only.
4. Pin the minimal official inference dependencies and regenerate the Python 3.11 lockfile.
5. Verify:

```powershell
uv run pytest tests/research/test_prepare_kronos_weights.py -q
uv sync --project runners/kronos --frozen
uv run --project runners/kronos pytest runners/kronos/tests -q
```

## Task 3: Run one real Eastmoney CUDA smoke

**Files:**

- Create: `tools/research/prepare_kronos_smoke.py`
- Create: `tests/research/test_prepare_kronos_smoke.py`
- Create: `docs/verification/quant-core-v3/kronos-official-smoke.md`
- Modify: `docs/superpowers/plans/2026-08-12-kronos-zero-shot-runner.md`

1. Select one exact Eastmoney snapshot already sealed by the repository, export one eligible context window and five future exchange-calendar timestamps, and label the artifact `SMOKE_ONLY`.
2. Run the official adapter twice with identical request and weights. Both response bytes and content digests must match; input/model/tokenizer/upstream/environment/device/output identities must be recorded.
3. Require CUDA for the acceptance run on this workstation. A CPU-only result may diagnose the environment but cannot close Task 3B.
4. Record failures and limitations honestly; do not report return, hit rate, or strategy quality from this window.
5. Run the full runner suite plus targeted repository tests, then commit and push.

```powershell
uv run --project runners/kronos --frozen python -m astraquant_kronos_runner --request <request.json> --output <response.json> --root <root> --upstream-root external/Kronos
uv run --project runners/kronos --frozen pytest runners/kronos/tests -q
uv run pytest tests/research/test_prepare_kronos_weights.py tests/research/test_prepare_kronos_smoke.py -q
```

**Exit gate:** Official pinned source and exact local weights complete the same real-data request twice on CUDA with byte-identical validated responses. Passing this gate starts Task 4 unified executable evaluation; it does not make Kronos a trading signal.

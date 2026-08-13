# Kronos Official CUDA Smoke Verification

**Status:** `PASSED_FUNCTIONAL_SMOKE`  
**Run class:** `SMOKE_ONLY`  
**Performance claim allowed:** `false`

## What this proves

The pinned official `Kronos-base` source, exact local model/tokenizer weights, AstraQuant request contract, a sealed Eastmoney minute-bar snapshot, and the Windows CUDA runner complete end-to-end inference on the repository workstation. Two independent processes produced byte-identical validated responses.

This smoke does **not** establish predictive edge, profitability, calibration, or promotion eligibility. Task 4/5 must evaluate the full 9-ETF panel under the common executable-cost protocol.

## Frozen identities

| Item | Identity |
|---|---|
| Upstream | `shiyu-coder/Kronos@67b630e67f6a18c9e9be918d9b4337c960db1e9a` |
| Model | `NeoQuasar/Kronos-base@2b554741eca47781b64468546e77fef3e85130e6` |
| Model weights | `sha256:abff193acab6db1a0368e9773e75799d11403b6d054ee6d5f0a11aeabc5f4b83` (409,264,008 bytes) |
| Tokenizer | `NeoQuasar/Kronos-Tokenizer-base@0e0117387f39004a9016484a186a908917e22426` |
| Tokenizer weights | `sha256:59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee` (15,842,368 bytes) |
| Eastmoney source | `cn-equity-512800-sse-1m-none@b2f369056c22570a00ac10d090c7c6b8c637c4fc3a51560ff3563965d2f3c8d4` |
| Request file | `sha256:0caabb2eca02fcf4e5f1c46629e6b482fd7a45daa307d7ce134257d750209002` |
| Windows file | `sha256:6b450c9dd8fd9c0b15e57e6e08e34330bb7abb3ca381d263aa0802e7909f7269` |
| Request content | `sha256:14a7139c992797cdfd7ccd8916f1f185d6bc1ac3a849174ed2c72a3763019351` |
| Response content | `sha256:1f462dbb782be6c60becda33904053c27337a442ac7b479c05ce88c4a7fdd7df` |
| Response file, run 1 | `sha256:030a0b44ee74e09483967caf891ec369a503edd6f7087e90ac191b2993c1863f` |
| Response file, run 2 | `sha256:030a0b44ee74e09483967caf891ec369a503edd6f7087e90ac191b2993c1863f` |

## Runtime

- Python: `3.11.15`
- PyTorch: `2.7.1+cu128`
- CUDA runtime: `12.8`
- GPU: `NVIDIA GeForce RTX 4060 Ti`, 8,188 MiB
- NVIDIA driver: `595.95`
- Context: 128 real one-minute bars
- Forecast horizon: 5 exchange-session timestamps
- Retained sample paths: 3
- Device policy: `CUDA`, `allow_cpu_fallback=false`

The response is finite, schema-valid, and reports `device=cuda:0`. The numerical forecast is intentionally omitted from this verification narrative because one window is not evidence of model quality.

## Verification evidence

```text
20 passed in 0.72s   # isolated runner tests
4 passed in 0.60s    # weight + real-snapshot smoke preparation tests
All checks passed!   # Ruff
Success: no issues found in 10 source files  # mypy
```

The official runner was executed twice with the same explicit request, root, upstream root, and local weight files. Both response SHA-256 digests were identical. No network fetch occurs in the inference process.

## Next gate

Proceed to Task 4: adapt the Kronos response into the same executable evaluator used by DoubleEnsemble and Ridge. Only Task 5 may decide `INSUFFICIENT_EVIDENCE`, `NO_NET_EDGE`, or `ZERO_SHOT_CANDIDATE` on the fixed 9-ETF panel.

# Kronos Task 1 Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 冻结 Kronos zero-shot 请求、响应、模型权重身份和稳定内容摘要，使后续窗口导出与真实推理不能读取漂移的 `latest` 权重或混用预测语义。

**Architecture:** `runners/kronos` 是独立 Python 3.11 project。`contracts.py` 只依赖标准库，先对 JSON object 做 fail-closed 校验，再生成 canonical SHA-256；真实 Torch/Kronos 依赖留到 Task 3。模型和 tokenizer revision 固定为 Hugging Face main 当前精确 commit，请求还必须携带本地 `model.safetensors` 的重算 digest。

**Tech Stack:** Python 3.11、dataclasses/Enum、JSON Schema Draft 2020-12、pytest、Ruff、uv。

---

## Task 1.1: 建立隔离 project 与失败契约测试

**Files:**

- Create: `runners/kronos/pyproject.toml`
- Create: `runners/kronos/.python-version`
- Create: `runners/kronos/tests/test_contracts.py`

- [x] 创建仅包含 `pytest` 开发依赖的 Python 3.11 project；Task 1 不安装 Torch 或下载模型。
- [x] 测试期望导入 `astraquant_kronos_runner.contracts`，首次运行必须因模块不存在而失败。
- [x] 测试有效 request 能返回稳定 `content_digest`，并逐项拒绝：非 exact snapshot、未知 upstream commit、空 revision、非 SHA-256 权重摘要、非正 context/horizon/sample count、非法 OHLCVA columns。
- [x] 测试 response 必须覆盖 request 的全部 `(fold_id,row_id)`，保持顺序，所有数值有限，并回传相同 request/upstream/model/tokenizer identity。
- [x] 运行 `uv sync --project runners/kronos` 后执行 `uv run --project runners/kronos pytest runners/kronos/tests/test_contracts.py -q`；按预期因 `contracts` 模块不存在失败。

## Task 1.2: 实现最小标准库契约

**Files:**

- Create: `runners/kronos/src/astraquant_kronos_runner/__init__.py`
- Create: `runners/kronos/src/astraquant_kronos_runner/contracts.py`

- [x] 定义 `KRONOS_REQUEST_SCHEMA = "astraquant.kronos-request/v1"`、`KRONOS_RESPONSE_SCHEMA = "astraquant.kronos-response/v1"` 和固定 upstream commit。
- [x] 实现 `canonical_digest(value) -> str`，使用排序键、紧凑 UTF-8 JSON 和 `sha256:` 前缀；拒绝 NaN/Infinity。
- [x] 实现 `validate_request(payload, *, root) -> dict`：校验严格字段集合、exact digests、model/tokenizer revision、本地相对路径、文件存在且 digest 匹配、OHLCVA columns、fold/row identity、device/sampling 范围及 supplied content digest。
- [x] 实现 `validate_response(payload, *, request) -> dict`：校验严格字段集合、identity 回传、逐行有限路径摘要、唯一且完整的 fold/row coverage、canonical order。
- [x] 再运行 Task 1.1 测试；全部通过。

## Task 1.3: 冻结机器可读 JSON Schema 与上游身份

**Files:**

- Create: `contracts/kronos-runner/v1/request.schema.json`
- Create: `contracts/kronos-runner/v1/response.schema.json`
- Modify: `runners/kronos/upstream-manifest.json`
- Test: `runners/kronos/tests/test_contracts.py`

- [x] Schema 使用 `additionalProperties: false`，digest 统一为 `^sha256:[0-9a-f]{64}$`，revision/upstream commit 为 40 位小写十六进制。
- [x] Manifest 固定 `Kronos-base` revision `2b554741eca47781b64468546e77fef3e85130e6` 与 tokenizer revision `0e0117387f39004a9016484a186a908917e22426`。
- [x] 测试加载两个 schema，并确认 valid fixture 通过、额外字段与缺字段失败；schema 与 Python validator 的字段集合一致。
- [x] 运行 `uv run --project runners/kronos pytest runners/kronos/tests -q`、根环境 Ruff 和 `git diff --check`。
- [x] 更新父计划 Task 1 checkbox 与当前进度，提交 `feat(kronos): 冻结零样本推理契约`。

## 完成后的程序能力

任何后续 Kronos 推理都必须回答并证明：用了哪份真实快照、哪一版官方源码、哪一版模型/tokenizer、哪两个本地权重文件、哪些 fold/rows、什么采样参数。任一文件或版本变化都会改变摘要或被拒绝，现有自有模型完全不依赖该 runner。

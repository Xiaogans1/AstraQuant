# StockMixer Stage B Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 固定官方 StockMixer，并建立可接收任意数量证券、正确处理停牌与缺失的不可变 panel 请求和动态共享模型核心。

**Architecture:** 官方仓库作为只读 gitlink 和差分语义标尺；AstraQuant 主环境只负责从 exact Eastmoney panel 导出 JSON + Parquet；独立 PyTorch runner 实现官方指标/因果时间混合与动态 masked stock-to-market bottleneck。首批不训练真实 challenger，完成后依据显存、耗时和真实覆盖另写训练微计划。

**Tech Stack:** Python 3.12、PyArrow/Parquet、Python 3.11 isolated runner、PyTorch 2.7 CUDA 12.8、pytest、git submodule。

---

## File map

- `.gitmodules` / `external/StockMixer`: 固定官方源码，不承载 AstraQuant 修改。
- `runners/stockmixer/upstream-manifest.json`: 保存 repository、commit、关键源码/论文 digest 和集成策略。
- `packages/data/src/astraquant_data/exports/stockmixer.py`: 生成动态 universe 请求，不 import PyTorch 或 quant 实现。
- `tests/data/test_stockmixer_export.py`: 验证时间、mask、排序、digest 和 fail-closed 边界。
- `runners/stockmixer/src/astraquant_stockmixer_runner/contracts.py`: 验证请求身份、Parquet schema 和完整覆盖。
- `runners/stockmixer/src/astraquant_stockmixer_runner/model.py`: 动态指标/时间/市场混合模型。
- `runners/stockmixer/tests/test_contracts.py`: runner 输入拒绝测试。
- `runners/stockmixer/tests/test_model.py`: 上游时间语义与动态 mask 不变量测试。

### Task 1: Freeze the official source and evidence manifest

**Files:**

- Modify: `.gitmodules`
- Create: `external/StockMixer` (gitlink)
- Create: `runners/stockmixer/upstream-manifest.json`
- Create: `runners/stockmixer/tests/test_upstream_manifest.py`

- [ ] **Step 1: Write the manifest test**

```python
def test_upstream_manifest_matches_pinned_checkout() -> None:
    root = Path(__file__).parents[3]
    manifest = json.loads((root / "runners/stockmixer/upstream-manifest.json").read_text())
    upstream = root / "external/StockMixer"
    assert manifest["commit"] == "cce13598afd3ff33ae317700a85ae08db0554652"
    assert _sha256(upstream / "src/model.py") == manifest["evidence"]["model_sha256"]
    assert _sha256(upstream / "paper+slide+poster/StockMixer.pdf") == manifest["evidence"]["paper_sha256"]
    assert manifest["integration_policy"]["sample_datasets_allowed"] is False
```

- [ ] **Step 2: Run the test and confirm the missing manifest red light**

Run: `uv run pytest runners/stockmixer/tests/test_upstream_manifest.py -q`

Expected: FAIL because `runners/stockmixer` and the manifest do not exist.

- [ ] **Step 3: Add and pin the official submodule**

Run:

```powershell
git submodule add https://github.com/SJTU-DMTai/StockMixer.git external/StockMixer
git -C external/StockMixer checkout cce13598afd3ff33ae317700a85ae08db0554652
```

Expected: `git -C external/StockMixer rev-parse HEAD` prints exactly `cce13598afd3ff33ae317700a85ae08db0554652`.

- [ ] **Step 4: Add the sealed manifest**

The manifest must contain these exact evidence values:

```json
{
  "contract": "astraquant.stockmixer-upstream/v1",
  "repository": "https://github.com/SJTU-DMTai/StockMixer.git",
  "branch": "master",
  "commit": "cce13598afd3ff33ae317700a85ae08db0554652",
  "source_root": "../../external/StockMixer",
  "evidence": {
    "model_sha256": "da731ce33b837df5e0542f411d24ed7f4da499ea2b806b1d19fc69034e6f3144",
    "train_sha256": "4d632a5ce3ece068edf382ef60aa1d5a37f7b5b68ee918ebae225554b46c2870",
    "paper_sha256": "0d23e239a825468601b1315f92b5887a013f7213482ac8d96021c9d737bc2c9c"
  },
  "integration_policy": {
    "upstream_source_read_only": true,
    "sample_datasets_allowed": false,
    "main_process_imports_torch": false,
    "dynamic_universe_required": true
  }
}
```

- [ ] **Step 5: Run the manifest test**

Run: `uv run pytest runners/stockmixer/tests/test_upstream_manifest.py -q`

Expected: `1 passed`.

- [ ] **Step 6: Commit the official-source lock**

```powershell
git add .gitmodules external/StockMixer runners/stockmixer/upstream-manifest.json runners/stockmixer/tests/test_upstream_manifest.py
git commit -m "build(stockmixer): 固定官方实现与论文证据"
```

### Task 2: Export a sealed dynamic-universe panel

**Files:**

- Create: `packages/data/src/astraquant_data/exports/stockmixer.py`
- Create: `tests/data/test_stockmixer_export.py`

- [ ] **Step 1: Write the repeatability and mask red-light test**

Build a two-instrument fixture where `BBB` is a member but has no bar at the second decision time. Assert:

```python
first = export_stockmixer_request(..., output_root=tmp_path / "first")
second = export_stockmixer_request(..., output_root=tmp_path / "second")
assert first.content_digest == second.content_digest
assert first.panel_path.read_bytes() == second.panel_path.read_bytes()

rows = pq.read_table(first.panel_path).to_pylist()
missing = next(
    row for row in rows
    if row["instrument_id"] == "BBB.SSE"
    and row["decision_time"] == SECOND_DECISION
    and row["sequence_index"] == LOOKBACK - 1
)
assert missing["presence_mask"] is True
assert missing["tradable_mask"] is False
assert missing["label_mask"] is False
assert missing["feature_mask"] is False
assert all(missing[name] == 0.0 for name in ("open", "high", "low", "close", "volume"))
```

Also assert canonical order is `(fold_id, decision_time, instrument_id, sequence_index)` and every nonzero feature has `event_time <= decision_time`.

- [ ] **Step 2: Run the export test and confirm import failure**

Run: `uv run pytest tests/data/test_stockmixer_export.py -q --basetemp=.astraquant/test-tmp/stockmixer-export-red`

Expected: FAIL with `ModuleNotFoundError: astraquant_data.exports.stockmixer`.

- [ ] **Step 3: Define the request types**

Implement these public types:

```python
STOCKMIXER_REQUEST_SCHEMA = "astraquant.stockmixer-request/v1"
STOCKMIXER_UPSTREAM_COMMIT = "cce13598afd3ff33ae317700a85ae08db0554652"
STOCKMIXER_INPUT_COLUMNS = ("open", "high", "low", "close", "volume")

@dataclass(frozen=True, slots=True)
class StockMixerSource:
    dataset_id: str
    instrument_id: str
    source_snapshot_id: str

@dataclass(frozen=True, slots=True)
class UniverseMembership:
    universe_id: str
    universe_snapshot_id: str
    members_by_time: Mapping[datetime, frozenset[str]]

@dataclass(frozen=True, slots=True)
class StockMixerExport:
    content_digest: str
    request_path: Path
    panel_path: Path
    sample_count: int
```

- [ ] **Step 4: Implement canonical materialization**

`export_stockmixer_request` must:

- reject an existing output root;
- require exact non-sentinel SHA-256 source and universe identities;
- require source instruments to equal the panel instruments;
- use fold test/train timestamps without splitting one timestamp across segments;
- materialize every declared universe member for every sample time;
- align lookback slots on the shared market timeline and emit `feature_mask=false` plus zeros for missing bars, never infer missingness from zero;
- reject any selected bar after `decision_time`;
- atomically write `panel.parquet` then `request.json`;
- hash source IDs, universe ID, folds, input columns, lookback, label name and panel file digest into `content_digest`.

The Parquet schema is fixed to:

```python
pa.schema([
    pa.field("fold_id", pa.string(), nullable=False),
    pa.field("segment", pa.string(), nullable=False),
    pa.field("sample_id", pa.int64(), nullable=False),
    pa.field("decision_time", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("instrument_id", pa.string(), nullable=False),
    pa.field("sequence_index", pa.int16(), nullable=False),
    pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("feature_mask", pa.bool_(), nullable=False),
    pa.field("presence_mask", pa.bool_(), nullable=False),
    pa.field("tradable_mask", pa.bool_(), nullable=False),
    pa.field("label_mask", pa.bool_(), nullable=False),
    pa.field("label", pa.float64(), nullable=False),
    pa.field("open", pa.float64(), nullable=False),
    pa.field("high", pa.float64(), nullable=False),
    pa.field("low", pa.float64(), nullable=False),
    pa.field("close", pa.float64(), nullable=False),
    pa.field("volume", pa.float64(), nullable=False),
])
```

- [ ] **Step 5: Add fail-closed tests**

Test exact rejection messages for:

- `source_snapshot_id="latest"`;
- universe omits a panel instrument;
- a timestamp is assigned to train and test in the same fold;
- a row contains a future bar;
- duplicate instrument IDs;
- output root already exists.

- [ ] **Step 6: Run exporter verification**

Run: `uv run pytest tests/data/test_stockmixer_export.py tests/data/test_kronos_export.py tests/quant/test_panel_research.py -q --basetemp=.astraquant/test-tmp/stockmixer-export-green`

Expected: all selected tests pass.

- [ ] **Step 7: Commit the dynamic panel**

```powershell
git add packages/data/src/astraquant_data/exports/stockmixer.py tests/data/test_stockmixer_export.py
git commit -m "feat(data): 导出StockMixer动态股票池面板"
```

### Task 3: Implement the isolated dynamic StockMixer core

**Files:**

- Create: `runners/stockmixer/pyproject.toml`
- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/__init__.py`
- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/contracts.py`
- Create: `runners/stockmixer/src/astraquant_stockmixer_runner/model.py`
- Create: `runners/stockmixer/tests/__init__.py`
- Create: `runners/stockmixer/tests/test_contracts.py`
- Create: `runners/stockmixer/tests/test_model.py`
- Create: `runners/stockmixer/uv.lock`

- [ ] **Step 1: Write dynamic-universe model red lights**

```python
def test_masked_instrument_cannot_change_valid_predictions() -> None:
    model = DynamicStockMixer(time_steps=4, channels=5, hidden_dim=8, market_dim=4)
    model.eval()
    valid = torch.randn(1, 2, 4, 5)
    feature_mask = torch.ones(1, 2, 4, dtype=torch.bool)
    base = model(valid, torch.tensor([[True, True]]), feature_mask)
    padded = torch.cat([valid, torch.full((1, 1, 4, 5), 1e9)], dim=1)
    padded_feature_mask = torch.cat(
        [feature_mask, torch.zeros(1, 1, 4, dtype=torch.bool)], dim=1
    )
    expanded = model(
        padded,
        torch.tensor([[True, True, False]]),
        padded_feature_mask,
    )
    torch.testing.assert_close(expanded[:, :2], base)
    assert expanded[0, 2].item() == 0.0

def test_permuting_instruments_only_permutes_predictions() -> None:
    permutation = torch.tensor([2, 0, 1])
    expected = model(features, mask, feature_mask)[:, permutation]
    actual = model(
        features[:, permutation],
        mask[:, permutation],
        feature_mask[:, permutation],
    )
    torch.testing.assert_close(actual, expected)
```

Add tests that `CausalTriangularMixer` never depends on a later timestep and that all-false masks raise `ValueError` instead of producing NaN.

- [ ] **Step 2: Write request contract red lights**

The contract tests must reject wrong schema, wrong upstream commit, non-Eastmoney provider, changed file digest, noncanonical rows, duplicate `(fold, sample, instrument, sequence)` identities, future event times and inconsistent mask/zero rows.

- [ ] **Step 3: Run runner tests and confirm missing modules**

Run: `uv run --project runners/stockmixer pytest -q`

Expected: FAIL because `astraquant_stockmixer_runner` is not implemented.

- [ ] **Step 4: Create the isolated environment**

Use Python `>=3.11,<3.12`, `torch>=2.7,<2.8`, `pyarrow>=18,<20`, `numpy>=2,<3`; use the explicit PyTorch CUDA 12.8 index on Windows/Linux, matching the working Kronos CUDA environment. Root workspace must not gain a Torch dependency.

- [ ] **Step 5: Implement strict request loading**

`load_request(request_path: Path) -> StockMixerRequest` must recompute the canonical request digest and Parquet SHA-256 before returning a typed request. It must validate the exact schema and canonical identity order before any tensor allocation.

- [ ] **Step 6: Implement causal indicator/time mixing**

Implement `IndicatorTimeMixer` with these shapes:

```python
def forward(self, features: Tensor) -> Tensor:
    # input [batch, stock, time, indicator]
    # output [batch, stock, hidden]
```

Indicator mixing is per time step. Time mixing uses a learned upper-triangular causal mask equivalent to the official `TriU`: output position `t` can read only `0..t`. Multi-scale branches use causal pooling and concatenate before the final projection.

- [ ] **Step 7: Implement the dynamic market bottleneck**

```python
class MaskedMarketMixer(nn.Module):
    def forward(self, stock_hidden: Tensor, presence_mask: Tensor) -> Tensor:
        weights = presence_mask.to(stock_hidden.dtype).unsqueeze(-1)
        market = (self.stock_to_market(stock_hidden) * weights).sum(dim=1)
        market = market / weights.sum(dim=1).clamp_min(1.0)
        broadcast = market.unsqueeze(1).expand(-1, stock_hidden.shape[1], -1)
        mixed = stock_hidden + self.market_to_stock(torch.cat([stock_hidden, broadcast], -1))
        return mixed * weights
```

`DynamicStockMixer.forward(features, presence_mask, feature_mask)` returns `[batch, stock]`; it validates finite inputs and shapes, excludes `feature_mask=false` slots from temporal normalization/mixing, rejects a batch row with no present security, and zeros masked outputs after every cross-stock operation.

- [ ] **Step 8: Run runner tests and lock dependencies**

Run:

```powershell
uv lock --project runners/stockmixer
uv sync --project runners/stockmixer --frozen
uv run --project runners/stockmixer pytest -q
```

Expected: all runner tests pass on CPU; if CUDA is available, add an optional parity assertion that CPU/CUDA output shapes and finite-value contracts match.

- [ ] **Step 9: Run cross-boundary verification**

Run:

```powershell
uv run pytest tests/data/test_stockmixer_export.py tests/quant/test_panel_research.py -q --basetemp=.astraquant/test-tmp/stockmixer-boundary
uv run --project runners/stockmixer pytest -q
uv run ruff check packages/data/src/astraquant_data/exports/stockmixer.py tests/data/test_stockmixer_export.py
```

Expected: all commands exit 0. The root environment still reports `import torch` unavailable unless another optional tool installed it independently.

- [ ] **Step 10: Commit the dynamic model core**

```powershell
git add runners/stockmixer
git commit -m "feat(stockmixer): 实现动态股票池共享模型核心"
```

## Batch exit and next planning gate

Run:

```powershell
git status --short
git log -3 --oneline
```

Exit conditions:

- official source and evidence are immutable;
- dynamic panel does not encode missingness as an unmasked number;
- model output is invariant to instrument ordering and masked padding;
- no real-data performance claim has been made yet.

At this point measure one real 9-ETF request's `(samples, stocks, lookback, features)`, GPU peak memory and one-epoch duration. Use those measurements to write the next micro plan for walk-forward training, inner validation, deterministic artifact saving and unified executable evaluation. Do not guess the epoch/trial budget before this measurement.

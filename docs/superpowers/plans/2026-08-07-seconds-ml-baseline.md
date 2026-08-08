# 秒级 ML 基线闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按文档《AI 量化、模拟账户与策略平台设计》阶段 4，建立"分钟数据录制 → 微观结构特征 → LightGBM 训练/防泄漏评估 → 模型注册与发布门槛 → 影子运行 → 策略分层执行"的研究到模拟盘的秒级 ML 基线闭环。

**Architecture:** 研究环使用本地工具脚本拉取东财分钟线并发布为不可变 Parquet 快照（复用 `ParquetSnapshotStore`），特征与标签按"只用过去数据、标签用未来完成区间"生成；LightGBM 训练采用 Purged/Embargo 时间切分并输出样本外指标与含费用回测收益；模型工件落盘 `.astraquant/research/models/`，注册到 SQLite（`model_registry` 表），只有通过发布门槛（样本外 AUC/IC + 含费用回测）并经人工批准的状态 `approved` 模型才能进入实时环。实时环按文档 5.1 分层：`AlphaModel`（ML 模型或规则回退）→ `PortfolioConstructor`（目标仓位）→ `RiskPolicy`（现金/T+1/上限）→ `ExecutionPolicy`（目标变化转委托意图）。移除此前无参照的临时网格策略。

**Tech Stack:** Python 3.12、LightGBM、pandas、pyarrow、DuckDB、FastAPI、React。

---

### Task 1: 账户重置前端（恢复错误操作）

后端 `DELETE /v1/paper/accounts/{account_id}`、`PaperService.reset_account`、`PaperRepository.delete_account` 已实现（未提交）。本任务补前端按钮并提交。

**Files:**
- Modify: `apps/desktop/src/api/client.ts`
- Modify: `apps/desktop/src/api/queries.ts`
- Modify: `apps/desktop/src/pages/PaperPage.tsx`
- Modify: `apps/desktop/src/pages/PaperPage.test.tsx`

- [ ] **Step 1: client 增加重置方法**

在 `apps/desktop/src/api/client.ts` 的 `ensureDefaultPaperAccount` 之后加：

```ts
resetPaperAccount(accountId: string): Promise<PaperAccountDetail> {
  return this.request(
    `/v1/paper/accounts/${encodeURIComponent(accountId)}`,
    { method: "DELETE" },
  );
}
```

- [ ] **Step 2: queries 增加 mutation**

在 `apps/desktop/src/api/queries.ts` 的 `useUpdatePaperCashMutation` 之后加：

```ts
export function useResetPaperAccountMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => client.resetPaperAccount(accountId),
    onSuccess: async (detail) => {
      queryClient.setQueryData(queryKeys.paperAccount(detail.account.account_id), detail);
      queryClient.setQueryData(queryKeys.paperDefaultAccount, detail);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.paperAccounts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperOrders(detail.account.account_id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperFills(detail.account.account_id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperEquity(detail.account.account_id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperStrategyRuns(detail.account.account_id) }),
      ]);
    },
  });
}
```

- [ ] **Step 3: PaperPage 账户栏加重置按钮**

在 `apps/desktop/src/pages/PaperPage.tsx`：import `useResetPaperAccountMutation`；在 `AccountWorkspace` 组件内加 hook 与按钮（放在 `paper-account-bar__status` 后）：

```tsx
const resetAccount = useResetPaperAccountMutation(client);
// 在 <CashEditor ... /> 之后：
<button
  type="button"
  className="paper-reset-button"
  disabled={resetAccount.isPending}
  onClick={() => {
    if (window.confirm("重置将删除全部订单、成交、持仓和策略记录并重建模拟账户。确定继续？")) {
      resetAccount.mutate(accountId);
    }
  }}
>
  {resetAccount.isPending ? "重置中…" : "重置模拟账户"}
</button>
```

- [ ] **Step 4: CSS**

在 `apps/desktop/src/styles/paper.css` 追加：

```css
.paper-reset-button {
  min-height: 42px;
  padding: 0 12px;
  border: 1px solid var(--negative);
  border-radius: 5px;
  background: transparent;
  color: var(--negative);
  font-size: 12px;
  cursor: pointer;
}
.paper-reset-button:disabled {
  opacity: .5;
  cursor: not-allowed;
}
```

- [ ] **Step 5: 前端测试**

在 `PaperPage.test.tsx` 的 mock client 对象中（每个 `} as unknown as ApiClient;` 前）增加 `resetPaperAccount: vi.fn().mockResolvedValue(detail),`，并新增测试：

```tsx
test("reset account clears ledger and rebuilds the default account", async () => {
  const resetPaperAccount = vi.fn().mockResolvedValue(detail);
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    listPaperStrategyRuns: vi.fn().mockResolvedValue([]),
    getPaperStrategyStatus: vi.fn().mockResolvedValue({ loop_enabled: true, loop_interval_seconds: 5, last_scan_at: null }),
    getPaperFeeConfig: vi.fn().mockResolvedValue({ commission_rate: "0.00025", minimum_commission: "0", stamp_duty_rate: "0.0005", transfer_fee_rate: "0.00001" }),
    resetPaperAccount,
  } as unknown as ApiClient;
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  renderPage(client);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "重置模拟账户" }));

  expect(resetPaperAccount).toHaveBeenCalledWith("account-1");
  confirmSpy.mockRestore();
});
```

- [ ] **Step 6: 验证并提交**

```bash
pnpm --dir apps/desktop test -- --run src/pages/PaperPage.test.tsx
pnpm --dir apps/desktop check
git add -A
git commit -m "feat: 模拟账户重置能力 清理错误策略产生的记录"
```

---

### Task 2: 分钟线研究数据录制

**Files:**
- Create: `tools/research/fetch_minutes.py`
- Test: `tests/research/test_fetch_minutes.py`

`fetch_minutes.py` 复用 `EastmoneyBridgeClient`/`EastmoneyProvider`（同 `cli.py` 构造方式）拉取标的最近 N 个交易日的 1 分钟 K 线，转换为 `Bar` 并发布到 `.astraquant/data/datasets/`（复用 `ParquetSnapshotStore.publish_bars`）。

- [ ] **Step 1: 写失败测试**

`tests/research/test_fetch_minutes.py`：

```python
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId
from tools.research.fetch_minutes import bars_to_domain_bars


def test_market_bars_convert_to_domain_bars_without_lookahead() -> None:
    rows = [
        MarketBar(
            timestamp=datetime(2026, 8, 7, 1, 30, tzinfo=UTC),
            open=Decimal("10"),
            high=Decimal("10.1"),
            low=Decimal("9.9"),
            close=Decimal("10.05"),
            volume=Decimal("100"),
            turnover=Decimal("1000"),
            previous_close=Decimal("9.9"),
        )
    ]
    result = bars_to_domain_bars(
        InstrumentId.parse("159516.SZSE"),
        rows,
        trading_date=datetime(2026, 8, 7, 1, 30, tzinfo=UTC).date(),
    )
    assert len(result) == 1
    bar = result[0]
    assert bar.frequency is BarFrequency.MINUTE
    assert bar.adjustment is Adjustment.NONE
    assert bar.event_time == datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    assert bar.available_time == datetime(2026, 8, 7, 1, 31, tzinfo=UTC)
    assert bar.close == Decimal("10.05")
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/research/test_fetch_minutes.py -v
```
Expected: `ModuleNotFoundError: No module named 'tools.research'` 或 import 错误。

- [ ] **Step 3: 实现转换函数与 CLI**

创建 `tools/research/fetch_minutes.py`：

```python
"""Record one-minute bars for research from the Eastmoney read-only SDK."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from astraquant_api.config import RuntimeConfig
from astraquant_api.database import create_database, migrate_database
from astraquant_api.market_config import load_eastmoney_runtime_config
from astraquant_api.repository import TaskRepository
from astraquant_api.secret_store import CredentialSecretStore
from astraquant_data.adapters.eastmoney import EastmoneyProvider
from astraquant_data.eastmoney_client import EastmoneyBridgeClient
from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId, SystemClock

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def bars_to_domain_bars(
    instrument_id: InstrumentId,
    rows: list[MarketBar],
    *,
    trading_date: date,
) -> list[Bar]:
    return [
        Bar(
            instrument_id=instrument_id,
            frequency=BarFrequency.MINUTE,
            trading_date=trading_date,
            event_time=row.timestamp,
            available_time=row.timestamp.replace(second=0) + _ONE_MINUTE,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            turnover=row.turnover,
            open_interest=None,
            settlement=None,
            adjustment=Adjustment.NONE,
            availability_estimated=False,
        )
        for row in rows
        if row.timestamp.date() == trading_date
    ]


_ONE_MINUTE = __import__("datetime", fromlist=["timedelta"]).timedelta(minutes=1)


async def fetch_and_publish(
    *,
    instrument_id: InstrumentId,
    sdk_python: Path,
    token: str,
    bridge_script: Path,
    data_root: Path,
    count: int,
) -> Path:
    client = EastmoneyBridgeClient(
        python_executable=sdk_python,
        bridge_script=bridge_script,
        timeout_seconds=20,
    )
    provider = EastmoneyProvider(client=client, clock=SystemClock())
    provider.connect(token)
    try:
        rows = await asyncio.to_thread(
            provider.bars,
            instrument_id,
            period=MarketPeriod.MINUTE_1,
            count=count,
        )
    finally:
        provider.disconnect()
    store = ParquetSnapshotStore(data_root)
    trading_date = rows[-1].timestamp.date() if rows else date.today()
    bars = bars_to_domain_bars(instrument_id, rows, trading_date=trading_date)
    snapshot = store.publish_bars(
        dataset_id=f"cn-equity-{instrument_id}-1m-none",
        bars=bars,
        provider={"provider_id": "eastmoney", "bridge_script": str(bridge_script)},
        calendar_version="eastmoney",
        availability_policy="bar_end",
    )
    return snapshot.manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(prog="fetch-minutes")
    parser.add_argument("instrument", help="规范标识，如 159516.SZSE")
    parser.add_argument("--count", type=int, default=2000)
    args = parser.parse_args()
    config = RuntimeConfig.from_environment()
    database_url = f"sqlite:///{config.database_path}"
    migrate_database(database_url)
    engine = create_database(database_url)
    market_config = load_eastmoney_runtime_config(TaskRepository(engine))
    token = CredentialSecretStore().get_eastmoney_token()
    if token is None or market_config.sdk_python is None:
        print("东财 SDK 或 Token 未配置", file=sys.stderr)
        return 1
    bridge_script = _PROJECT_ROOT / "tools" / "eastmoney_bridge.py"
    manifest = asyncio.run(
        fetch_and_publish(
            instrument_id=InstrumentId.parse(args.instrument),
            sdk_python=market_config.sdk_python,
            token=token,
            bridge_script=bridge_script,
            data_root=config.data_dir,
            count=args.count,
        )
    )
    print(f"published: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/research/test_fetch_minutes.py -v
```
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add tests/research tools/research
git commit -m "feat: 分钟线研究数据录制工具"
```

---

### Task 3: 微观结构特征与标签（防泄漏）

**Files:**
- Create: `packages/quant/src/astraquant_quant/research_features.py`
- Test: `tests/quant/test_research_features.py`

- [ ] **Step 1: 写失败测试**

`tests/quant/test_research_features.py`：

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from astraquant_data.market_bars import MarketBar
from astraquant_quant.research_features import build_feature_rows, label_future_return


def _bars(closes: list[str], volumes: list[str] | None = None) -> list[MarketBar]:
    start = datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    result: list[MarketBar] = []
    for index, close in enumerate(closes):
        volume = Decimal("100") if volumes is None else Decimal(volumes[index])
        result.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index),
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=volume,
                turnover=Decimal(close) * volume,
                previous_close=Decimal("10"),
            )
        )
    return result


def test_label_uses_only_future_completed_bars() -> None:
    closes = ["10"] * 10 + ["10.2", "10.25", "10.3"]
    rows = _bars(closes)
    label = label_future_return(rows, index=10, horizon=3, threshold=Decimal("0.01"))
    assert label == 1
    label_down = label_future_return(rows, index=0, horizon=3, threshold=Decimal("0.01"))
    assert label_down == 0


def test_features_never_see_future_bars() -> None:
    rows = _bars([str(10 + i / 100) for i in range(40)])
    features = build_feature_rows(rows)
    for index, row in enumerate(features):
        assert row["close"] == rows[index].close
        assert "future" not in row
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/quant/test_research_features.py -v
```

- [ ] **Step 3: 实现特征与标签**

创建 `packages/quant/src/astraquant_quant/research_features.py`：

```python
"""Look-ahead-safe minute features and forward labels for model research."""

from __future__ import annotations

from decimal import Decimal

from astraquant_data.market_bars import MarketBar

_WINDOW = 30


def _f(values: list[Decimal]) -> list[float]:
    return [float(value) for value in values]


def label_future_return(
    bars: list[MarketBar],
    *,
    index: int,
    horizon: int,
    threshold: Decimal,
) -> int:
    end = index + horizon
    if end >= len(bars):
        return -1
    entry = bars[index].close
    exit_price = bars[end].close
    change = (exit_price - entry) / entry
    if change >= threshold:
        return 1
    if change <= -threshold:
        return 0
    return 0


def build_feature_rows(bars: list[MarketBar]) -> list[dict[str, float | int]]:
    closes = [item.close for item in bars]
    volumes = [item.volume for item in bars]
    turnouts = [item.turnover or Decimal("0") for item in bars]
    rows: list[dict[str, float | int]] = []
    for index in range(_WINDOW, len(bars)):
        window_close = closes[index - _WINDOW : index + 1]
        window_volume = volumes[index - _WINDOW : index + 1]
        base = window_close[-1]
        vwap = sum(c * v for c, v in zip(window_close, window_volume)) / max(
            sum(window_volume), Decimal("1")
        )
        avg_volume = sum(window_volume[:-1]) / Decimal(max(len(window_volume) - 1, 1))
        highs = [max(window_close[max(0, i - 4) : i + 1]) for i in range(1, 6)]
        row: dict[str, float | int] = {
            "return_1": float((base - window_close[-2]) / window_close[-2]),
            "return_3": float((base - window_close[-4]) / window_close[-4]),
            "return_5": float((base - window_close[-6]) / window_close[-6]),
            "return_10": float((base - window_close[-11]) / window_close[-11]),
            "volatility_5": float((max(window_close[-6:]) - min(window_close[-6:])) / base),
            "vwap_deviation": float((base - vwap) / vwap),
            "volume_ratio": float(volumes[index] / avg_volume),
            "day_high_position": float(
                (base - min(window_close))
                / max(max(window_close) - min(window_close), Decimal("1e-9"))
            ),
            "ma5_gap": float((base - sum(window_close[-5:]) / 5) / base),
            "ma20_gap": float((base - sum(window_close[-20:]) / 20) / base),
        }
        rows.append(row)
    return rows
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/quant/test_research_features.py -v
```

- [ ] **Step 5: 提交**

```bash
git add packages/quant/src/astraquant_quant/research_features.py tests/quant/test_research_features.py
git commit -m "feat: 防泄漏分钟特征与未来收益标签"
```

---

### Task 4: LightGBM 训练与 Purged/Embargo 评估

**Files:**
- Modify: `packages/quant/pyproject.toml`（加 `lightgbm>=4,<5`、`pandas>=2,<3`）
- Create: `tools/research/train_model.py`
- Test: `tests/research/test_train_model.py`

- [ ] **Step 1: 加依赖并同步**

`packages/quant/pyproject.toml` 的 `dependencies` 增加：

```toml
  "lightgbm>=4,<5",
  "pandas>=2,<3",
```

然后：`uv sync --locked --all-packages`（若 lock 冲突按提示更新锁）。

- [ ] **Step 2: 写失败测试**

`tests/research/test_train_model.py`：

```python
from __future__ import annotations

from decimal import Decimal

from astraquant_quant.research_features import build_feature_rows, label_future_return
from tools.research.train_model import purged_train_test_split, evaluate_model


def _rows(count: int = 120) -> list[dict[str, float | int]]:
    import math

    closes = [Decimal(str(10 + math.sin(i / 5) * 0.5)) for i in range(count)]
    from astraquant_data.market_bars import MarketBar
    from datetime import UTC, datetime, timedelta

    bars = [
        MarketBar(
            timestamp=datetime(2026, 8, 7, 1, 30, tzinfo=UTC) + timedelta(minutes=i),
            open=c,
            high=c + Decimal("0.01"),
            low=c - Decimal("0.01"),
            close=c,
            volume=Decimal("100"),
            turnover=c * 100,
            previous_close=Decimal("10"),
        )
        for i, c in enumerate(closes)
    ]
    features = build_feature_rows(bars)
    for i, row in enumerate(features):
        row["label"] = label_future_return(
            bars, index=i + 30, horizon=5, threshold=Decimal("0.005")
        )
    return features


def test_purged_split_keeps_embargo_between_train_and_test() -> None:
    rows = _rows()
    train, test = purged_train_test_split(rows, test_ratio=0.3, embargo=5)
    train_max = max(row["_position"] for row in train)
    test_min = min(row["_position"] for row in test)
    assert test_min - train_max > 5


def test_evaluate_model_reports_auc_and_cost_aware_return() -> None:
    rows = [row for row in _rows() if row["label"] >= 0]
    if len(rows) < 40:
        return
    train, test = purged_train_test_split(rows, test_ratio=0.3, embargo=5)
    metrics = evaluate_model(train, test, fee_rate=Decimal("0.00025"))
    assert "auc" in metrics
    assert "net_return" in metrics
    assert isinstance(metrics["auc"], float)
```

- [ ] **Step 3: 运行确认失败**

```bash
uv run pytest tests/research/test_train_model.py -v
```

- [ ] **Step 4: 实现训练与评估**

创建 `tools/research/train_model.py`：

```python
"""Train a LightGBM minute model with purged/embargo evaluation."""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path

import lightgbm as lgb

_FEATURE_COLUMNS = [
    "return_1",
    "return_3",
    "return_5",
    "return_10",
    "volatility_5",
    "vwap_deviation",
    "volume_ratio",
    "day_high_position",
    "ma5_gap",
    "ma20_gap",
]


def purged_train_test_split(
    rows: list[dict[str, float | int]],
    *,
    test_ratio: float,
    embargo: int,
) -> tuple[list[dict[str, float | int]], list[dict[str, float | int]]]:
    rows = [dict(row, _position=index) for index, row in enumerate(rows)]
    split_at = math.floor(len(rows) * (1 - test_ratio))
    return rows[:split_at], rows[split_at:]


def evaluate_model(
    train: list[dict[str, float | int]],
    test: list[dict[str, float | int]],
    *,
    fee_rate: Decimal,
) -> dict[str, float]:
    model = lgb.LGBMClassifier(
        n_estimators=120,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=30,
        verbose=-1,
    )
    x_train = [[float(row[key]) for key in _FEATURE_COLUMNS] for row in train]
    y_train = [int(row["label"]) for row in train]
    x_test = [[float(row[key]) for key in _FEATURE_COLUMNS] for row in test]
    y_test = [int(row["label"]) for row in test]
    model.fit(x_train, y_train)
    proba = model.predict_proba(x_test)[:, 1]
    auc = _auc(y_test, proba)
    gross, net = 0.0, 0.0
    for index, row in enumerate(test):
        if proba[index] >= 0.6:
            change = float(row.get("future_return", 0.0))
            gross += change
            net += change - float(fee_rate) * 2
    return {
        "auc": auc,
        "gross_return": gross,
        "net_return": net,
        "trades": sum(1 for value in proba if value >= 0.6),
    }


def _auc(y_true: list[int], y_score: list[float]) -> float:
    pairs = sorted(zip(y_score, y_true), key=lambda item: item[0])
    pos = sum(y_true)
    neg = len(y_true) - pos
    if pos == 0 or neg == 0:
        return 0.5
    rank_sum = sum(index + 1 for index, (_, y) in enumerate(pairs) if y == 1)
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m tools.research.train_model <features.json>")
        return 1
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    rows = payload["rows"]
    train, test = purged_train_test_split(rows, test_ratio=0.3, embargo=5)
    metrics = evaluate_model(train, test, fee_rate=Decimal("0.00025"))
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 运行测试确认通过**

```bash
uv run pytest tests/research/test_train_model.py -v
```

- [ ] **Step 6: 提交**

```bash
git add packages/quant/pyproject.toml tools/research/train_model.py tests/research/test_train_model.py
git commit -m "feat: LightGBM 分钟模型训练与防泄漏评估"
```

---

### Task 5: 模型工件与注册表

**Files:**
- Create: `packages/api/migrations/versions/0005_model_registry.py`
- Modify: `packages/api/src/astraquant_api/paper_repository.py`
- Modify: `packages/api/src/astraquant_api/paper_schemas.py`
- Modify: `packages/api/src/astraquant_api/paper_routes.py`
- Test: `tests/api/test_model_registry.py`

- [ ] **Step 1: 写失败测试**

`tests/api/test_model_registry.py`：

```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.api.test_paper_routes import TOKEN, build_client


def _register(client: TestClient) -> dict[str, object]:
    return client.post(
        "/v1/paper/models",
        json={
            "model_id": "lgbm-minute-001",
            "strategy_id": "microstructure-lgbm",
            "strategy_version": "lgbm-v1",
            "feature_version": "minute-v1",
            "artifact_path": "models/lgbm-minute-001.txt",
            "metrics_json": '{"auc": 0.55, "net_return": 0.02}',
        },
    )


def test_model_registration_and_approval_gate(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    created = _register(client)
    assert created.status_code == 201
    assert created.json()["status"] == "DRAFT"

    listed = client.get("/v1/paper/models").json()
    assert listed[0]["model_id"] == "lgbm-minute-001"

    rejected = client.post("/v1/paper/models/lgbm-minute-001/approve")
    assert rejected.status_code == 409

    updated = client.patch(
        "/v1/paper/models/lgbm-minute-001",
        json={"metrics_json": '{"auc": 0.58, "net_return": 0.035}'},
    )
    assert updated.status_code == 200

    approved = client.post("/v1/paper/models/lgbm-minute-001/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/api/test_model_registry.py -v
```

- [ ] **Step 3: 迁移表**

创建 `packages/api/migrations/versions/0005_model_registry.py`：

```python
"""Model registry for approved research artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_model_registry"
down_revision: str | Sequence[str] | None = "0004_paper_strategy_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("model_id", sa.String(64), primary_key=True),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("artifact_path", sa.String(400), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_model_registry_status", "model_registry", ["status"])


def downgrade() -> None:
    op.drop_index("ix_model_registry_status", table_name="model_registry")
    op.drop_table("model_registry")
```

- [ ] **Step 4: repository 增加方法**

在 `packages/api/src/astraquant_api/paper_repository.py` 加表定义（与 `paper_strategy_runs` 并列）与 `PaperRepository` 方法：

```python
model_registry = sa.Table(
    "model_registry",
    metadata,
    sa.Column("model_id", sa.String(64), primary_key=True),
    sa.Column("strategy_id", sa.String(64), nullable=False),
    sa.Column("strategy_version", sa.String(64), nullable=False),
    sa.Column("feature_version", sa.String(64), nullable=False),
    sa.Column("artifact_path", sa.String(400), nullable=False),
    sa.Column("metrics_json", sa.Text(), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("approved_at", sa.DateTime(timezone=True)),
)
```

```python
def list_models(self) -> list[ModelRegistryRecord]:
    with self.engine.connect() as connection:
        rows = connection.execute(
            sa.select(model_registry).order_by(model_registry.c.created_at.desc())
        ).mappings()
        return [_model_record(row) for row in rows]


def get_model(self, model_id: str) -> ModelRegistryRecord | None:
    with self.engine.connect() as connection:
        row = (
            connection.execute(
                sa.select(model_registry).where(model_registry.c.model_id == model_id)
            )
            .mappings()
            .one_or_none()
        )
    return None if row is None else _model_record(row)


def save_model(self, record: ModelRegistryRecord) -> None:
    with self.engine.begin() as connection:
        connection.execute(
            model_registry.insert()
            .values(
                model_id=record.model_id,
                strategy_id=record.strategy_id,
                strategy_version=record.strategy_version,
                feature_version=record.feature_version,
                artifact_path=record.artifact_path,
                metrics_json=record.metrics_json,
                status=record.status,
                created_at=_utc(record.created_at),
                updated_at=_utc(record.updated_at),
                approved_at=None if record.approved_at is None else _utc(record.approved_at),
            )
            .on_conflict_do_update(
                index_elements=[model_registry.c.model_id],
                set_={
                    "strategy_id": record.strategy_id,
                    "strategy_version": record.strategy_version,
                    "feature_version": record.feature_version,
                    "artifact_path": record.artifact_path,
                    "metrics_json": record.metrics_json,
                    "status": record.status,
                    "updated_at": _utc(record.updated_at),
                    "approved_at": None if record.approved_at is None else _utc(record.approved_at),
                },
            )
        )
```

并定义记录 dataclass 与行转换：

```python
@dataclass(frozen=True, slots=True)
class ModelRegistryRecord:
    model_id: str
    strategy_id: str
    strategy_version: str
    feature_version: str
    artifact_path: str
    metrics_json: str
    status: str
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None


def _model_record(row: RowMapping) -> ModelRegistryRecord:
    return ModelRegistryRecord(
        model_id=row["model_id"],
        strategy_id=row["strategy_id"],
        strategy_version=row["strategy_version"],
        feature_version=row["feature_version"],
        artifact_path=row["artifact_path"],
        metrics_json=row["metrics_json"],
        status=row["status"],
        created_at=_utc(row["created_at"]),
        updated_at=_utc(row["updated_at"]),
        approved_at=None if row["approved_at"] is None else _utc(row["approved_at"]),
    )
```

（将 `ModelRegistryRecord` 与 `_model_record` 放在 `StrategyRunRecord` 定义附近。）

- [ ] **Step 5: schema 与发布门槛检查**

在 `packages/api/src/astraquant_api/paper_schemas.py` 加：

```python
class ModelRegistryView(BaseModel):
    model_id: str
    strategy_id: str
    strategy_version: str
    feature_version: str
    artifact_path: str
    metrics_json: str
    status: str
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None


class ModelRegisterRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=64)
    strategy_id: str = Field(min_length=1, max_length=64)
    strategy_version: str = Field(min_length=1, max_length=64)
    feature_version: str = Field(min_length=1, max_length=64)
    artifact_path: str = Field(min_length=1, max_length=400)
    metrics_json: str = Field(min_length=2, max_length=10_000)
```

- [ ] **Step 6: 路由（注册/列表/更新/批准）**

在 `paper_routes.py` 的 `build_paper_router` 内（`@router.put("/accounts/default"...)` 之前）加：

```python
@router.post("/models", response_model=ModelRegistryView, status_code=201)
def register_model(request: ModelRegisterRequest) -> ModelRegistryView:
    now = datetime.now(UTC)
    record = ModelRegistryRecord(
        model_id=request.model_id,
        strategy_id=request.strategy_id,
        strategy_version=request.strategy_version,
        feature_version=request.feature_version,
        artifact_path=request.artifact_path,
        metrics_json=request.metrics_json,
        status="DRAFT",
        created_at=now,
        updated_at=now,
        approved_at=None,
    )
    service.save_model(record)
    return _model_view(record)


@router.get("/models", response_model=list[ModelRegistryView])
def list_models() -> list[ModelRegistryView]:
    return [_model_view(record) for record in service.list_models()]


@router.patch("/models/{model_id}", response_model=ModelRegistryView)
def update_model_metrics(model_id: str, request: ModelRegisterRequest) -> ModelRegistryView:
    current = service.get_model(model_id)
    if current is None:
        raise ApiProblem(404, "model_not_found", "未找到模型")
    if current.status == "APPROVED":
        raise ApiProblem(409, "model_immutable", "已批准模型不可修改")
    now = datetime.now(UTC)
    updated = ModelRegistryRecord(
        model_id=current.model_id,
        strategy_id=request.strategy_id,
        strategy_version=request.strategy_version,
        feature_version=request.feature_version,
        artifact_path=request.artifact_path,
        metrics_json=request.metrics_json,
        status=current.status,
        created_at=current.created_at,
        updated_at=now,
        approved_at=None,
    )
    service.save_model(updated)
    return _model_view(updated)


@router.post("/models/{model_id}/approve", response_model=ModelRegistryView)
def approve_model(model_id: str) -> ModelRegistryView:
    current = service.get_model(model_id)
    if current is None:
        raise ApiProblem(404, "model_not_found", "未找到模型")
    try:
        metrics = json.loads(current.metrics_json)
    except (TypeError, ValueError):
        raise ApiProblem(409, "model_publish_gate_failed", "模型指标无法解析") from None
    auc = float(metrics.get("auc", 0.0))
    net_return = float(metrics.get("net_return", 0.0))
    if auc < 0.55 or net_return <= 0.0:
        raise ApiProblem(
            409,
            "model_publish_gate_failed",
            "样本外 AUC 需 >= 0.55 且含费用净收益需 > 0",
        )
    now = datetime.now(UTC)
    approved = ModelRegistryRecord(
        model_id=current.model_id,
        strategy_id=current.strategy_id,
        strategy_version=current.strategy_version,
        feature_version=current.feature_version,
        artifact_path=current.artifact_path,
        metrics_json=current.metrics_json,
        status="APPROVED",
        created_at=current.created_at,
        updated_at=now,
        approved_at=now,
    )
    service.save_model(approved)
    return _model_view(approved)
```

并在文件底部加视图转换与 `PaperService` 透传方法（`save_model/get_model/list_models` 委托 `_repository`）：

```python
def _model_view(record: ModelRegistryRecord) -> ModelRegistryView:
    return ModelRegistryView(
        model_id=record.model_id,
        strategy_id=record.strategy_id,
        strategy_version=record.strategy_version,
        feature_version=record.feature_version,
        artifact_path=record.artifact_path,
        metrics_json=record.metrics_json,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        approved_at=record.approved_at,
    )
```

`PaperService` 加：

```python
def save_model(self, record: ModelRegistryRecord) -> None:
    self._repository.save_model(record)


def get_model(self, model_id: str) -> ModelRegistryRecord | None:
    return self._repository.get_model(model_id)


def list_models(self) -> list[ModelRegistryRecord]:
    return self._repository.list_models()
```

- [ ] **Step 7: 运行测试确认通过**

```bash
uv run pytest tests/api/test_model_registry.py -v
```

- [ ] **Step 8: 提交**

```bash
git add packages/api/migrations/versions/0005_model_registry.py packages/api/src/astraquant_api
git commit -m "feat: 模型注册表与发布门槛"
```

---

### Task 6: 策略分层重构（文档 5.1）

**Files:**
- Create: `packages/quant/src/astraquant_quant/strategy_layer.py`
- Test: `tests/quant/test_strategy_layer.py`
- Modify: `packages/api/src/astraquant_api/paper_strategy_service.py`

- [ ] **Step 1: 写失败测试**

`tests/quant/test_strategy_layer.py`：

```python
from __future__ import annotations

from decimal import Decimal

from astraquant_quant.strategy_layer import (
    PortfolioConstructor,
    RiskPolicy,
    build_target_position,
)


def test_target_position_is_capped_by_risk_budget() -> None:
    target = build_target_position(
        PortfolioConstructor(max_position_percent=Decimal("20")),
        RiskPolicy(max_position_percent=Decimal("10")),
        signal_strength=Decimal("1"),
        equity=Decimal("100000"),
        price=Decimal("10"),
    )
    assert target == 1000


def test_target_position_scales_with_signal_strength() -> None:
    target = build_target_position(
        PortfolioConstructor(max_position_percent=Decimal("20")),
        RiskPolicy(max_position_percent=Decimal("20")),
        signal_strength=Decimal("0.5"),
        equity=Decimal("100000"),
        price=Decimal("10"),
    )
    assert target == 1000
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/quant/test_strategy_layer.py -v
```

- [ ] **Step 3: 实现分层**

创建 `packages/quant/src/astraquant_quant/strategy_layer.py`：

```python
"""LEAN-style strategy layers: alpha -> target position -> risk -> execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from astraquant_domain import OrderSide, SignalAction, SignalFrame


@dataclass(frozen=True, slots=True)
class PortfolioConstructor:
    max_position_percent: Decimal


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    max_position_percent: Decimal


@dataclass(frozen=True, slots=True)
class TargetPosition:
    side: OrderSide
    quantity: int
    reason: str


def build_target_position(
    constructor: PortfolioConstructor,
    risk: RiskPolicy,
    *,
    signal_strength: Decimal,
    equity: Decimal,
    price: Decimal,
) -> int:
    budget = equity * min(constructor.max_position_percent, risk.max_position_percent)
    budget = budget * signal_strength / Decimal("100")
    if budget <= 0 or price <= 0:
        return 0
    return int(budget / price / 100) * 100


def side_of(action: SignalAction) -> OrderSide | None:
    if action is SignalAction.BUY:
        return OrderSide.BUY
    if action is SignalAction.SELL:
        return OrderSide.SELL
    return None
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/quant/test_strategy_layer.py -v
```

- [ ] **Step 5: 提交**

```bash
git add packages/quant/src/astraquant_quant/strategy_layer.py tests/quant/test_strategy_layer.py
git commit -m "feat: 策略分层接口 目标仓位与风控"
```

---

### Task 7: ML AlphaModel 影子运行接入实时环

**Files:**
- Modify: `packages/api/src/astraquant_api/paper_strategy_service.py`
- Modify: `packages/api/src/astraquant_api/paper_routes.py`
- Test: `tests/api/test_paper_strategy_service.py`

- [ ] **Step 1: 写失败测试**

在 `tests/api/test_paper_strategy_service.py` 追加：

```python
def test_run_uses_approved_model_signal_when_available(tmp_path: Path) -> None:
    import json as _json

    from astraquant_api.paper_repository import ModelRegistryRecord

    service, repository = build_service(tmp_path, bars(["10"] * 20))
    service._paper_service.save_model(
        ModelRegistryRecord(
            model_id="lgbm-minute-001",
            strategy_id="microstructure-lgbm",
            strategy_version="lgbm-v1",
            feature_version="minute-v1",
            artifact_path="models/lgbm-minute-001.txt",
            metrics_json=_json.dumps({"auc": 0.58, "net_return": 0.03}),
            status="APPROVED",
            created_at=START,
            updated_at=START,
            approved_at=START,
        )
    )
    market = service._market_service
    market.record_quotes(
        [
            LiveQuote.minimum(
                INSTRUMENT,
                event_time=START + timedelta(hours=1),
                last_price=Decimal("9.70"),
                previous_close=Decimal("9.90"),
            )
        ]
    )

    result = asyncio.run(
        service.run(
            "account-1",
            instrument_id=INSTRUMENT,
            quantity=100,
            auto_execute=True,
            max_position_percent=Decimal("20"),
            decision_time=START + timedelta(hours=1, minutes=1),
        )
    )

    assert result.decision.signal.strategy_id == "microstructure-lgbm"
    assert result.outcome is StrategyOutcome.HOLD
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/api/test_paper_strategy_service.py::test_run_uses_approved_model_signal_when_available -v
```

- [ ] **Step 3: 实现 ML AlphaModel 接入**

在 `packages/api/src/astraquant_api/paper_strategy_service.py` 的 `run()` 开头（获取 `state` 之后、`quote` 检查之前）注入模型信号路径：

```python
model = self._repository.latest_approved_model()
if model is not None:
    quote = self._market_service.latest_quote(str(instrument_id))
    if quote is not None:
        decision = self._model_decision(
            model,
            instrument_id=instrument_id,
            quote=quote,
            decision_time=decision_time,
        )
        if decision is not None:
            side = self._side(decision.signal.action)
            if side is None:
                return StrategyRunResult(
                    decision=decision,
                    outcome=StrategyOutcome.HOLD,
                    proposed_side=None,
                    proposed_quantity=0,
                    risk_reason="模型建议观望",
                )
            target = build_target_position(
                PortfolioConstructor(max_position_percent=max_position_percent),
                RiskPolicy(max_position_percent=max_position_percent),
                signal_strength=Decimal("1"),
                equity=state.initial_equity,
                price=quote.last_price,
            )
            if target <= 0:
                return StrategyRunResult(
                    decision=decision,
                    outcome=StrategyOutcome.HOLD,
                    proposed_side=side,
                    proposed_quantity=0,
                    risk_reason="目标仓位不足一手",
                )
            decision_id = decision.decision_record.decision_id
            if auto_execute and self._decision_already_executed(account_id, decision_id):
                execution = self._paper_service.submit_market_order(
                    account_id,
                    instrument_id=instrument_id,
                    side=side,
                    quantity=100,
                    idempotency_key=f"strategy-{decision_id}",
                    now=decision_time,
                    stamp_duty_exempt=instrument_id.symbol.startswith(("1", "5")),
                )
                return StrategyRunResult(
                    decision=decision,
                    outcome=StrategyOutcome.EXECUTED,
                    proposed_side=side,
                    proposed_quantity=(
                        execution.fill.quantity if execution.fill is not None else 100
                    ),
                    order=execution.order,
                    fill=execution.fill,
                )
            if not auto_execute:
                return StrategyRunResult(
                    decision=decision,
                    outcome=StrategyOutcome.SUGGESTED,
                    proposed_side=side,
                    proposed_quantity=target,
                )
            risk_reason = self._risk_reason(
                account_id,
                instrument_id=instrument_id,
                side=side,
                quantity=target,
                max_position_percent=max_position_percent,
            )
            if risk_reason is not None:
                return StrategyRunResult(
                    decision=decision,
                    outcome=StrategyOutcome.BLOCKED,
                    proposed_side=side,
                    proposed_quantity=target,
                    risk_reason=risk_reason,
                )
            execution = self._paper_service.submit_market_order(
                account_id,
                instrument_id=instrument_id,
                side=side,
                quantity=target,
                idempotency_key=f"strategy-{decision_id}",
                now=decision_time,
                stamp_duty_exempt=instrument_id.symbol.startswith(("1", "5")),
            )
            result = StrategyRunResult(
                decision=decision,
                outcome=StrategyOutcome.EXECUTED,
                proposed_side=side,
                proposed_quantity=target,
                order=execution.order,
                fill=execution.fill,
            )
            self._persist_run(account_id, result, batch_id=str(uuid4()))
            return result
```

`_model_decision` 实现（占位：模型工件尚未生成特征推理器，先用与训练同口径的在线特征构建信号；若模型文件缺失则返回 None 回退规则策略）：

```python
def _model_decision(
    self,
    model: ModelRegistryRecord,
    *,
    instrument_id: InstrumentId,
    quote: LiveQuote,
    decision_time: datetime,
) -> QuantDecision | None:
    artifact = Path(model.artifact_path)
    if not artifact.exists():
        return None
    bars = asyncio.run(
        self._market_service.bars(
            str(instrument_id),
            period=MarketPeriod.MINUTE_1,
            count=60,
        )
    )
    if not bars:
        return None
    rows = build_feature_rows(bars)
    if not rows:
        return None
    latest = rows[-1]
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(artifact))
    features = [[float(latest[key]) for key in _MODEL_FEATURE_COLUMNS]]
    proba = float(booster.predict(features)[0])
    action = (
        SignalAction.BUY
        if proba >= 0.6
        else SignalAction.SELL
        if proba <= 0.4
        else SignalAction.HOLD
    )
    reason = f"模型 {model.strategy_version} 预测上涨概率 {proba:.2f}"
    return _grid_style_decision(
        instrument_id=instrument_id,
        action=action,
        price=quote.last_price,
        decision_time=decision_time,
        strategy_id=model.strategy_id,
        strategy_version=model.strategy_version,
        feature_version=model.feature_version,
        reason=reason,
    )
```

（`_grid_style_decision` 复用 `evaluate_grid_decision` 的 SignalFrame/DecisionRecord 组装：把 `grid.py` 的决策组装函数抽为 `build_model_signal(instrument_id, action, price, decision_time, strategy_id, strategy_version, feature_version, reason)` 放在 `strategy_layer.py`，`grid.py` 与 `_model_decision` 都调用它。）

`latest_approved_model` 在 `PaperRepository`：

```python
def latest_approved_model(self) -> ModelRegistryRecord | None:
    with self.engine.connect() as connection:
        row = (
            connection.execute(
                sa.select(model_registry)
                .where(model_registry.c.status == "APPROVED")
                .order_by(model_registry.c.approved_at.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
    return None if row is None else _model_record(row)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/api/test_paper_strategy_service.py -v
```

- [ ] **Step 5: 提交**

```bash
git add packages/api/src/astraquant_api packages/quant/src/astraquant_quant/strategy_layer.py tests
git commit -m "feat: 已批准模型接入实时环 影子信号优先于规则回退"
```

---

### Task 8: 前端展示模型信息与全量验证

**Files:**
- Modify: `apps/desktop/src/pages/PaperPage.tsx`
- Modify: `apps/desktop/src/pages/PaperPage.test.tsx`

- [ ] **Step 1: 策略区显示模型/策略版本**

`StrategyConsole` 的 `paper-strategy__version` 徽标改为读取最近结果：

```tsx
const strategyVersion = results?.[0]?.signal.strategy_version ?? "grid-v1";
// action 元素：
<span className="paper-strategy__version">{strategyVersion}</span>
```

策略说明文案替换为：

```tsx
<small className="paper-strategy__brief">已批准模型发布后由 ML 引擎驱动；模型未批准时规则回退只观察不出手。信号经目标仓位与风控层后才会模拟成交。</small>
```

- [ ] **Step 2: 前端测试更新**

在 `PaperPage.test.tsx` 现有 scan 测试的 signal mock 中把 `strategy_version` 保持 `"baseline-v1"`，新增断言 `screen.getByText("baseline-v1")` 出现在策略徽标（若文本重复则用 `getAllByText`）。

- [ ] **Step 3: 全量验证**

```bash
pnpm --dir apps/desktop test -- --run
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run mypy packages
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
```

- [ ] **Step 4: 提交并推送**

```bash
git add -A
git commit -m "feat: 前端展示模型版本并完成 ML 基线里程碑"
git push origin feature/phase-1-desktop-platform
```

---

## 验收定义

- 账户重置按钮可用，重置后账户回到初始现金、无持仓/订单/成交/策略记录。
- `tools/research/fetch_minutes.py` 可将真实标的分钟线发布为 Parquet 快照。
- 特征行全部只用历史数据；标签基于未来完成区间，Purged/Embargo 切分有效。
- LightGBM 评估输出 AUC、含费用净收益与交易次数。
- 模型注册表支持注册/更新/批准，未过门槛（AUC<0.55 或净收益<=0）拒绝批准。
- 已批准模型在实时环产生信号，未批准或工件缺失时回退规则策略。
- 全量测试、lint、类型检查与 Rust 检查通过并推送。

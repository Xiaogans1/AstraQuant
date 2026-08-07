from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from tests.api.test_paper_routes import build_client

from astraquant_api.market_service import MarketDataService
from astraquant_data.market_bars import MarketBar
from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId


def _publish_dataset(data_root: Path, bars: list[Bar], dataset_id: str) -> None:
    ParquetSnapshotStore(data_root).publish_bars(
        dataset_id=dataset_id,
        bars=bars,
        provider={"id": "eastmoney", "interface": "bridge", "version": "1"},
        calendar_version="eastmoney",
        availability_policy="bar_end",
    )


def _minute_bars(instrument: str, count: int = 200) -> list[Bar]:
    instrument_id = InstrumentId.parse(instrument)
    start = datetime(2026, 8, 6, 1, 30, tzinfo=UTC)
    result: list[Bar] = []
    for index in range(count):
        close = Decimal("10") + Decimal(index % 5) * Decimal("0.01")
        result.append(
            Bar(
                instrument_id=instrument_id,
                frequency=BarFrequency.MINUTE,
                trading_date=start.date(),
                event_time=start + timedelta(minutes=index),
                available_time=start + timedelta(minutes=index + 1),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("100"),
                turnover=close * 100,
                open_interest=None,
                settlement=None,
                adjustment=Adjustment.NONE,
                availability_estimated=False,
            )
        )
    return result


def _make_artifact(tmp_path: Path) -> Path:
    import lightgbm as lgb
    import numpy as np

    from astraquant_data.market_bars import MarketBar
    from astraquant_quant.research_features import build_feature_rows, label_future_return
    from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS

    bars = _minute_bars("159516.SZSE", count=120)
    market_bars = [
        MarketBar(
            timestamp=bar.event_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            turnover=bar.turnover if bar.turnover is not None else bar.open,
            previous_close=bar.open,
        )
        for bar in bars
    ]
    training: list[dict[str, float | int]] = []
    for index, row in enumerate(build_feature_rows(market_bars)):
        label = label_future_return(
            market_bars,
            index=index + 30,
            horizon=5,
            threshold=Decimal("0.005"),
        )
        if label < 0:
            continue
        training.append({**row, "label": label})
    dataset = lgb.Dataset(
        np.asarray(
            [[float(row[key]) for key in MODEL_FEATURE_COLUMNS] for row in training],
            dtype=float,
        ),
        label=[int(row["label"]) for row in training],
    )
    booster = lgb.train({"objective": "binary", "verbosity": -1}, dataset, num_boost_round=4)
    artifact = tmp_path / "model.txt"
    booster.save_model(str(artifact))
    return artifact


def _register_model(
    client: TestClient,
    artifact: Path,
    model_id: str,
    *,
    approve: bool,
) -> None:
    import json as _json

    response = client.post(
        "/v1/paper/models",
        json={
            "model_id": model_id,
            "strategy_id": "microstructure-lgbm",
            "strategy_version": "lgbm-v1",
            "feature_version": "minute-v1",
            "artifact_path": str(artifact),
            "metrics_json": _json.dumps({"auc": 0.58, "net_return": 0.02}),
            "params_json": _json.dumps({"buy_threshold": 0.5, "sell_threshold": 0.4}),
        },
    )
    assert response.status_code == 201
    if approve:
        assert client.post(f"/v1/paper/models/{model_id}/approve").status_code == 200


def _register_approved_model(client: TestClient, tmp_path: Path) -> None:
    _register_model(client, _make_artifact(tmp_path), "replay-model-001", approve=True)


def test_research_datasets_lists_recorded_snapshots(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _publish_dataset(
        data_root,
        _minute_bars("159516.SZSE"),
        "cn-equity-159516-szse-1m-none",
    )
    client, _ = build_client(tmp_path)

    response = client.get("/v1/research/datasets")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["dataset_id"] == "cn-equity-159516-szse-1m-none"
    assert payload[0]["instrument_id"] == "159516.SZSE"
    assert payload[0]["bar_count"] == 200


def _attach_bars_provider(
    client: TestClient,
    market: MarketDataService,
    bars: list[MarketBar],
) -> None:
    from collections.abc import Sequence
    from datetime import date

    from astraquant_data.live_providers import ProviderHealth
    from astraquant_data.market_bars import MarketPeriod

    class FakeBarsProvider:
        def __init__(self, rows: list[MarketBar]) -> None:
            self._rows = rows

        def connect(self, _token: str) -> None: ...
        def disconnect(self) -> None: ...
        def poll(self, _instruments: Sequence[InstrumentId]) -> list[object]:
            return []

        def health(self) -> ProviderHealth:
            return ProviderHealth(provider_id="test")

        def history_n(self, _instrument_id: InstrumentId, *, count: int) -> list[object]:
            return []

        def bars(
            self,
            _instrument_id: InstrumentId,
            *,
            period: MarketPeriod,
            count: int,
        ) -> list[MarketBar]:
            assert period is MarketPeriod.MINUTE_1
            return self._rows[-count:]

        def search(self, _query: str) -> list[object]:
            return []

        def trading_dates(self, start: date, _end: date) -> list[date]:
            return [start]

    market.configure_provider(FakeBarsProvider(bars))  # type: ignore[arg-type]
    client.app.state.runtime.market_service = market  # type: ignore[attr-defined]


def _market_bars(count: int = 200) -> list[MarketBar]:

    rows = _minute_bars("159516.SZSE", count=count)
    return [
        MarketBar(
            timestamp=bar.event_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            turnover=bar.turnover if bar.turnover is not None else bar.open,
            previous_close=bar.open,
        )
        for bar in rows
    ]


def test_research_replay_requires_existing_model(tmp_path: Path) -> None:
    client, market = build_client(tmp_path)
    _attach_bars_provider(client, market, _market_bars())

    response = client.post(
        "/v1/research/replay",
        json={
            "instruments": [{"instrument_id": "159516.SZSE"}],
            "model_id": "replay-model-001",
            "initial_cash": "100000",
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "model_not_found"


def test_research_replay_allows_draft_model_with_status_marker(tmp_path: Path) -> None:
    client, market = build_client(tmp_path)
    _attach_bars_provider(client, market, _market_bars())
    _register_model(client, _make_artifact(tmp_path), "draft-model-001", approve=False)

    replay_response = client.post(
        "/v1/research/replay",
        json={
            "instruments": [{"instrument_id": "159516.SZSE"}],
            "model_id": "draft-model-001",
            "initial_cash": "100000",
        },
    )

    assert replay_response.status_code == 200
    payload = replay_response.json()
    assert isinstance(payload, list)
    assert payload[0]["model_status"] == "DRAFT"


def test_research_replay_returns_metrics_trades_and_bars(tmp_path: Path) -> None:
    client, market = build_client(tmp_path)
    _attach_bars_provider(client, market, _market_bars())
    _register_approved_model(client, tmp_path)

    response = client.post(
        "/v1/research/replay",
        json={
            "instruments": [{"instrument_id": "159516.SZSE"}],
            "model_id": "replay-model-001",
            "initial_cash": "100000",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload[0]["instrument_id"] == "159516.SZSE"
    assert payload[0]["bars_count"] == 200
    assert "buys" in payload[0]
    assert "sells" in payload[0]
    assert "win_rate" in payload[0]
    assert "net_return_percent" in payload[0]
    assert "max_drawdown_percent" in payload[0]
    assert "sharpe" in payload[0]
    assert "profit_factor" in payload[0]
    assert isinstance(payload[0]["trades"], list)
    assert len(payload[0]["bars"]) == 200
    assert len(payload[0]["equity_points"]) == 170


def test_research_replay_supports_multiple_instruments_and_opening_position(
    tmp_path: Path,
) -> None:
    client, market = build_client(tmp_path)
    rows = _market_bars(200)
    second = _minute_bars("159599.SZSE", count=120)
    from astraquant_data.market_bars import MarketBar

    second_market = [
        MarketBar(
            timestamp=bar.event_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            turnover=bar.turnover if bar.turnover is not None else bar.open,
            previous_close=bar.open,
        )
        for bar in second
    ]
    _attach_bars_provider(client, market, [*rows, *second_market])
    _register_approved_model(client, tmp_path)

    response = client.post(
        "/v1/research/replay",
        json={
            "instruments": [
                {"instrument_id": "159516.SZSE"},
                {
                    "instrument_id": "159599.SZSE",
                    "opening": {
                        "instrument_id": "159599.SZSE",
                        "quantity": 1000,
                        "available_quantity": 400,
                        "average_cost": "3.0",
                    },
                },
            ],
            "model_id": "replay-model-001",
            "initial_cash": "100000",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["instrument_id"] for item in payload] == ["159516.SZSE", "159599.SZSE"]
    assert payload[1]["initial_equity"] > payload[1]["initial_cash"]

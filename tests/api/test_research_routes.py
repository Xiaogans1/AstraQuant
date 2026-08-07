from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from tests.api.test_paper_routes import build_client

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


def _register_approved_model(client: TestClient, tmp_path: Path) -> None:
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
    response = client.post(
        "/v1/paper/models",
        json={
            "model_id": "replay-model-001",
            "strategy_id": "microstructure-lgbm",
            "strategy_version": "lgbm-v1",
            "feature_version": "minute-v1",
            "artifact_path": str(artifact),
            "metrics_json": json.dumps({"auc": 0.58, "net_return": 0.02}),
            "params_json": json.dumps({"buy_threshold": 0.5, "sell_threshold": 0.4}),
        },
    )
    assert response.status_code == 201
    assert client.post("/v1/paper/models/replay-model-001/approve").status_code == 200


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


def test_research_replay_requires_approved_model(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _publish_dataset(
        data_root,
        _minute_bars("159516.SZSE"),
        "cn-equity-159516-szse-1m-none",
    )
    client, _ = build_client(tmp_path)

    response = client.post(
        "/v1/research/replay",
        json={
            "dataset_id": "cn-equity-159516-szse-1m-none",
            "model_id": "replay-model-001",
            "initial_cash": "100000",
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "model_not_found"


def test_research_replay_returns_metrics_trades_and_bars(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _publish_dataset(
        data_root,
        _minute_bars("159516.SZSE"),
        "cn-equity-159516-szse-1m-none",
    )
    client, _ = build_client(tmp_path)
    _register_approved_model(client, tmp_path)

    response = client.post(
        "/v1/research/replay",
        json={
            "dataset_id": "cn-equity-159516-szse-1m-none",
            "model_id": "replay-model-001",
            "initial_cash": "100000",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["instrument_id"] == "159516.SZSE"
    assert payload["bars_count"] == 200
    assert "buys" in payload
    assert "sells" in payload
    assert "win_rate" in payload
    assert "net_return_percent" in payload
    assert isinstance(payload["trades"], list)
    assert len(payload["bars"]) == 200
    assert len(payload["equity_points"]) == 170

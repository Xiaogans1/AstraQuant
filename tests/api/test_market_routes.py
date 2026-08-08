from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from astraquant_api.app import AppState, create_app
from astraquant_api.data_repository import DataCatalogRepository
from astraquant_api.database import create_database, migrate_database
from astraquant_api.logging import ActivityBuffer
from astraquant_api.market_service import MarketDataService
from astraquant_api.repository import TaskRepository
from astraquant_api.secret_store import MemorySecretStore
from astraquant_api.task_model import TaskRecord
from astraquant_data.live_providers import ProviderHealth
from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_data.subscriptions import SubscriptionBudget
from astraquant_domain import InstrumentId, LiveQuote

TOKEN = "m" * 43


class IdleSupervisor:
    def start_demo(self, task: TaskRecord) -> TaskRecord:
        return task

    def start(
        self,
        task: TaskRecord,
        _worker_target: Callable[..., None],
        _worker_args: tuple[object, ...],
    ) -> TaskRecord:
        return task

    def cancel(self, _task_id: str) -> TaskRecord:
        raise KeyError

    def active_count(self) -> int:
        return 0

    def shutdown(self, _timeout_seconds: float) -> None:
        return None


class EmptyProvider:
    def connect(self, token: str) -> None:
        assert token == "eastmoney-test-token"

    def disconnect(self) -> None:
        return None

    def poll(self, instruments: Sequence[InstrumentId]) -> list[LiveQuote]:
        return []

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id="eastmoney")

    def history_n(self, instrument_id: InstrumentId, *, count: int) -> list[dict[str, Any]]:
        return []

    def bars(
        self,
        instrument_id: InstrumentId,
        *,
        period: MarketPeriod,
        count: int,
    ) -> list[MarketBar]:
        return [
            MarketBar(
                timestamp=datetime(2026, 8, 6, 2, 10, tzinfo=UTC),
                open=Decimal("0.701"),
                high=Decimal("0.715"),
                low=Decimal("0.699"),
                close=Decimal("0.712"),
                volume=Decimal("481900"),
                turnover=Decimal("34260000"),
                previous_close=Decimal("0.701"),
            )
        ]

    def search(self, query: str) -> list[dict[str, Any]]:
        return [{"symbol": "SHSE.510300", "sec_name": "沪深300ETF", "query": query}]

    def trading_dates(self, start: date, end: date) -> list[date]:
        return []


@pytest.fixture
def market_state(tmp_path: Path) -> AppState:
    database_url = f"sqlite:///{tmp_path / 'market-api.sqlite3'}"
    migrate_database(database_url)
    engine = create_database(database_url)
    repository = TaskRepository(engine)
    secret_store = MemorySecretStore("eastmoney-test-token")
    service = MarketDataService(
        provider=EmptyProvider(),
        budget=SubscriptionBudget(),
        secret_store=secret_store,
        watchlist_store=repository,
        poll_interval_seconds=30,
    )
    return AppState(
        repository=repository,
        data_catalog=DataCatalogRepository(engine),
        supervisor=IdleSupervisor(),
        activity=ActivityBuffer(),
        session_token=TOKEN,
        state_dir=tmp_path,
        market_service=service,
        secret_store=secret_store,
        market_provider_factory=lambda _path, _timeout: EmptyProvider(),
    )


@pytest.fixture
def client(market_state: AppState) -> TestClient:
    return TestClient(create_app(market_state))


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def test_every_market_route_requires_local_authentication(client: TestClient) -> None:
    requests = [
        ("GET", "/v1/market/connection"),
        ("PUT", "/v1/market/eastmoney/config"),
        ("POST", "/v1/market/connection/start"),
        ("POST", "/v1/market/connection/stop"),
        ("GET", "/v1/market/home"),
        ("GET", "/v1/market/instruments/search?q=510300"),
        ("GET", "/v1/market/instruments/000001.SSE/intraday"),
        ("GET", "/v1/market/instruments/000001.SSE/bars?period=5m"),
        ("GET", "/v1/market/instruments/000001.SSE/signal"),
        ("POST", "/v1/market/watchlist"),
        ("DELETE", "/v1/market/watchlist/600000.SSE"),
    ]
    for method, path in requests:
        response = client.request(method, path, json={"instrument_id": "600000.SSE"})
        assert response.status_code == 401, (method, path, response.text)


def test_home_contains_six_core_slots_and_honest_unavailable_features(
    auth_client: TestClient,
) -> None:
    response = auth_client.get("/v1/market/home")
    assert response.status_code == 200
    body = response.json()
    assert len(body["core_indices"]) == 6
    assert all(item["last_price"] is None for item in body["core_indices"])
    assert body["breadth"] == {
        "status": "UNAVAILABLE",
        "reason": "当前东财免费行情不提供全市场宽度",
    }
    assert body["intelligence"]["status"] == "UNAVAILABLE"
    assert body["candidates"] == []
    assert "eastmoney-test-token" not in json.dumps(body, ensure_ascii=False)
    assert isinstance(body["connection"]["token_configured"], bool)


def test_home_keeps_unknown_change_values_null(
    auth_client: TestClient,
    market_state: AppState,
) -> None:
    assert market_state.market_service is not None
    market_state.market_service.record_quotes(
        [
            LiveQuote.minimum(
                InstrumentId.parse("000001.SSE"),
                event_time=datetime(2026, 8, 6, 2, 11, tzinfo=UTC),
                last_price=Decimal("3884.55"),
                previous_close=None,
            )
        ]
    )

    quote = auth_client.get("/v1/market/home").json()["core_indices"][0]

    assert quote["last_price"] == "3884.55"
    assert quote["change"] is None
    assert quote["change_percent"] is None
    assert quote["previous_close"] is None
    assert quote["open"] == "3884.55"
    assert quote["high"] == "3884.55"
    assert quote["low"] == "3884.55"
    assert quote["volume"] == "0"


def test_configuration_stores_token_without_returning_it(
    auth_client: TestClient,
    market_state: AppState,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_python = tmp_path / "python.exe"
    sdk_python.touch()
    monkeypatch.setattr("astraquant_api.market_routes.validate_sdk_python", lambda _: True)

    response = auth_client.put(
        "/v1/market/eastmoney/config",
        json={"sdk_python_path": str(sdk_python), "token": "new-private-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider_id": "eastmoney",
        "sdk_configured": True,
        "token_configured": True,
    }
    assert "new-private-token" not in response.text
    assert market_state.secret_store is not None
    assert market_state.secret_store.get_eastmoney_token() == "new-private-token"
    stored = market_state.repository.get_setting("market.eastmoney")
    assert "token" not in json.dumps(stored).lower()


def test_connection_start_stop_and_search(auth_client: TestClient) -> None:
    started = auth_client.post("/v1/market/connection/start")
    assert started.status_code == 200
    assert started.json()["state"] in {"CONNECTING", "CLOSED"}

    search = auth_client.get("/v1/market/instruments/search?q=510300")
    assert search.status_code == 200
    assert search.json()[0]["instrument_id"] == "510300.SSE"

    stopped = auth_client.post("/v1/market/connection/stop")
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "DISCONNECTED"


def test_configured_market_connection_starts_with_app_lifespan(
    market_state: AppState,
) -> None:
    assert market_state.market_service is not None
    assert market_state.market_service.connection().state.value == "DISCONNECTED"

    with TestClient(create_app(market_state)) as started_client:
        started_client.headers.update({"Authorization": f"Bearer {TOKEN}"})
        response = started_client.get("/v1/market/connection")
        assert response.status_code == 200
        assert response.json()["state"] in {"CONNECTING", "CLOSED"}

    assert market_state.market_service.connection().state.value == "DISCONNECTED"


def test_watchlist_is_bounded_and_rejects_continuous_futures(
    auth_client: TestClient,
    market_state: AppState,
) -> None:
    invalid = auth_client.post("/v1/market/watchlist", json={"instrument_id": "RB0.SHFE"})
    assert invalid.status_code == 422
    for index in range(34):
        response = auth_client.post(
            "/v1/market/watchlist",
            json={"instrument_id": f"{600000 + index}.SSE"},
        )
        assert response.status_code == 200
    overflow = auth_client.post(
        "/v1/market/watchlist",
        json={"instrument_id": "700000.SSE"},
    )
    assert overflow.status_code == 409
    stored = market_state.repository.get_setting("market.watchlist")
    assert isinstance(stored, dict)
    assert stored["version"] == 1
    assert stored["items"][0] == {
        "instrument_id": "600000.SSE",
        "name": None,
    }
    serialized = json.dumps(stored, ensure_ascii=False).lower()
    assert "price" not in serialized
    assert "token" not in serialized


def test_intraday_count_and_instrument_validation(auth_client: TestClient) -> None:
    assert (
        auth_client.get("/v1/market/instruments/000001.SSE/intraday?count=241").status_code == 422
    )
    assert auth_client.get("/v1/market/instruments/RB0.SHFE/intraday").status_code == 422


def test_period_bars_are_strict_and_validate_query_values(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/market/instruments/159516.SZSE/bars?period=5m&count=300")

    assert response.status_code == 200
    assert response.json() == [
        {
            "timestamp": "2026-08-06T02:10:00Z",
            "open": 0.701,
            "high": 0.715,
            "low": 0.699,
            "close": 0.712,
            "volume": 481900.0,
            "turnover": 34260000.0,
            "previous_close": 0.701,
        }
    ]
    assert auth_client.get("/v1/market/instruments/159516.SZSE/bars?period=2m").status_code == 422
    assert (
        auth_client.get("/v1/market/instruments/159516.SZSE/bars?period=1d&count=5001").status_code
        == 422
    )


def test_realtime_signal_route_returns_auditable_suppressed_decision(
    auth_client: TestClient,
) -> None:
    response = auth_client.get("/v1/market/instruments/159516.SZSE/signal")

    assert response.status_code == 200
    body = response.json()
    assert body["features"]["feature_snapshot_id"].startswith("feature-")
    assert body["features"]["status"] in {"READY", "WARMING_UP"}
    assert body["signal"]["signal_id"].startswith("signal-")
    assert body["signal"]["state"] == "SUPPRESSED"
    assert body["signal"]["action"] == "HOLD"
    assert body["signal"]["strategy_id"] == "intraday-momentum-volume"
    assert body["signal"]["strategy_version"] == "baseline-v1"
    assert body["decision_record"]["decision_id"].startswith("decision-")
    assert body["decision_record"]["feature_snapshot_id"] == body["features"]["feature_snapshot_id"]
    assert "MARKET_NOT_LIVE" in body["decision_record"]["advisory_checks"]
    assert "token" not in json.dumps(body).lower()

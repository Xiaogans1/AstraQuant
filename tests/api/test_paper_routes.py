from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from astraquant_api.app import AppState, create_app
from astraquant_api.data_repository import DataCatalogRepository
from astraquant_api.database import create_database, migrate_database
from astraquant_api.logging import ActivityBuffer
from astraquant_api.market_service import MarketDataService
from astraquant_api.paper_repository import PaperRepository
from astraquant_api.paper_service import PaperService
from astraquant_api.paper_strategy_service import PaperStrategyService
from astraquant_api.repository import TaskRepository
from astraquant_api.secret_store import MemorySecretStore
from astraquant_api.task_model import TaskRecord
from astraquant_data.subscriptions import SubscriptionBudget
from astraquant_domain import InstrumentId, LiveQuote

TOKEN = "t" * 43
NOW = datetime(2026, 8, 6, 6, 30, tzinfo=UTC)


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


def build_client(tmp_path: Path) -> tuple[TestClient, MarketDataService]:
    database_url = f"sqlite:///{tmp_path / 'state.sqlite3'}"
    migrate_database(database_url)
    engine = create_database(database_url)
    market = MarketDataService(
        provider=None,
        budget=SubscriptionBudget(),
        secret_store=MemorySecretStore(None),
    )
    paper = PaperService(
        repository=PaperRepository(engine),
        market_service=market,
    )
    paper_repository = PaperRepository(engine)
    state = AppState(
        repository=TaskRepository(engine),
        data_catalog=DataCatalogRepository(engine),
        supervisor=IdleSupervisor(),
        activity=ActivityBuffer(),
        session_token=TOKEN,
        state_dir=tmp_path,
        paper_service=paper,
        paper_strategy_service=PaperStrategyService(
            paper_service=paper,
            market_service=market,
            repository=paper_repository,
        ),
    )
    client = TestClient(create_app(state))
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client, market


def create_account(client: TestClient) -> str:
    response = client.post(
        "/v1/paper/accounts",
        json={"name": "主模拟账户", "mode": "PAPER", "initial_cash": "100000"},
    )
    assert response.status_code == 201
    return str(response.json()["account"]["account_id"])


def test_paper_routes_require_authentication(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    client.headers.clear()

    assert client.get("/v1/paper/accounts").status_code == 401


def test_default_paper_account_is_created_once_and_reused(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)

    first = client.put("/v1/paper/accounts/default")
    second = client.put("/v1/paper/accounts/default")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["account"]["account_id"] == second.json()["account"]["account_id"]
    assert first.json()["account"]["name"] == "主模拟账户"
    assert first.json()["account"]["initial_cash"] == "100000"
    assert len(client.get("/v1/paper/accounts").json()) == 1


def test_default_paper_account_reuses_an_existing_ledger(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    existing_account_id = create_account(client)

    response = client.put("/v1/paper/accounts/default")

    assert response.status_code == 200
    assert response.json()["account"]["account_id"] == existing_account_id
    assert len(client.get("/v1/paper/accounts").json()) == 1


def test_create_account_and_add_opening_position(tmp_path: Path) -> None:
    client, market = build_client(tmp_path)
    account_id = create_account(client)

    response = client.post(
        f"/v1/paper/accounts/{account_id}/positions/opening",
        json={
            "instrument_id": "159516.SZSE",
            "name": "半导体设备ETF",
            "quantity": 1000,
            "available_quantity": 800,
            "average_cost": "0.6800",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["positions"][0]["instrument_id"] == "159516.SZSE"
    assert payload["positions"][0]["available_quantity"] == 800
    assert "159516.SZSE" in market.active_instruments()
    assert client.get("/v1/paper/accounts").json()[0]["account_id"] == account_id


def test_account_positions_expose_previous_close_from_real_quote(tmp_path: Path) -> None:
    client, market = build_client(tmp_path)
    account_id = create_account(client)
    client.post(
        f"/v1/paper/accounts/{account_id}/positions/opening",
        json={
            "instrument_id": "159516.SZSE",
            "name": "半导体设备ETF",
            "quantity": 1000,
            "available_quantity": 800,
            "average_cost": "0.6800",
        },
    )
    market.request_quote("159516.SZSE")
    market.record_quotes(
        [
            LiveQuote.minimum(
                InstrumentId.parse("159516.SZSE"),
                event_time=NOW,
                last_price=Decimal("0.714"),
                previous_close=Decimal("0.701"),
            )
        ]
    )

    payload = client.get(f"/v1/paper/accounts/{account_id}").json()

    assert payload["positions"][0]["previous_close"] == "0.701"


def test_update_cash_balance_persists_external_capital_without_fake_profit(
    tmp_path: Path,
) -> None:
    client, _ = build_client(tmp_path)
    account_id = create_account(client)
    client.post(
        f"/v1/paper/accounts/{account_id}/positions/opening",
        json={
            "instrument_id": "159516.SZSE",
            "name": "半导体设备ETF",
            "quantity": 1_000,
            "available_quantity": 800,
            "average_cost": "0.6800",
        },
    )

    response = client.patch(
        f"/v1/paper/accounts/{account_id}/cash",
        json={"cash": "50000"},
    )

    assert response.status_code == 200
    assert response.json()["account"]["cash"] == "50000"
    assert response.json()["latest_equity"]["initial_equity"] == "50680.0000"
    assert response.json()["latest_equity"]["total_pnl"] == "0.0000"
    persisted = client.get(f"/v1/paper/accounts/{account_id}").json()
    assert persisted["account"]["cash"] == "50000"


def test_virtual_order_uses_real_quote_and_is_idempotent(tmp_path: Path) -> None:
    client, market = build_client(tmp_path)
    account_id = create_account(client)
    market.request_quote("159516.SZSE")
    market.record_quotes(
        [
            LiveQuote.minimum(
                InstrumentId.parse("159516.SZSE"),
                event_time=NOW,
                last_price=Decimal("0.714"),
                previous_close=Decimal("0.701"),
            )
        ]
    )
    headers = {"Idempotency-Key": "paper-order-route-0001"}
    request = {
        "instrument_id": "159516.SZSE",
        "side": "BUY",
        "quantity": 100,
        "name": "半导体设备ETF",
        "stamp_duty_exempt": True,
    }

    first = client.post(
        f"/v1/paper/accounts/{account_id}/orders",
        json=request,
        headers=headers,
    )
    second = client.post(
        f"/v1/paper/accounts/{account_id}/orders",
        json=request,
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["order"] == second.json()["order"]
    assert len(client.get(f"/v1/paper/accounts/{account_id}/orders").json()) == 1
    assert len(client.get(f"/v1/paper/accounts/{account_id}/fills").json()) == 1
    assert len(client.get(f"/v1/paper/accounts/{account_id}/equity").json()) == 1


def test_order_without_quote_returns_stable_problem(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    account_id = create_account(client)

    response = client.post(
        f"/v1/paper/accounts/{account_id}/orders",
        json={
            "instrument_id": "159516.SZSE",
            "side": "BUY",
            "quantity": 100,
            "stamp_duty_exempt": True,
        },
        headers={"Idempotency-Key": "paper-order-route-0002"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "quote_unavailable"


def test_invalid_idempotency_key_is_rejected(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    account_id = create_account(client)

    response = client.post(
        f"/v1/paper/accounts/{account_id}/orders",
        json={"instrument_id": "159516.SZSE", "side": "BUY", "quantity": 100},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_idempotency_key"


def test_strategy_run_returns_auditable_hold_without_warm_features(tmp_path: Path) -> None:
    client, market = build_client(tmp_path)
    account_id = create_account(client)
    market.request_quote("159516.SZSE")
    market.record_quotes(
        [
            LiveQuote.minimum(
                InstrumentId.parse("159516.SZSE"),
                event_time=NOW,
                last_price=Decimal("0.714"),
                previous_close=Decimal("0.701"),
            )
        ]
    )

    response = client.post(
        f"/v1/paper/accounts/{account_id}/strategy/run",
        json={
            "instrument_id": "159516.SZSE",
            "quantity": 100,
            "auto_execute": False,
            "max_position_percent": "20",
        },
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "HOLD"
    assert response.json()["signal"]["strategy_version"] == "baseline-v1"
    assert response.json()["signal"]["instrument_id"] == "159516.SZSE"
    assert response.json()["decision_id"].startswith("decision-")


def test_strategy_scan_concurrently_checks_every_holding(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    account_id = create_account(client)
    for instrument_id, name in (
        ("159516.SZSE", "半导体设备ETF"),
        ("600000.SSE", "浦发银行"),
    ):
        client.post(
            f"/v1/paper/accounts/{account_id}/positions/opening",
            json={
                "instrument_id": instrument_id,
                "name": name,
                "quantity": 1000,
                "available_quantity": 1000,
                "average_cost": "0.7",
            },
        )

    response = client.post(
        f"/v1/paper/accounts/{account_id}/strategy/scan",
        json={
            "instrument_id": "159516.SZSE",
            "quantity": 100,
            "auto_execute": False,
            "max_position_percent": "20",
        },
    )

    assert response.status_code == 200
    results = response.json()
    assert [item["signal"]["instrument_id"] for item in results] == [
        "159516.SZSE",
        "600000.SSE",
    ]
    assert all(item["signal"]["strategy_version"] == "baseline-v1" for item in results)
    assert all(item["decision_id"].startswith("decision-") for item in results)


def test_strategy_scan_on_empty_account_returns_empty_list(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    account_id = create_account(client)

    response = client.post(
        f"/v1/paper/accounts/{account_id}/strategy/scan",
        json={
            "instrument_id": "159516.SZSE",
            "quantity": 100,
            "auto_execute": False,
            "max_position_percent": "20",
        },
    )

    assert response.status_code == 200
    assert response.json() == []


def test_strategy_runs_survive_reload_and_return_newest_batch(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    account_id = create_account(client)
    for instrument_id, name in (
        ("159516.SZSE", "半导体设备ETF"),
        ("600000.SSE", "浦发银行"),
    ):
        client.post(
            f"/v1/paper/accounts/{account_id}/positions/opening",
            json={
                "instrument_id": instrument_id,
                "name": name,
                "quantity": 1000,
                "available_quantity": 1000,
                "average_cost": "0.7",
            },
        )
    request = {
        "instrument_id": "159516.SZSE",
        "quantity": 100,
        "auto_execute": False,
        "max_position_percent": "20",
    }
    first_scan = client.post(f"/v1/paper/accounts/{account_id}/strategy/scan", json=request)
    assert first_scan.status_code == 200

    runs = client.get(f"/v1/paper/accounts/{account_id}/strategy/runs")
    assert runs.status_code == 200
    payload = runs.json()
    assert [item["signal"]["instrument_id"] for item in payload] == [
        "159516.SZSE",
        "600000.SSE",
    ]
    assert all(item["outcome"] == "HOLD" for item in payload)
    assert all(item["decision_id"].startswith("decision-") for item in payload)

    second_scan = client.post(f"/v1/paper/accounts/{account_id}/strategy/scan", json=request)
    assert second_scan.status_code == 200

    runs_after = client.get(f"/v1/paper/accounts/{account_id}/strategy/runs").json()
    assert runs_after[0]["decision_id"] != payload[0]["decision_id"]

    reloaded, _ = build_client(tmp_path)
    persisted = reloaded.get(f"/v1/paper/accounts/{account_id}/strategy/runs")
    assert persisted.status_code == 200
    assert persisted.json() == runs_after


def test_strategy_runs_on_empty_account_return_empty_list(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    account_id = create_account(client)

    response = client.get(f"/v1/paper/accounts/{account_id}/strategy/runs")

    assert response.status_code == 200
    assert response.json() == []

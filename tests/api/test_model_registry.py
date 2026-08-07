from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tests.api.test_paper_routes import build_client


def _register(client: TestClient) -> dict[str, object]:
    return client.post(
        "/v1/paper/models",
        json={
            "model_id": "lgbm-minute-001",
            "strategy_id": "microstructure-lgbm",
            "strategy_version": "lgbm-v1",
            "feature_version": "minute-v1",
            "artifact_path": "models/lgbm-minute-001.txt",
            "metrics_json": '{"auc": 0.50, "net_return": 0.01}',
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
    assert rejected.json()["code"] == "model_publish_gate_failed"

    updated = client.patch(
        "/v1/paper/models/lgbm-minute-001",
        json={
            "model_id": "lgbm-minute-001",
            "strategy_id": "microstructure-lgbm",
            "strategy_version": "lgbm-v1",
            "feature_version": "minute-v1",
            "artifact_path": "models/lgbm-minute-001.txt",
            "metrics_json": '{"auc": 0.58, "net_return": 0.035}',
        },
    )
    assert updated.status_code == 200

    approved = client.post("/v1/paper/models/lgbm-minute-001/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approved_at"] is not None

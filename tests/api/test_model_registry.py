from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from tests.api.test_paper_routes import build_client

from astraquant_api.database import create_database
from astraquant_api.paper_repository import PaperRepository


def _model_body(model_id: str, metrics_json: str) -> dict[str, str]:
    return {
        "model_id": model_id,
        "strategy_id": "microstructure-lgbm",
        "strategy_version": "lgbm-v1",
        "feature_version": "minute-v1",
        "artifact_path": f"models/{model_id}.txt",
        "metrics_json": metrics_json,
    }


def _register(client: TestClient) -> Any:
    return client.post(
        "/v1/paper/models",
        json=_model_body("lgbm-minute-001", '{"auc": 0.50, "net_return": 0.01}'),
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
        json=_model_body("lgbm-minute-001", '{"auc": 0.58, "net_return": 0.035}'),
    )
    assert updated.status_code == 200

    approved = client.post("/v1/paper/models/lgbm-minute-001/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approved_at"] is not None

    repository = PaperRepository(create_database(f"sqlite:///{tmp_path / 'state.sqlite3'}"))
    record = repository.get_model("lgbm-minute-001")
    assert record is not None
    assert record.semantic_class == "LEGACY_SEMANTICS"
    assert record.evidence_class == "LEGACY_UNVERIFIED"
    assert record.run_class == "EXPLORATORY"
    assert record.manifest_schema == "1"
    assert record.content_digest is None


def test_registered_model_cannot_be_duplicated_or_edited_after_approval(
    tmp_path: Path,
) -> None:
    client, _ = build_client(tmp_path)
    _register(client)
    assert (
        client.post(
            "/v1/paper/models/lgbm-minute-001/approve",
        ).status_code
        == 409
    )
    client.patch(
        "/v1/paper/models/lgbm-minute-001",
        json=_model_body("lgbm-minute-001", '{"auc": 0.58, "net_return": 0.035}'),
    )
    assert client.post("/v1/paper/models/lgbm-minute-001/approve").status_code == 200

    duplicate = _register(client)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "model_exists"

    immutable = client.patch(
        "/v1/paper/models/lgbm-minute-001",
        json=_model_body("lgbm-minute-001", '{"auc": 0.60, "net_return": 0.05}'),
    )
    assert immutable.status_code == 409
    assert immutable.json()["code"] == "model_immutable"


def test_model_operations_on_missing_model_return_404(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    body = _model_body("missing-001", '{"auc": 0.6, "net_return": 0.1}')

    patched = client.patch("/v1/paper/models/missing-001", json=body)
    assert patched.status_code == 404
    assert patched.json()["code"] == "model_not_found"

    approved = client.post("/v1/paper/models/missing-001/approve")
    assert approved.status_code == 404
    assert approved.json()["code"] == "model_not_found"


def test_patch_rejects_mismatched_model_id(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    _register(client)

    response = client.patch(
        "/v1/paper/models/lgbm-minute-001",
        json=_model_body("other-001", '{"auc": 0.58, "net_return": 0.035}'),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_model_id"


def test_approve_rejects_null_metric(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    model_id = "lgbm-null-metric"
    created = client.post(
        "/v1/paper/models",
        json=_model_body(model_id, '{"auc": null, "net_return": 0.1}'),
    )
    assert created.status_code == 201

    approved = client.post(f"/v1/paper/models/{model_id}/approve")

    assert approved.status_code == 409
    assert approved.json()["code"] == "model_publish_gate_failed"


def test_approve_rejects_auc_at_strict_boundary(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    model_id = "lgbm-boundary-055"
    created = client.post(
        "/v1/paper/models",
        json=_model_body(model_id, '{"auc": 0.55, "net_return": 0.02}'),
    )
    assert created.status_code == 201

    approved = client.post(f"/v1/paper/models/{model_id}/approve")

    assert approved.status_code == 409
    assert approved.json()["code"] == "model_publish_gate_failed"

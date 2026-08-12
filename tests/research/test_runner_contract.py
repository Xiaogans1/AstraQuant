from __future__ import annotations

import json
from pathlib import Path

CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "contracts" / "research-runner" / "v1"


def _schema(name: str) -> dict[str, object]:
    value = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_request_schema_requires_model_task_target_and_score_identity() -> None:
    schema = _schema("request.schema.json")
    required = schema["required"]

    assert isinstance(required, list)
    assert {
        "training_task_digest",
        "model_kind",
        "target_column",
        "score_semantics",
        "model_config",
        "validation_policy",
    }.issubset(required)


def test_response_schema_carries_score_semantics_back_to_the_host() -> None:
    schema = _schema("response.schema.json")
    required = schema["required"]

    assert isinstance(required, list)
    assert {
        "request_content_digest",
        "training_task_digest",
        "model_kind",
        "score_semantics",
        "predictions",
    }.issubset(required)

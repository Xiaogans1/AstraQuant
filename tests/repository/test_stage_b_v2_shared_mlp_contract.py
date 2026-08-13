from __future__ import annotations

import json
from pathlib import Path

CONTRACT_ROOT = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "research-runner"
    / "stage-b-v2-shared-mlp-v1"
)


def _schema(name: str) -> dict[str, object]:
    value = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_request_freezes_rows_trials_runner_and_model_policy() -> None:
    schema = _schema("request.schema.json")

    assert schema["additionalProperties"] is False
    required = schema["required"]
    assert isinstance(required, list)
    assert {
        "content_digest",
        "runner_identity",
        "source_materialization_digest",
        "feature_columns",
        "rows_file",
        "model_config",
        "trials",
    }.issubset(required)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    model = properties["model_config"]
    assert isinstance(model, dict)
    model_properties = model["properties"]
    assert isinstance(model_properties, dict)
    assert model_properties["hidden_dim"] == {"const": 64}
    assert model_properties["market_dim"] == {"const": 32}
    assert model_properties["batch_semantics"] == {
        "const": "DECISION_DATE_CROSS_SECTION"
    }


def test_response_requires_ordered_valid_and_outer_scores() -> None:
    schema = _schema("response.schema.json")

    assert schema["additionalProperties"] is False
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    trial = definitions["trial"]
    assert isinstance(trial, dict)
    required = trial["required"]
    assert isinstance(required, list)
    assert {
        "processor_digest",
        "model_digest",
        "inner_valid_predictions",
        "outer_test_predictions",
    }.issubset(required)

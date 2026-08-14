from __future__ import annotations

import json
from pathlib import Path

CONTRACT_ROOT = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "research-runner"
    / "stage-b-v2-stockmixer-v2-v1"
)


def _schema(name: str) -> dict[str, object]:
    value = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_request_freezes_exact_temporal_inputs_and_model_policy() -> None:
    schema = _schema("request.schema.json")

    assert schema["additionalProperties"] is False
    required = schema["required"]
    assert isinstance(required, list)
    assert {
        "content_digest",
        "runner_identity",
        "source_materialization_digest",
        "source_raw_export_digest",
        "temporal_panel_file",
        "rows_file",
        "feature_spec",
        "model_config",
        "trials",
    }.issubset(required)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    feature_spec = properties["feature_spec"]
    assert isinstance(feature_spec, dict)
    feature_properties = feature_spec["properties"]
    assert isinstance(feature_properties, dict)
    assert feature_properties["lookback"] == {"const": 64}
    assert feature_properties["price_transform"] == {
        "const": "PREVIOUS_CLOSE_RELATIVE_V1"
    }
    assert feature_properties["context_visibility"] == {
        "const": "DECISION_TIME_ONLY"
    }
    model = properties["model_config"]
    assert isinstance(model, dict)
    model_properties = model["properties"]
    assert isinstance(model_properties, dict)
    assert model_properties["hidden_dim"] == {"const": 64}
    assert model_properties["market_dim"] == {"const": 32}
    assert model_properties["context_dim"] == {"const": 32}
    assert model_properties["internal_purge_sessions"] == {"const": 11}
    assert model_properties["session_batch_size"] == {"const": 16}


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

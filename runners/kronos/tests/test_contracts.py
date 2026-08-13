from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from astraquant_kronos_runner.contracts import (
    KRONOS_REQUEST_SCHEMA,
    KRONOS_RESPONSE_SCHEMA,
    KRONOS_UPSTREAM_COMMIT,
    canonical_digest,
    validate_request,
    validate_response,
)

MODEL_REVISION = "2b554741eca47781b64468546e77fef3e85130e6"
TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _artifact(root: Path, directory: str, content: bytes) -> dict[str, str]:
    path = root / directory / "model.safetensors"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "path": path.relative_to(root).as_posix(),
        "digest": _digest_bytes(content),
    }


def _request(root: Path) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": KRONOS_REQUEST_SCHEMA,
        "upstream_commit": KRONOS_UPSTREAM_COMMIT,
        "provider_id": "eastmoney",
        "sources": [
            {
                "dataset_id": "cn-equity-512800-sse-1m-none",
                "instrument_id": "512800.SSE",
                "source_snapshot_id": f"sha256:{'1' * 64}",
            }
        ],
        "windows_file": {
            "path": "windows.parquet",
            "digest": f"sha256:{'2' * 64}",
        },
        "folds_digest": f"sha256:{'3' * 64}",
        "calendar_snapshot_id": f"sha256:{'4' * 64}",
        "rows": [
            {
                "fold_id": "fold-01",
                "row_id": 7,
                "instrument_id": "512800.SSE",
                "decision_time": "2026-08-07T06:50:00+00:00",
                "forecast_times": [
                    f"2026-08-07T06:{minute:02d}:00+00:00" for minute in range(51, 56)
                ],
            }
        ],
        "input_columns": ["open", "high", "low", "close", "volume", "amount"],
        "model": {
            "id": "NeoQuasar/Kronos-base",
            "revision": MODEL_REVISION,
            "weights": _artifact(root, "models/kronos-base", b"model"),
        },
        "tokenizer": {
            "id": "NeoQuasar/Kronos-Tokenizer-base",
            "revision": TOKENIZER_REVISION,
            "weights": _artifact(root, "models/kronos-tokenizer-base", b"tokenizer"),
        },
        "device_policy": {"preferred": "AUTO", "allow_cpu_fallback": True},
        "seed": 7,
        "context_length": 512,
        "prediction_length": 5,
        "sampling": {
            "temperature": 1.0,
            "top_k": 0,
            "top_p": 0.9,
            "sample_count": 5,
        },
    }
    return {"content_digest": canonical_digest(body), **body}


def _response(request: dict[str, object]) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": KRONOS_RESPONSE_SCHEMA,
        "request_content_digest": request["content_digest"],
        "upstream_commit": request["upstream_commit"],
        "model": {
            "id": request["model"]["id"],  # type: ignore[index]
            "revision": request["model"]["revision"],  # type: ignore[index]
            "weights_digest": request["model"]["weights"]["digest"],  # type: ignore[index]
        },
        "tokenizer": {
            "id": request["tokenizer"]["id"],  # type: ignore[index]
            "revision": request["tokenizer"]["revision"],  # type: ignore[index]
            "weights_digest": request["tokenizer"]["weights"]["digest"],  # type: ignore[index]
        },
        "environment": {
            "python": "3.11.13",
            "torch": "2.8.0",
            "device": "cpu",
        },
        "forecasts": [
            {
                "fold_id": "fold-01",
                "row_id": 7,
                "instrument_id": "512800.SSE",
                "decision_time": "2026-08-07T06:50:00+00:00",
                "expected_return": 0.002,
                "up_path_fraction": 0.6,
                "terminal_return_p10": -0.01,
                "terminal_return_p50": 0.002,
                "terminal_return_p90": 0.015,
                "predicted_volatility": 0.006,
                "uncertainty_width": 0.025,
            }
        ],
    }
    return {"content_digest": canonical_digest(body), **body}


def test_request_is_validated_and_has_stable_content_digest(tmp_path: Path) -> None:
    request = _request(tmp_path)

    assert validate_request(request, root=tmp_path) == request
    body = {key: value for key, value in request.items() if key != "content_digest"}
    assert canonical_digest(body) == request["content_digest"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["sources"][0].update(source_snapshot_id="latest"), "snapshot"),
        (lambda value: value.update(upstream_commit="0" * 40), "upstream"),
        (lambda value: value["model"].update(revision="main"), "revision"),
        (lambda value: value["model"]["weights"].update(digest="sha256:bad"), "digest"),
        (lambda value: value.update(context_length=0), "context_length"),
        (lambda value: value.update(prediction_length=0), "prediction_length"),
        (lambda value: value["sampling"].update(sample_count=0), "sample_count"),
        (
            lambda value: value.update(input_columns=["open", "high", "low", "close"]),
            "input_columns",
        ),
    ],
)
def test_request_rejects_unsealed_or_invalid_identity(
    tmp_path: Path, mutation, message: str
) -> None:
    request = _request(tmp_path)
    mutation(request)
    request["content_digest"] = canonical_digest(
        {key: value for key, value in request.items() if key != "content_digest"}
    )

    with pytest.raises(ValueError, match=message):
        validate_request(request, root=tmp_path)


def test_request_rejects_weight_path_escape_and_file_drift(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["model"]["weights"]["path"] = "../model.safetensors"  # type: ignore[index]
    request["content_digest"] = canonical_digest(
        {key: value for key, value in request.items() if key != "content_digest"}
    )
    with pytest.raises(ValueError, match="weights path"):
        validate_request(request, root=tmp_path)

    request = _request(tmp_path)
    (tmp_path / request["model"]["weights"]["path"]).write_bytes(b"changed")  # type: ignore[index]
    with pytest.raises(ValueError, match="weights digest"):
        validate_request(request, root=tmp_path)


def test_response_covers_request_rows_and_preserves_identity(tmp_path: Path) -> None:
    request = validate_request(_request(tmp_path), root=tmp_path)
    response = _response(request)

    assert validate_response(response, request=request) == response


def test_response_rejects_missing_reordered_or_non_finite_forecasts(tmp_path: Path) -> None:
    request = validate_request(_request(tmp_path), root=tmp_path)

    missing = _response(request)
    missing["forecasts"] = []
    missing["content_digest"] = canonical_digest(
        {key: value for key, value in missing.items() if key != "content_digest"}
    )
    with pytest.raises(ValueError, match="coverage"):
        validate_response(missing, request=request)

    non_finite = _response(request)
    non_finite["forecasts"][0]["expected_return"] = float("nan")  # type: ignore[index]
    with pytest.raises(ValueError, match="finite"):
        validate_response(non_finite, request=request)


def test_json_schemas_match_validators(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    request_path = repository_root / "contracts/kronos-runner/v1/request.schema.json"
    response_path = repository_root / "contracts/kronos-runner/v1/response.schema.json"
    request_schema = json.loads(request_path.read_text(encoding="utf-8"))
    response_schema = json.loads(response_path.read_text(encoding="utf-8"))
    request = _request(tmp_path)
    response = _response(request)

    jsonschema.Draft202012Validator(request_schema).validate(request)
    jsonschema.Draft202012Validator(response_schema).validate(response)

    invalid = copy.deepcopy(request)
    invalid["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(request_schema).validate(invalid)

"""Fail-closed contracts for the isolated Kronos zero-shot runner."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

KRONOS_REQUEST_SCHEMA = "astraquant.kronos-request/v1"
KRONOS_RESPONSE_SCHEMA = "astraquant.kronos-response/v1"
KRONOS_UPSTREAM_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
KRONOS_MODEL_ID = "NeoQuasar/Kronos-base"
KRONOS_MODEL_REVISION = "2b554741eca47781b64468546e77fef3e85130e6"
KRONOS_TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
KRONOS_TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_INPUT_COLUMNS = ["open", "high", "low", "close", "volume", "amount"]
_REQUEST_KEYS = {
    "content_digest",
    "schema_version",
    "upstream_commit",
    "provider_id",
    "sources",
    "windows_file",
    "folds_digest",
    "calendar_snapshot_id",
    "rows",
    "input_columns",
    "model",
    "tokenizer",
    "device_policy",
    "seed",
    "context_length",
    "prediction_length",
    "sampling",
}
_RESPONSE_KEYS = {
    "content_digest",
    "schema_version",
    "request_content_digest",
    "upstream_commit",
    "model",
    "tokenizer",
    "environment",
    "forecasts",
}
_FORECAST_KEYS = {
    "fold_id",
    "row_id",
    "instrument_id",
    "decision_time",
    "expected_return",
    "up_path_fraction",
    "terminal_return_p10",
    "terminal_return_p50",
    "terminal_return_p90",
    "predicted_volatility",
    "uncertainty_width",
}


def canonical_digest(value: object) -> str:
    """Return the stable SHA-256 identity of a finite JSON value."""
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("canonical JSON must contain only finite JSON values") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def validate_request(payload: object, *, root: Path) -> dict[str, object]:
    """Validate and return a sealed Kronos request without mutating it."""
    request = _object(payload, "request")
    _exact_keys(request, _REQUEST_KEYS, "request")
    if request["schema_version"] != KRONOS_REQUEST_SCHEMA:
        raise ValueError("request schema_version mismatch")
    if request["upstream_commit"] != KRONOS_UPSTREAM_COMMIT:
        raise ValueError("upstream commit mismatch")
    if request["provider_id"] != "eastmoney":
        raise ValueError("provider_id must be eastmoney")
    _digest_value(request["content_digest"], "content_digest")
    _digest_value(request["folds_digest"], "folds_digest")
    _digest_value(request["calendar_snapshot_id"], "calendar_snapshot_id")
    prediction_length = _integer(
        request["prediction_length"], "prediction_length", minimum=1
    )

    sources = _list(request["sources"], "sources")
    if not sources:
        raise ValueError("sources must not be empty")
    source_instruments: set[str] = set()
    for index, value in enumerate(sources):
        source = _object(value, f"source {index}")
        _exact_keys(
            source,
            {"dataset_id", "instrument_id", "source_snapshot_id"},
            f"source {index}",
        )
        _nonempty_string(source["dataset_id"], f"source {index} dataset_id")
        instrument = _nonempty_string(source["instrument_id"], f"source {index} instrument_id")
        if instrument in source_instruments:
            raise ValueError("source instrument_id must be unique")
        source_instruments.add(instrument)
        _digest_value(source["source_snapshot_id"], f"source {index} snapshot")

    windows = _object(request["windows_file"], "windows_file")
    _exact_keys(windows, {"path", "digest"}, "windows_file")
    if windows["path"] != "windows.parquet":
        raise ValueError("windows_file path mismatch")
    _digest_value(windows["digest"], "windows_file digest")

    if request["input_columns"] != _INPUT_COLUMNS:
        raise ValueError("input_columns must be canonical OHLCVA columns")
    rows = _list(request["rows"], "rows")
    if not rows:
        raise ValueError("rows must not be empty")
    row_keys: list[tuple[str, int, str, str]] = []
    for index, value in enumerate(rows):
        row = _object(value, f"row {index}")
        _exact_keys(
            row,
            {"fold_id", "row_id", "instrument_id", "decision_time", "forecast_times"},
            f"row {index}",
        )
        fold_id = _nonempty_string(row["fold_id"], f"row {index} fold_id")
        row_id = _integer(row["row_id"], f"row {index} row_id", minimum=0)
        instrument = _nonempty_string(row["instrument_id"], f"row {index} instrument_id")
        if instrument not in source_instruments:
            raise ValueError("row instrument_id is absent from sources")
        decision_time = _timestamp(row["decision_time"], f"row {index} decision_time")
        forecast_times = [
            _timestamp(item, f"row {index} forecast time")
            for item in _list(row["forecast_times"], f"row {index} forecast_times")
        ]
        parsed_decision = datetime.fromisoformat(decision_time.replace("Z", "+00:00"))
        parsed_forecasts = [
            datetime.fromisoformat(item.replace("Z", "+00:00")) for item in forecast_times
        ]
        if (
            len(parsed_forecasts) != prediction_length
            or any(item <= parsed_decision for item in parsed_forecasts)
            or any(
                previous >= current
                for previous, current in pairwise(parsed_forecasts)
            )
        ):
            raise ValueError("row forecast_times must match prediction_length and increase")
        row_keys.append((fold_id, row_id, instrument, decision_time))
    if len(set(row_keys)) != len(row_keys):
        raise ValueError("row identity must be unique")
    if row_keys != sorted(row_keys):
        raise ValueError("rows must use canonical order")

    _validate_artifact(
        request["model"],
        name="model",
        expected_id=KRONOS_MODEL_ID,
        expected_revision=KRONOS_MODEL_REVISION,
        root=root,
    )
    _validate_artifact(
        request["tokenizer"],
        name="tokenizer",
        expected_id=KRONOS_TOKENIZER_ID,
        expected_revision=KRONOS_TOKENIZER_REVISION,
        root=root,
    )

    device = _object(request["device_policy"], "device_policy")
    _exact_keys(device, {"preferred", "allow_cpu_fallback"}, "device_policy")
    if device["preferred"] not in {"AUTO", "CPU", "CUDA"}:
        raise ValueError("device_policy preferred mismatch")
    if not isinstance(device["allow_cpu_fallback"], bool):
        raise ValueError("device_policy allow_cpu_fallback must be boolean")
    _integer(request["seed"], "seed")
    _integer(request["context_length"], "context_length", minimum=1, maximum=512)

    sampling = _object(request["sampling"], "sampling")
    _exact_keys(sampling, {"temperature", "top_k", "top_p", "sample_count"}, "sampling")
    _finite_number(sampling["temperature"], "temperature", minimum_exclusive=0)
    _integer(sampling["top_k"], "top_k", minimum=0)
    _finite_number(sampling["top_p"], "top_p", minimum_exclusive=0, maximum=1)
    _integer(sampling["sample_count"], "sample_count", minimum=1)

    supplied = request["content_digest"]
    body = {key: value for key, value in request.items() if key != "content_digest"}
    if supplied != canonical_digest(body):
        raise ValueError("request content_digest mismatch")
    return request


def validate_response(payload: object, *, request: dict[str, object]) -> dict[str, object]:
    """Validate one complete, canonically ordered Kronos response."""
    response = _object(payload, "response")
    _exact_keys(response, _RESPONSE_KEYS, "response")
    if response["schema_version"] != KRONOS_RESPONSE_SCHEMA:
        raise ValueError("response schema_version mismatch")
    if response["request_content_digest"] != request["content_digest"]:
        raise ValueError("response request identity mismatch")
    if response["upstream_commit"] != request["upstream_commit"]:
        raise ValueError("response upstream identity mismatch")
    _validate_response_artifact(response["model"], request["model"], "model")
    _validate_response_artifact(response["tokenizer"], request["tokenizer"], "tokenizer")

    environment = _object(response["environment"], "environment")
    _exact_keys(environment, {"python", "torch", "device"}, "environment")
    for key in ("python", "torch", "device"):
        _nonempty_string(environment[key], f"environment {key}")

    forecasts = _list(response["forecasts"], "forecasts")
    actual_keys: list[tuple[str, int, str, str]] = []
    for index, value in enumerate(forecasts):
        forecast = _object(value, f"forecast {index}")
        _exact_keys(forecast, _FORECAST_KEYS, f"forecast {index}")
        identity = (
            _nonempty_string(forecast["fold_id"], f"forecast {index} fold_id"),
            _integer(forecast["row_id"], f"forecast {index} row_id", minimum=0),
            _nonempty_string(forecast["instrument_id"], f"forecast {index} instrument_id"),
            _timestamp(forecast["decision_time"], f"forecast {index} decision_time"),
        )
        actual_keys.append(identity)
        expected_return = _finite_number(
            forecast["expected_return"], f"forecast {index} expected_return"
        )
        _finite_number(
            forecast["up_path_fraction"],
            f"forecast {index} up_path_fraction",
            minimum=0,
            maximum=1,
        )
        p10 = _finite_number(forecast["terminal_return_p10"], f"forecast {index} p10")
        p50 = _finite_number(forecast["terminal_return_p50"], f"forecast {index} p50")
        p90 = _finite_number(forecast["terminal_return_p90"], f"forecast {index} p90")
        if not p10 <= p50 <= p90:
            raise ValueError("forecast terminal quantiles must be ordered")
        if expected_return != p50:
            raise ValueError("forecast expected_return must equal terminal_return_p50")
        _finite_number(
            forecast["predicted_volatility"],
            f"forecast {index} predicted_volatility",
            minimum=0,
        )
        _finite_number(
            forecast["uncertainty_width"],
            f"forecast {index} uncertainty_width",
            minimum=0,
        )

    expected_keys: list[tuple[str, int, str, str]] = []
    for index, value in enumerate(_list(request["rows"], "request rows")):
        row = _object(value, f"request row {index}")
        expected_keys.append(
            (
                str(row["fold_id"]),
                int(row["row_id"]),
                str(row["instrument_id"]),
                str(row["decision_time"]),
            )
        )
    if actual_keys != expected_keys:
        raise ValueError("forecast coverage or canonical order mismatch")

    _digest_value(response["content_digest"], "response content_digest")
    body = {key: value for key, value in response.items() if key != "content_digest"}
    if response["content_digest"] != canonical_digest(body):
        raise ValueError("response content_digest mismatch")
    return response


def _validate_artifact(
    value: object,
    *,
    name: str,
    expected_id: str,
    expected_revision: str,
    root: Path,
) -> None:
    artifact = _object(value, name)
    _exact_keys(artifact, {"id", "revision", "weights"}, name)
    if artifact["id"] != expected_id:
        raise ValueError(f"{name} id mismatch")
    revision = _nonempty_string(artifact["revision"], f"{name} revision")
    if not _COMMIT.fullmatch(revision) or revision != expected_revision:
        raise ValueError(f"{name} revision mismatch")
    weights = _object(artifact["weights"], f"{name} weights")
    _exact_keys(weights, {"path", "digest"}, f"{name} weights")
    relative = Path(_nonempty_string(weights["path"], f"{name} weights path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{name} weights path must stay within runner root")
    root_resolved = root.resolve()
    path = (root_resolved / relative).resolve()
    if root_resolved not in path.parents:
        raise ValueError(f"{name} weights path must stay within runner root")
    if not path.is_file():
        raise ValueError(f"{name} weights file is missing")
    digest = _digest_value(weights["digest"], f"{name} weights digest")
    actual = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    if digest != actual:
        raise ValueError(f"{name} weights digest mismatch")


def _validate_response_artifact(value: object, requested: object, name: str) -> None:
    artifact = _object(value, f"response {name}")
    request_artifact = _object(requested, f"request {name}")
    _exact_keys(artifact, {"id", "revision", "weights_digest"}, f"response {name}")
    request_weights = _object(request_artifact["weights"], f"request {name} weights")
    expected = {
        "id": request_artifact["id"],
        "revision": request_artifact["revision"],
        "weights_digest": request_weights["digest"],
    }
    if artifact != expected:
        raise ValueError(f"response {name} identity mismatch")


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} fields mismatch")


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _digest_value(value: object, name: str) -> str:
    text = _nonempty_string(value, name)
    if not _DIGEST.fullmatch(text) or text == f"sha256:{'0' * 64}":
        raise ValueError(f"{name} must be an exact SHA-256 digest")
    return text


def _integer(
    value: object,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value


def _finite_number(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
    minimum_exclusive: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if minimum_exclusive is not None and number <= minimum_exclusive:
        raise ValueError(f"{name} must be greater than {minimum_exclusive}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return number


def _timestamp(value: object, name: str) -> str:
    text = _nonempty_string(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return text

"""Shared authenticated HTTP client for formal capture commands."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

SESSION_TOKEN_ENV = "ASTRAQUANT_SESSION_TOKEN"


class FormalCaptureCliError(RuntimeError):
    pass


def post_formal_command(
    *,
    api_url: str,
    path: str,
    idempotency_key: str,
    payload: Mapping[str, object],
    environ: Mapping[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    result = post_json_command(
        api_url=api_url,
        path=path,
        idempotency_key=idempotency_key,
        payload=payload,
        environ=environ,
        timeout_seconds=timeout_seconds,
    )
    if not all(
        isinstance(result.get(name), str) and result[name] for name in ("task_id", "status")
    ):
        raise FormalCaptureCliError("formal capture API response is invalid")
    return result


def post_json_command(
    *,
    api_url: str,
    path: str,
    payload: Mapping[str, object],
    environ: Mapping[str, str],
    timeout_seconds: float,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    token = environ.get(SESSION_TOKEN_ENV, "").strip()
    if not token:
        raise FormalCaptureCliError(f"{SESSION_TOKEN_ENV} is required")
    if idempotency_key is not None and (
        not 8 <= len(idempotency_key) <= 200
        or any(ord(character) < 33 or ord(character) > 126 for character in idempotency_key)
    ):
        raise FormalCaptureCliError("idempotency key is invalid")
    if timeout_seconds <= 0:
        raise FormalCaptureCliError("timeout must be positive")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}{path}",
        data=json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read())
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise FormalCaptureCliError("formal capture API command failed") from error
    if not isinstance(result, dict):
        raise FormalCaptureCliError("formal capture API response is invalid")
    return result

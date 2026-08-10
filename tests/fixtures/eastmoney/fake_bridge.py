"""Deterministic NDJSON child used by bridge lifecycle tests."""

import hashlib
import json
import sys
import time
from datetime import UTC, datetime

CONTRACT_VERSION = "astraquant.eastmoney-bridge/v1"
SERIALIZATION_VERSION = "astraquant.sdk-object-json/v1"
permission_tier = "legacy-unverified"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.casefold() in {"token", "secret"} else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def observed_schema(value: object) -> dict[str, object]:
    if isinstance(value, list):
        fields = sorted({str(key) for item in value if isinstance(item, dict) for key in item})
        return {"kind": "list", "fields": fields}
    if isinstance(value, dict):
        return {"kind": "object", "fields": sorted(value)}
    return {"kind": type(value).__name__, "fields": []}


def success(
    request: dict[str, object],
    result: object,
    *,
    permission: str,
    fault: str | None = None,
) -> None:
    evidence = {
        "request_digest": digest(redact(request)),
        "response_digest": digest(result),
        "representation": "SDK_OBJECT_CANONICAL",
        "serialization_version": SERIALIZATION_VERSION,
        "interface": "gm_python_sdk",
        "interface_build": "test-sdk-1.0",
        "permission_tier": permission,
        "requested_at": request["requested_at"],
        "received_at": datetime.now(UTC).isoformat(),
        "observed_schema": observed_schema(result),
    }
    response_version = CONTRACT_VERSION
    if fault == "wrong_version":
        response_version = "astraquant.eastmoney-bridge/v999"
    if fault == "unknown_representation":
        evidence["representation"] = "BRIDGE_JSON_PRETENDING_RAW"
    if fault == "bad_digest":
        evidence["response_digest"] = f"sha256:{'0' * 64}"
    respond(
        {
            "contract_version": response_version,
            "id": request["id"],
            "ok": True,
            "result": result,
            "evidence": evidence,
        }
    )


def respond(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    request = json.loads(line)
    request_id = request["id"]
    method = request["method"]
    params = request.get("params", {})

    if method == "shutdown":
        success(request, None, permission=permission_tier)
        break
    if method == "configure":
        permission_tier = params.get("permission_tier", "legacy-unverified")
        success(request, {"configured": True}, permission=permission_tier)
        continue
    if method == "current":
        symbols = params.get("symbols", [])
        if symbols == ["TEST.TIMEOUT"]:
            time.sleep(1)
        if symbols == ["TEST.MALFORMED"]:
            sys.stdout.write("not-json\n")
            sys.stdout.flush()
            continue
        if symbols == ["TEST.WRONG_ID"]:
            respond({"id": "wrong", "ok": True, "result": []})
            continue
        if symbols == ["TEST.EXIT"]:
            raise SystemExit(7)
        fault_by_symbol = {
            "TEST.WRONG_VERSION": "wrong_version",
            "TEST.UNKNOWN_REPRESENTATION": "unknown_representation",
            "TEST.BAD_DIGEST": "bad_digest",
        }
        fault = fault_by_symbol.get(symbols[0]) if symbols else None
        success(
            request,
            [{"symbol": symbol, "price": 1} for symbol in symbols],
            permission=permission_tier,
            fault=fault,
        )
        continue
    if method == "history_n":
        success(request, [params], permission=permission_tier)
        continue
    if method == "history_range":
        page = params["page"]
        rows = [
            {
                "symbol": params["symbol"],
                "bob": page["start_at"],
            }
        ]
        success(
            request,
            {
                "rows": rows,
                "page": {
                    **page,
                    "frequency": params["frequency"],
                    "adjust": params["adjust"],
                    "units": params["units"],
                    "returned_count": len(rows),
                    "declared_total": None,
                },
            },
            permission=permission_tier,
        )
        continue
    success(request, params, permission=permission_tier)

"""Isolated stdin/stdout bridge for the Eastmoney ``gm`` SDK."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, TextIO, cast

with contextlib.redirect_stdout(sys.stderr):
    from gm import api as gm  # type: ignore[import-not-found]

PROTOCOL_STDOUT = cast(TextIO, sys.__stdout__)
if PROTOCOL_STDOUT is None:
    raise RuntimeError("protocol stdout is unavailable")

_SYMBOL_CATALOG: list[dict[str, Any]] | None = None
_SEARCH_LIMIT = 20
_CONTRACT_VERSION = "astraquant.eastmoney-bridge/v1"
_SERIALIZATION_VERSION = "astraquant.sdk-object-json/v1"
_PERMISSION_TIER = "legacy-unverified"


def sdk_build() -> str:
    for distribution in ("gm", "gm-python-sdk"):
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "unknown-build"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if str(key).casefold() in {"token", "secret"} else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def observed_schema(value: object) -> dict[str, object]:
    if isinstance(value, list):
        fields = sorted({str(key) for item in value if isinstance(item, dict) for key in item})
        field_types = {
            field: sorted(
                {
                    type(item[field]).__name__
                    for item in value
                    if isinstance(item, dict) and field in item and item[field] is not None
                }
            )
            for field in fields
        }
        return {"kind": "list", "fields": fields, "field_types": field_types}
    if isinstance(value, dict):
        fields = sorted(str(key) for key in value)
        return {
            "kind": "object",
            "fields": fields,
            "field_types": {field: [type(value[field]).__name__] for field in fields},
        }
    return {"kind": type(value).__name__, "fields": [], "field_types": {}}


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().isoformat()
    if hasattr(value, "to_dict"):
        try:
            return json_safe(value.to_dict("records"))
        except TypeError:
            return json_safe(value.to_dict())
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)


def invoke(method: str, params: dict[str, Any]) -> Any:
    global _PERMISSION_TIER
    with contextlib.redirect_stdout(sys.stderr):
        if method == "configure":
            gm.set_token(params["token"])
            _PERMISSION_TIER = str(params.get("permission_tier", "legacy-unverified"))
            return {"configured": True}
        if method == "current":
            return gm.current(symbols=params["symbols"])
        if method == "history_n":
            adjust = int(params.get("adjust", gm.ADJUST_NONE))
            if adjust not in (gm.ADJUST_NONE, gm.ADJUST_PREV, gm.ADJUST_POST):
                raise ValueError("unsupported_adjustment")
            return gm.history_n(
                symbol=params["symbol"],
                frequency=params["frequency"],
                count=params["count"],
                adjust=adjust,
                df=True,
            )
        if method == "history_range":
            adjust = int(params.get("adjust", gm.ADJUST_NONE))
            if adjust not in (gm.ADJUST_NONE, gm.ADJUST_PREV, gm.ADJUST_POST):
                raise ValueError("unsupported_adjustment")
            page = params["page"]
            rows = json_safe(
                gm.history(
                    symbol=params["symbol"],
                    frequency=params["frequency"],
                    start_time=page["start_at"],
                    end_time=page["end_at"],
                    adjust=adjust,
                    df=True,
                )
            )
            if not isinstance(rows, list):
                raise ValueError("history_range_not_a_record_list")
            return {
                "rows": rows,
                "page": {
                    **page,
                    "frequency": params["frequency"],
                    "adjust": adjust,
                    "units": params["units"],
                    "returned_count": len(rows),
                    "declared_total": None,
                },
            }
        if method == "search_symbols":
            return search_symbols(str(params["query"]))
        if method == "trading_dates":
            return gm.get_trading_dates(
                exchange=params["exchange"],
                start_date=params["start_date"],
                end_date=params["end_date"],
            )
        if method == "stock_instruments":
            return gm.get_instrumentinfos(
                sec_types=[gm.SEC_TYPE_STOCK],
                exchanges=["SHSE", "SZSE", "BSE"],
                df=False,
            )
    raise ValueError("unsupported_method")


def search_symbols(query: str) -> list[dict[str, Any]]:
    global _SYMBOL_CATALOG
    if _SYMBOL_CATALOG is None:
        catalog: list[dict[str, Any]] = []
        for security_types, exchanges in (
            (
                [gm.SEC_TYPE_STOCK, gm.SEC_TYPE_FUND],
                ["SHSE", "SZSE", "BSE"],
            ),
            (
                [gm.SEC_TYPE_FUTURE],
                ["CFFEX", "SHFE", "DCE", "CZCE", "INE", "GFEX"],
            ),
        ):
            rows = gm.get_instrumentinfos(
                sec_types=security_types,
                exchanges=exchanges,
                df=False,
            )
            catalog.extend(row for row in rows if isinstance(row, dict))
        _SYMBOL_CATALOG = catalog

    normalized = query.strip().casefold()
    if not normalized:
        return []
    matches = [
        row
        for row in _SYMBOL_CATALOG
        if normalized in str(row.get("symbol", "")).casefold()
        or normalized in str(row.get("sec_name", "")).casefold()
    ]
    return matches[:_SEARCH_LIMIT]


def respond(payload: dict[str, Any]) -> None:
    PROTOCOL_STDOUT.write(json.dumps(json_safe(payload), separators=(",", ":")) + "\n")
    PROTOCOL_STDOUT.flush()


def respond_success(request: dict[str, Any], result: object) -> None:
    safe_result = json_safe(result)
    requested_at = request["requested_at"]
    respond(
        {
            "contract_version": _CONTRACT_VERSION,
            "id": request["id"],
            "ok": True,
            "result": safe_result,
            "evidence": {
                "request_digest": digest(redact(request)),
                "response_digest": digest(safe_result),
                "canonical_request": redact(request),
                "attempt": 1,
                "retry_of_request_digest": None,
                "representation": "SDK_OBJECT_CANONICAL",
                "serialization_version": _SERIALIZATION_VERSION,
                "interface": "gm_python_sdk",
                "interface_build": sdk_build(),
                "permission_tier": _PERMISSION_TIER,
                "requested_at": requested_at,
                "received_at": datetime.now(UTC).isoformat(),
                "observed_schema": observed_schema(safe_result),
            },
        }
    )


def main() -> None:
    for line in sys.stdin:
        request_id: object = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            if request.get("contract_version") != _CONTRACT_VERSION:
                raise ValueError("unsupported_contract_version")
            requested_at = datetime.fromisoformat(str(request.get("requested_at")))
            if requested_at.tzinfo is None or requested_at.utcoffset() is None:
                raise ValueError("requested_at_not_timezone_aware")
            method = request.get("method")
            params = request.get("params", {})
            if method == "shutdown":
                respond_success(request, None)
                return
            result = invoke(str(method), params)
            respond_success(request, result)
        except Exception:
            respond(
                {
                    "contract_version": _CONTRACT_VERSION,
                    "id": request_id,
                    "ok": False,
                    "error": {"code": "gm_call_failed", "message": "Eastmoney SDK call failed"},
                }
            )


if __name__ == "__main__":
    main()

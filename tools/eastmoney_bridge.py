"""Isolated stdin/stdout bridge for the Eastmoney ``gm`` SDK."""

from __future__ import annotations

import contextlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TextIO, cast

with contextlib.redirect_stdout(sys.stderr):
    from gm import api as gm  # type: ignore[import-not-found]

PROTOCOL_STDOUT = cast(TextIO, sys.__stdout__)
if PROTOCOL_STDOUT is None:
    raise RuntimeError("protocol stdout is unavailable")

_SYMBOL_CATALOG: list[dict[str, Any]] | None = None
_SEARCH_LIMIT = 20


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
    with contextlib.redirect_stdout(sys.stderr):
        if method == "configure":
            gm.set_token(params["token"])
            return {"configured": True}
        if method == "current":
            return gm.current(symbols=params["symbols"])
        if method == "history_n":
            return gm.history_n(
                symbol=params["symbol"],
                frequency=params["frequency"],
                count=params["count"],
                df=True,
            )
        if method == "search_symbols":
            return search_symbols(str(params["query"]))
        if method == "trading_dates":
            return gm.get_trading_dates(
                exchange=params["exchange"],
                start_date=params["start_date"],
                end_date=params["end_date"],
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


def main() -> None:
    for line in sys.stdin:
        request_id: object = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            if method == "shutdown":
                respond({"id": request_id, "ok": True, "result": None})
                return
            result = invoke(str(method), params)
            respond({"id": request_id, "ok": True, "result": result})
        except Exception:
            respond(
                {
                    "id": request_id,
                    "ok": False,
                    "error": {"code": "gm_call_failed", "message": "Eastmoney SDK call failed"},
                }
            )


if __name__ == "__main__":
    main()

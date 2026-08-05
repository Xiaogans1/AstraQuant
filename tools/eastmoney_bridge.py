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
        if method == "symbol_infos":
            return gm.get_symbol_infos(symbols=params["symbols"], df=True)
        if method == "trading_dates":
            return gm.get_trading_dates(
                exchange=params["exchange"],
                start_date=params["start_date"],
                end_date=params["end_date"],
            )
    raise ValueError("unsupported_method")


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

"""Deterministic NDJSON child used by bridge lifecycle tests."""

import json
import sys
import time


def respond(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    request = json.loads(line)
    request_id = request["id"]
    method = request["method"]
    params = request.get("params", {})

    if method == "shutdown":
        respond({"id": request_id, "ok": True, "result": None})
        break
    if method == "configure":
        respond({"id": request_id, "ok": True, "result": {"configured": True}})
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
        respond(
            {
                "id": request_id,
                "ok": True,
                "result": [{"symbol": symbol, "price": 1} for symbol in symbols],
            }
        )
        continue
    respond({"id": request_id, "ok": True, "result": params})

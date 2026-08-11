from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from tools.data.backfill_eastmoney import main as backfill_main
from tools.data.increment_eastmoney import main as increment_main


class _Handler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, object]]] = []

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.__class__.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "idempotency_key": self.headers.get("Idempotency-Key"),
                "body": json.loads(body),
            }
        )
        response = json.dumps(
            {
                "task_id": "task-1",
                "task_type": "data.formal_capture",
                "status": "RUNNING",
                "progress": 0,
                "current_step": "started",
                "correlation_id": "correlation-1",
                "worker_pid": 42,
                "created_at": "2026-08-11T00:00:00+00:00",
                "started_at": "2026-08-11T00:00:00+00:00",
                "finished_at": None,
                "result": None,
                "error_code": None,
                "error_message": None,
                "revision": 1,
            }
        ).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.fixture
def api_server() -> Iterator[tuple[str, list[dict[str, object]]]]:
    _Handler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", _Handler.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_backfill_posts_exact_authenticated_formal_request_without_secret_output(
    api_server: tuple[str, list[dict[str, object]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    api_url, requests = api_server

    exit_code = backfill_main(
        [
            "--api-url",
            api_url,
            "--idempotency-key",
            "formal-backfill-600000-20260811",
            "--approval-id",
            "sha256:" + "1" * 64,
            "--instrument-id",
            "600000.SSE",
            "--frequency",
            "1d",
            "--start",
            "2026-08-10",
            "--end",
            "2026-08-11",
            "--adjustment",
            "none",
        ],
        environ={"ASTRAQUANT_SESSION_TOKEN": "private-session-token"},
    )

    assert exit_code == 0
    assert requests == [
        {
            "path": "/v1/formal-data/captures",
            "authorization": "Bearer private-session-token",
            "idempotency_key": "formal-backfill-600000-20260811",
            "body": {
                "approval_id": "sha256:" + "1" * 64,
                "instrument_id": "600000.SSE",
                "frequency": "1d",
                "start": "2026-08-10",
                "end": "2026-08-11",
                "adjustment": "none",
            },
        }
    ]
    output = capsys.readouterr().out
    assert "task-1" in output
    assert "private-session-token" not in output


def test_formal_capture_cli_source_has_no_database_sdk_or_direct_store_write() -> None:
    sources = "\n".join(
        Path(path).read_text(encoding="utf-8").casefold()
        for path in (
            "tools/data/formal_capture_cli.py",
            "tools/data/backfill_eastmoney.py",
            "tools/data/increment_eastmoney.py",
        )
    )

    assert "sqlalchemy" not in sources
    assert "eastmoneybridgeclient" not in sources
    assert "capturestore" not in sources
    assert "sqlite" not in sources


def test_increment_posts_only_exact_sealed_predecessor_and_end(
    api_server: tuple[str, list[dict[str, object]]],
) -> None:
    api_url, requests = api_server
    capture_id = "sha256:" + "9" * 64

    exit_code = increment_main(
        [
            "--api-url",
            api_url,
            "--idempotency-key",
            "formal-increment-600000-20260814",
            "--predecessor-capture-id",
            capture_id,
            "--end",
            "2026-08-14",
        ],
        environ={"ASTRAQUANT_SESSION_TOKEN": "private-session-token"},
    )

    assert exit_code == 0
    assert requests[-1]["path"] == "/v1/formal-data/captures/increment"
    assert requests[-1]["body"] == {
        "predecessor_capture_id": capture_id,
        "end": "2026-08-14",
    }

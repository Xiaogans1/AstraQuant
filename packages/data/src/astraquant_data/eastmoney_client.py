"""Supervised NDJSON client for an isolated Eastmoney SDK interpreter."""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import subprocess
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self

LOGGER = logging.getLogger(__name__)


class EastmoneyBridgeError(RuntimeError):
    """Base class for sanitized bridge failures."""


class EastmoneyBridgeTimeout(EastmoneyBridgeError):
    pass


class EastmoneyBridgeExited(EastmoneyBridgeError):
    pass


class EastmoneyBridgeProtocolError(EastmoneyBridgeError):
    pass


class EastmoneyBridgeCallError(EastmoneyBridgeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Eastmoney bridge call failed: {code}")


class EastmoneyBridgeClient:
    """Own one SDK subprocess and permit one correlated request at a time."""

    def __init__(
        self,
        *,
        python_executable: Path,
        bridge_script: Path,
        timeout_seconds: float = 8,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.python_executable = python_executable
        self.bridge_script = bridge_script
        self.timeout_seconds = timeout_seconds
        self.command = (
            str(python_executable),
            "-I",
            "-u",
            str(bridge_script),
        )
        self._process: subprocess.Popen[str] | None = None
        self._stdout: queue.Queue[str | None] = queue.Queue()
        self._request_lock = threading.Lock()
        self._request_id = 0
        self._secrets: set[str] = set()

    @property
    def last_request_id(self) -> int:
        return self._request_id

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self._stdout = queue.Queue()
        self._process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            with contextlib.suppress(EastmoneyBridgeError):
                self._request("shutdown", {}, timeout_seconds=min(self.timeout_seconds, 1))
        self._terminate()
        self._process = None
        self._secrets.clear()

    def configure(self, token: str) -> None:
        normalized = token.strip()
        if not normalized:
            raise ValueError("token must not be blank")
        self._secrets.add(normalized)
        self._request("configure", {"token": normalized})

    def current(self, symbols: Sequence[str]) -> list[dict[str, Any]]:
        return self._list_result(self._request("current", {"symbols": list(symbols)}))

    def history_n(self, *, symbol: str, frequency: str, count: int) -> list[dict[str, Any]]:
        return self._list_result(
            self._request(
                "history_n",
                {"symbol": symbol, "frequency": frequency, "count": count},
            )
        )

    def search_symbols(self, query: str) -> list[dict[str, Any]]:
        return self._list_result(self._request("search_symbols", {"query": query}))

    def trading_dates(self, *, exchange: str, start_date: str, end_date: str) -> list[Any]:
        result = self._request(
            "trading_dates",
            {"exchange": exchange, "start_date": start_date, "end_date": end_date},
        )
        if not isinstance(result, list):
            raise EastmoneyBridgeProtocolError("Bridge result must be a list")
        return result

    @staticmethod
    def _list_result(result: object) -> list[dict[str, Any]]:
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise EastmoneyBridgeProtocolError("Bridge result must be a list of objects")
        return result

    def _request(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> object:
        with self._request_lock:
            process = self._running_process()
            self._request_id += 1
            request_id = str(self._request_id)
            request = {"id": request_id, "method": method, "params": dict(params)}
            assert process.stdin is not None
            try:
                process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                raise EastmoneyBridgeExited("Eastmoney bridge exited") from error
            try:
                line = self._stdout.get(timeout=timeout_seconds or self.timeout_seconds)
            except queue.Empty as error:
                self._terminate()
                raise EastmoneyBridgeTimeout("Eastmoney bridge request timed out") from error
            if line is None:
                raise EastmoneyBridgeExited("Eastmoney bridge exited")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as error:
                raise EastmoneyBridgeProtocolError("Bridge returned malformed JSON") from error
            if not isinstance(response, dict) or response.get("id") != request_id:
                raise EastmoneyBridgeProtocolError("Bridge response id does not match request")
            if response.get("ok") is not True:
                raw_error = response.get("error")
                code = raw_error.get("code") if isinstance(raw_error, dict) else "unknown"
                raise EastmoneyBridgeCallError(str(code))
            return response.get("result")

    def _running_process(self) -> subprocess.Popen[str]:
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError("Eastmoney bridge is not running")
        return self._process

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self._stdout.put(line)
        self._stdout.put(None)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            message = line.rstrip()
            for secret in self._secrets:
                message = message.replace(secret, "[REDACTED]")
            if message:
                LOGGER.debug("Eastmoney bridge: %s", message)

    def _terminate(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)

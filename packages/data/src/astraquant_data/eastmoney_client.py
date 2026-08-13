"""Supervised NDJSON client for an isolated Eastmoney SDK interpreter."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import queue
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

from .eastmoney_protocol import (
    HistoryBatch,
    HistoryPage,
    HistoryPageEvidence,
    HistoryPageSpec,
    validate_history_pages,
)

LOGGER = logging.getLogger(__name__)
BRIDGE_CONTRACT_VERSION = "astraquant.eastmoney-bridge/v1"
SDK_OBJECT_SERIALIZATION_VERSION = "astraquant.sdk-object-json/v1"


class BridgeResponseRepresentation(StrEnum):
    PROVIDER_RAW_BYTES = "PROVIDER_RAW_BYTES"
    SDK_OBJECT_CANONICAL = "SDK_OBJECT_CANONICAL"


def _aware_utc(name: str, value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class BridgeCallEvidence:
    request_digest: str
    response_digest: str
    canonical_request: dict[str, object]
    attempt: int
    retry_of_request_digest: str | None
    representation: BridgeResponseRepresentation
    serialization_version: str
    interface: str
    interface_build: str
    permission_tier: str
    requested_at: datetime
    received_at: datetime
    observed_schema: dict[str, object]

    @classmethod
    def from_dict(cls, value: object) -> BridgeCallEvidence:
        if not isinstance(value, dict):
            raise ValueError("evidence must be an object")
        try:
            representation = BridgeResponseRepresentation(value["representation"])
            evidence = cls(
                request_digest=validate_digest("request_digest", str(value["request_digest"])),
                response_digest=validate_digest("response_digest", str(value["response_digest"])),
                canonical_request=dict(value["canonical_request"]),
                attempt=int(value["attempt"]),
                retry_of_request_digest=(
                    None
                    if value.get("retry_of_request_digest") is None
                    else validate_digest(
                        "retry_of_request_digest",
                        str(value["retry_of_request_digest"]),
                    )
                ),
                representation=representation,
                serialization_version=str(value["serialization_version"]),
                interface=str(value["interface"]),
                interface_build=str(value["interface_build"]),
                permission_tier=str(value["permission_tier"]),
                requested_at=_aware_utc("requested_at", value["requested_at"]),
                received_at=_aware_utc("received_at", value["received_at"]),
                observed_schema=dict(value["observed_schema"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid bridge evidence") from error
        if evidence.representation is not BridgeResponseRepresentation.SDK_OBJECT_CANONICAL:
            raise ValueError("unsupported response representation")
        if evidence.serialization_version != SDK_OBJECT_SERIALIZATION_VERSION:
            raise ValueError("unsupported SDK object serialization")
        if evidence.interface != "gm_python_sdk":
            raise ValueError("unsupported bridge interface")
        for name in ("interface_build", "permission_tier"):
            text = getattr(evidence, name)
            if not text or text != text.strip():
                raise ValueError(f"{name} must be non-empty canonical text")
        if evidence.received_at < evidence.requested_at:
            raise ValueError("received_at cannot precede requested_at")
        if evidence.attempt <= 0:
            raise ValueError("attempt must be positive")
        if not evidence.canonical_request:
            raise ValueError("canonical_request must not be empty")
        if not evidence.observed_schema:
            raise ValueError("observed_schema must not be empty")
        return evidence

    def to_dict(self) -> dict[str, object]:
        return {
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "canonical_request": self.canonical_request,
            "attempt": self.attempt,
            "retry_of_request_digest": self.retry_of_request_digest,
            "representation": self.representation.value,
            "serialization_version": self.serialization_version,
            "interface": self.interface,
            "interface_build": self.interface_build,
            "permission_tier": self.permission_tier,
            "requested_at": self.requested_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "observed_schema": self.observed_schema,
        }


@dataclass(frozen=True, slots=True)
class BridgeResponse:
    result: object
    evidence: BridgeCallEvidence


@dataclass(frozen=True, slots=True)
class HistoryCall:
    page: HistoryPage
    response: BridgeResponse


@dataclass(frozen=True, slots=True)
class HistoryRangeCapture:
    batch: HistoryBatch
    calls: tuple[HistoryCall, ...]


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _redact_request(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if str(key).casefold() in {"token", "secret"}
                else _redact_request(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_request(item) for item in value]
    return value


def _row_schema_digest(rows: Sequence[Mapping[str, object]]) -> str:
    fields = sorted({str(key) for row in rows for key in row})
    value_types = {
        str(key): sorted(
            {type(row[key]).__name__ for row in rows if key in row and row[key] is not None}
        )
        for key in fields
    }
    return _digest({"fields": fields, "types": value_types})


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

    def configure(self, token: str, *, permission_tier: str = "legacy-unverified") -> None:
        normalized = token.strip()
        if not normalized:
            raise ValueError("token must not be blank")
        if not permission_tier or permission_tier != permission_tier.strip():
            raise ValueError("permission_tier must be non-empty canonical text")
        self._secrets.add(normalized)
        self._request(
            "configure",
            {"token": normalized, "permission_tier": permission_tier},
        )

    def current(self, symbols: Sequence[str]) -> list[dict[str, Any]]:
        return self._list_result(self._request("current", {"symbols": list(symbols)}))

    def current_with_evidence(self, symbols: Sequence[str]) -> BridgeResponse:
        response = self._request_response("current", {"symbols": list(symbols)})
        self._list_result(response.result)
        return response

    def stock_instruments_with_evidence(self) -> BridgeResponse:
        """Return the complete exchange stock catalog and immutable call evidence."""

        response = self._request_response("stock_instruments", {})
        self._list_result(response.result)
        return response

    def history_n(
        self,
        *,
        symbol: str,
        frequency: str,
        count: int,
        adjust: int = 0,
    ) -> list[dict[str, Any]]:
        if adjust not in (0, 1, 2):
            raise ValueError("adjust must be 0, 1 or 2")
        return self._list_result(
            self._request(
                "history_n",
                {
                    "symbol": symbol,
                    "frequency": frequency,
                    "count": count,
                    "adjust": adjust,
                },
            )
        )

    def history_range(
        self,
        *,
        symbol: str,
        frequency: str,
        pages: Sequence[HistoryPageSpec],
        adjust: int = 0,
        units: tuple[str, ...] = ("price=CNY", "volume=share"),
        expected_total: int | None = None,
    ) -> HistoryBatch:
        return self.history_range_with_evidence(
            symbol=symbol,
            frequency=frequency,
            pages=pages,
            adjust=adjust,
            units=units,
            expected_total=expected_total,
        ).batch

    def history_range_with_evidence(
        self,
        *,
        symbol: str,
        frequency: str,
        pages: Sequence[HistoryPageSpec],
        adjust: int = 0,
        units: tuple[str, ...] = ("price=CNY", "volume=share"),
        expected_total: int | None = None,
    ) -> HistoryRangeCapture:
        if not symbol or symbol != symbol.strip():
            raise ValueError("symbol must be non-empty canonical text")
        if not frequency or frequency != frequency.strip():
            raise ValueError("frequency must be non-empty canonical text")
        if adjust not in (0, 1, 2):
            raise ValueError("adjust must be 0, 1 or 2")
        expected_specs = tuple(pages)
        calls = tuple(
            self.history_page_with_evidence(
                symbol=symbol,
                frequency=frequency,
                page=spec,
                adjust=adjust,
                units=units,
            )
            for spec in expected_specs
        )
        batch = validate_history_pages(
            tuple(call.page for call in calls),
            expected_specs=expected_specs,
            expected_total=expected_total,
        )
        return HistoryRangeCapture(batch=batch, calls=calls)

    def history_page_with_evidence(
        self,
        *,
        symbol: str,
        frequency: str,
        page: HistoryPageSpec,
        adjust: int = 0,
        units: tuple[str, ...] = ("price=CNY", "volume=share"),
    ) -> HistoryCall:
        if not symbol or symbol != symbol.strip():
            raise ValueError("symbol must be non-empty canonical text")
        if not frequency or frequency != frequency.strip():
            raise ValueError("frequency must be non-empty canonical text")
        if adjust not in (0, 1, 2):
            raise ValueError("adjust must be 0, 1 or 2")
        response = self._request_response(
            "history_range",
            {
                "symbol": symbol,
                "frequency": frequency,
                "adjust": adjust,
                "units": list(units),
                "page": {
                    "index": page.index,
                    "page_count": page.page_count,
                    "cursor": page.cursor,
                    "start_at": page.start_at.isoformat(),
                    "end_at": page.end_at.isoformat(),
                },
            },
        )
        parsed = self._history_page(response)
        if parsed.evidence.spec != page:
            raise EastmoneyBridgeProtocolError("History page does not match request")
        return HistoryCall(page=parsed, response=response)

    @staticmethod
    def _history_page(response: BridgeResponse) -> HistoryPage:
        if not isinstance(response.result, dict):
            raise EastmoneyBridgeProtocolError("History result must be an object")
        raw_rows = response.result.get("rows")
        raw_page = response.result.get("page")
        if not isinstance(raw_rows, list) or not all(isinstance(row, dict) for row in raw_rows):
            raise EastmoneyBridgeProtocolError("History rows must be objects")
        if not isinstance(raw_page, dict):
            raise EastmoneyBridgeProtocolError("History page evidence must be an object")
        try:
            spec = HistoryPageSpec(
                index=int(raw_page["index"]),
                page_count=int(raw_page["page_count"]),
                cursor=str(raw_page["cursor"]),
                start_at=datetime.fromisoformat(str(raw_page["start_at"])),
                end_at=datetime.fromisoformat(str(raw_page["end_at"])),
            )
            declared_raw = raw_page.get("declared_total")
            raw_units = raw_page["units"]
            if not isinstance(raw_units, list):
                raise ValueError("units must be a list")
            rows = tuple(dict(row) for row in raw_rows)
            evidence = HistoryPageEvidence(
                spec=spec,
                returned_count=int(raw_page["returned_count"]),
                declared_total=(None if declared_raw is None else int(declared_raw)),
                frequency=str(raw_page["frequency"]),
                adjust=int(raw_page["adjust"]),
                units=tuple(str(unit) for unit in raw_units),
                schema_digest=_row_schema_digest(rows),
                request_digest=response.evidence.request_digest,
                response_digest=response.evidence.response_digest,
            )
            return HistoryPage(rows=rows, evidence=evidence)
        except (KeyError, TypeError, ValueError) as error:
            raise EastmoneyBridgeProtocolError("History page evidence is invalid") from error

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
        return self._request_response(
            method,
            params,
            timeout_seconds=timeout_seconds,
        ).result

    def _request_response(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> BridgeResponse:
        with self._request_lock:
            process = self._running_process()
            self._request_id += 1
            request_id = str(self._request_id)
            request = {
                "contract_version": BRIDGE_CONTRACT_VERSION,
                "id": request_id,
                "method": method,
                "params": dict(params),
                "requested_at": datetime.now(UTC).isoformat(),
            }
            expected_request_digest = _digest(_redact_request(request))
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
            if response.get("contract_version") != BRIDGE_CONTRACT_VERSION:
                raise EastmoneyBridgeProtocolError("Bridge contract version does not match")
            if response.get("ok") is not True:
                raw_error = response.get("error")
                code = raw_error.get("code") if isinstance(raw_error, dict) else "unknown"
                raise EastmoneyBridgeCallError(str(code))
            result = response.get("result")
            try:
                evidence = BridgeCallEvidence.from_dict(response.get("evidence"))
            except ValueError as error:
                raise EastmoneyBridgeProtocolError("Bridge evidence is invalid") from error
            if evidence.request_digest != expected_request_digest:
                raise EastmoneyBridgeProtocolError("Bridge request digest does not match")
            if evidence.canonical_request != _redact_request(request):
                raise EastmoneyBridgeProtocolError("Bridge canonical request does not match")
            if evidence.response_digest != _digest(result):
                raise EastmoneyBridgeProtocolError("Bridge response digest does not match")
            return BridgeResponse(result=result, evidence=evidence)

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

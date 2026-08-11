"""Immutable raw provider capture contracts."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

from .eastmoney_client import BridgeResponseRepresentation

CAPTURE_PLAN_SCHEMA = "astraquant.capture-plan/v1"
CAPTURE_CHUNK_SCHEMA = "astraquant.capture-chunk/v1"
CAPTURE_ENVELOPE_SCHEMA = "astraquant.capture-envelope/v1"
_SECRET_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "password",
        "secret",
        "session_token",
        "token",
    }
)


class CaptureStatus(StrEnum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    QUARANTINED = "QUARANTINED"


class CapturePurpose(StrEnum):
    QUALIFICATION_PROBE = "QUALIFICATION_PROBE"
    FORMAL_DATA = "FORMAL_DATA"


class SecretMaterialError(ValueError):
    """Raised when persisted evidence contains a secret-like field."""


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _utc(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _canonical_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty canonical text")
    return value


def _scan_secret_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in _SECRET_KEYS:
                raise SecretMaterialError("capture contains a secret-like field")
            _scan_secret_keys(item)
    elif isinstance(value, list):
        for item in value:
            _scan_secret_keys(item)


def _validated_json_bytes(name: str, value: bytes) -> bytes:
    if not isinstance(value, bytes) or not value:
        raise ValueError(f"{name} must be non-empty bytes")
    try:
        parsed = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{name} must contain UTF-8 JSON") from error
    _scan_secret_keys(parsed)
    return value


def _schema(value: Mapping[str, object]) -> Mapping[str, object]:
    if not value:
        raise ValueError("schema must not be empty")
    canonical = json.loads(canonical_json_bytes(value))
    if not isinstance(canonical, dict):  # pragma: no cover - Mapping always serializes as object
        raise ValueError("schema must be an object")
    return MappingProxyType(canonical)


@dataclass(frozen=True, slots=True)
class CapturePlan:
    identity_digest: str
    report_digest: str | None
    approval_id: str | None
    endpoint: str
    expected_chunk_count: int
    expected_row_count: int
    coverage_proof_digest: str
    started_at: datetime
    purpose: CapturePurpose = CapturePurpose.FORMAL_DATA
    command_digest: str | None = None
    predecessor_capture_id: str | None = None
    schema_version: str = CAPTURE_PLAN_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identity_digest",
            validate_digest("identity_digest", self.identity_digest),
        )
        if not isinstance(self.purpose, CapturePurpose):
            raise ValueError("purpose must be a known CapturePurpose")
        if self.purpose is CapturePurpose.FORMAL_DATA:
            if self.report_digest is None or self.approval_id is None:
                raise ValueError("formal capture requires exact report and approval")
        elif self.report_digest is not None or self.approval_id is not None:
            raise ValueError("qualification probe cannot claim report or approval")
        for name in ("report_digest", "approval_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, validate_digest(name, value))
        object.__setattr__(self, "endpoint", _canonical_text("endpoint", self.endpoint))
        if self.expected_chunk_count <= 0:
            raise ValueError("expected_chunk_count must be positive")
        if self.expected_row_count < 0:
            raise ValueError("expected_row_count must be non-negative")
        object.__setattr__(
            self,
            "coverage_proof_digest",
            validate_digest("coverage_proof_digest", self.coverage_proof_digest),
        )
        object.__setattr__(self, "started_at", _utc("started_at", self.started_at))
        for name in ("command_digest", "predecessor_capture_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, validate_digest(name, value))
        if self.predecessor_capture_id is not None and self.command_digest is None:
            raise ValueError("predecessor capture requires a bound command digest")
        if self.schema_version != CAPTURE_PLAN_SCHEMA:
            raise ValueError("unsupported capture plan schema")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "identity_digest": self.identity_digest,
            "report_digest": self.report_digest,
            "approval_id": self.approval_id,
            "endpoint": self.endpoint,
            "expected_chunk_count": self.expected_chunk_count,
            "expected_row_count": self.expected_row_count,
            "coverage_proof_digest": self.coverage_proof_digest,
            "started_at": self.started_at.isoformat(),
            "purpose": self.purpose.value,
        }
        if self.command_digest is not None:
            value["command_digest"] = self.command_digest
        if self.predecessor_capture_id is not None:
            value["predecessor_capture_id"] = self.predecessor_capture_id
        return value

    @property
    def capture_id(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CapturePlan:
        try:
            return cls(
                identity_digest=str(value["identity_digest"]),
                report_digest=(
                    None if value["report_digest"] is None else str(value["report_digest"])
                ),
                approval_id=(None if value["approval_id"] is None else str(value["approval_id"])),
                endpoint=str(value["endpoint"]),
                expected_chunk_count=int(str(value["expected_chunk_count"])),
                expected_row_count=int(str(value["expected_row_count"])),
                coverage_proof_digest=str(value["coverage_proof_digest"]),
                started_at=datetime.fromisoformat(str(value["started_at"])),
                purpose=CapturePurpose(str(value["purpose"])),
                command_digest=(
                    None if value.get("command_digest") is None else str(value["command_digest"])
                ),
                predecessor_capture_id=(
                    None
                    if value.get("predecessor_capture_id") is None
                    else str(value["predecessor_capture_id"])
                ),
                schema_version=str(value["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid capture plan") from error


@dataclass(frozen=True, slots=True)
class CaptureChunk:
    sequence: int
    canonical_request: bytes
    canonical_response: bytes
    response_representation: BridgeResponseRepresentation
    requested_at: datetime
    received_at: datetime
    recorded_at: datetime
    serialization_version: str
    dtype: str
    schema: Mapping[str, object]
    units: tuple[str, ...]
    adjust: str
    page_cursor: str
    page_count: int
    returned_count: int
    declared_total: int | None
    attempt: int
    retry_of_request_digest: str | None
    schema_version: str = CAPTURE_CHUNK_SCHEMA

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        object.__setattr__(
            self,
            "canonical_request",
            _validated_json_bytes("canonical_request", self.canonical_request),
        )
        object.__setattr__(
            self,
            "canonical_response",
            _validated_json_bytes("canonical_response", self.canonical_response),
        )
        if not isinstance(self.response_representation, BridgeResponseRepresentation):
            raise ValueError("unknown response representation")
        for name in ("requested_at", "received_at", "recorded_at"):
            object.__setattr__(self, name, _utc(name, getattr(self, name)))
        if self.received_at < self.requested_at:
            raise ValueError("received_at cannot precede requested_at")
        if self.recorded_at < self.received_at:
            raise ValueError("recorded_at cannot precede received_at")
        for name in ("serialization_version", "dtype", "adjust", "page_cursor"):
            object.__setattr__(self, name, _canonical_text(name, getattr(self, name)))
        object.__setattr__(self, "schema", _schema(self.schema))
        units = tuple(sorted(self.units))
        if not units or len(units) != len(set(units)):
            raise ValueError("units must be non-empty and unique")
        if any(not item or item != item.strip() for item in units):
            raise ValueError("units must contain canonical text")
        object.__setattr__(self, "units", units)
        if self.page_count <= 0 or self.sequence >= self.page_count:
            raise ValueError("invalid page_count")
        if self.returned_count < 0:
            raise ValueError("returned_count must be non-negative")
        if self.declared_total is not None and self.declared_total < 0:
            raise ValueError("declared_total must be non-negative")
        if self.attempt <= 0:
            raise ValueError("attempt must be positive")
        if self.retry_of_request_digest is not None:
            object.__setattr__(
                self,
                "retry_of_request_digest",
                validate_digest("retry_of_request_digest", self.retry_of_request_digest),
            )
        if self.schema_version != CAPTURE_CHUNK_SCHEMA:
            raise ValueError("unsupported capture chunk schema")

    @property
    def request_digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_request).hexdigest()}"

    @property
    def response_digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_response).hexdigest()}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "canonical_request_b64": base64.b64encode(self.canonical_request).decode("ascii"),
            "canonical_response_b64": base64.b64encode(self.canonical_response).decode("ascii"),
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "response_representation": self.response_representation.value,
            "requested_at": self.requested_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "serialization_version": self.serialization_version,
            "dtype": self.dtype,
            "schema": dict(self.schema),
            "units": list(self.units),
            "adjust": self.adjust,
            "page_cursor": self.page_cursor,
            "page_count": self.page_count,
            "returned_count": self.returned_count,
            "declared_total": self.declared_total,
            "attempt": self.attempt,
            "retry_of_request_digest": self.retry_of_request_digest,
        }

    @property
    def chunk_id(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CaptureChunk:
        try:
            request = base64.b64decode(str(value["canonical_request_b64"]), validate=True)
            response = base64.b64decode(str(value["canonical_response_b64"]), validate=True)
            expected_request_digest = validate_digest(
                "request_digest", str(value["request_digest"])
            )
            expected_response_digest = validate_digest(
                "response_digest", str(value["response_digest"])
            )
            raw_schema = value["schema"]
            raw_units = value["units"]
            if not isinstance(raw_schema, Mapping) or not isinstance(raw_units, list):
                raise ValueError("invalid schema or units")
            chunk = cls(
                sequence=int(str(value["sequence"])),
                canonical_request=request,
                canonical_response=response,
                response_representation=BridgeResponseRepresentation(
                    str(value["response_representation"])
                ),
                requested_at=datetime.fromisoformat(str(value["requested_at"])),
                received_at=datetime.fromisoformat(str(value["received_at"])),
                recorded_at=datetime.fromisoformat(str(value["recorded_at"])),
                serialization_version=str(value["serialization_version"]),
                dtype=str(value["dtype"]),
                schema=dict(raw_schema),
                units=tuple(str(item) for item in raw_units),
                adjust=str(value["adjust"]),
                page_cursor=str(value["page_cursor"]),
                page_count=int(str(value["page_count"])),
                returned_count=int(str(value["returned_count"])),
                declared_total=(
                    None if value["declared_total"] is None else int(str(value["declared_total"]))
                ),
                attempt=int(str(value["attempt"])),
                retry_of_request_digest=(
                    None
                    if value["retry_of_request_digest"] is None
                    else str(value["retry_of_request_digest"])
                ),
                schema_version=str(value["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid capture chunk") from error
        if chunk.request_digest != expected_request_digest:
            raise ValueError("request digest does not match canonical bytes")
        if chunk.response_digest != expected_response_digest:
            raise ValueError("response digest does not match canonical bytes")
        return chunk


@dataclass(frozen=True, slots=True)
class CaptureEnvelope:
    plan: CapturePlan
    chunk_ids: tuple[str, ...]
    sealed_at: datetime
    status: CaptureStatus = CaptureStatus.SEALED
    schema_version: str = CAPTURE_ENVELOPE_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.plan, CapturePlan):
            raise ValueError("plan must be CapturePlan")
        chunk_ids = tuple(validate_digest("chunk_id", item) for item in self.chunk_ids)
        if len(chunk_ids) != self.plan.expected_chunk_count:
            raise ValueError("chunk count does not match capture plan")
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("chunk ids must be unique")
        object.__setattr__(self, "chunk_ids", chunk_ids)
        object.__setattr__(self, "sealed_at", _utc("sealed_at", self.sealed_at))
        if self.status is not CaptureStatus.SEALED:
            raise ValueError("capture envelope must be SEALED")
        if self.schema_version != CAPTURE_ENVELOPE_SCHEMA:
            raise ValueError("unsupported capture envelope schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "capture_id": self.plan.capture_id,
            "plan": self.plan.to_dict(),
            "chunk_ids": list(self.chunk_ids),
            "sealed_at": self.sealed_at.isoformat(),
        }

    @property
    def seal_digest(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CaptureEnvelope:
        try:
            raw_plan = value["plan"]
            raw_chunks = value["chunk_ids"]
            if not isinstance(raw_plan, Mapping) or not isinstance(raw_chunks, list):
                raise ValueError("invalid plan or chunk ids")
            envelope = cls(
                plan=CapturePlan.from_dict(raw_plan),
                chunk_ids=tuple(str(item) for item in raw_chunks),
                sealed_at=datetime.fromisoformat(str(value["sealed_at"])),
                status=CaptureStatus(str(value["status"])),
                schema_version=str(value["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid capture envelope") from error
        if value.get("capture_id") != envelope.plan.capture_id:
            raise ValueError("capture id does not match plan")
        return envelope

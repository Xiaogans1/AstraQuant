"""Deterministic comparison of two integrity-checked sealed captures."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from astraquant_data.capture import CaptureChunk, CaptureEnvelope
from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

CAPTURE_RECONCILIATION_SCHEMA = "astraquant.capture-reconciliation/v1"


class CaptureReconciliationStatus(StrEnum):
    MATCH = "MATCH"
    CONTENT_MISMATCH = "CONTENT_MISMATCH"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"


class CaptureReconciliationError(RuntimeError):
    pass


class CaptureReaderWriter(Protocol):
    def read(self, capture_id: str) -> CaptureEnvelope: ...

    def read_chunk(self, capture_id: str, chunk_id: str) -> CaptureChunk: ...

    def write_reconciliation(self, report: CaptureReconciliationReport) -> str: ...


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


@dataclass(frozen=True, slots=True)
class CaptureReconciliationReport:
    left_capture_id: str
    right_capture_id: str
    left_seal_digest: str
    right_seal_digest: str
    left_scope_digest: str
    right_scope_digest: str
    left_content_digest: str
    right_content_digest: str
    status: CaptureReconciliationStatus
    differences: tuple[str, ...]
    schema_version: str = CAPTURE_RECONCILIATION_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "left_capture_id",
            "right_capture_id",
            "left_seal_digest",
            "right_seal_digest",
            "left_scope_digest",
            "right_scope_digest",
            "left_content_digest",
            "right_content_digest",
        ):
            object.__setattr__(self, name, validate_digest(name, getattr(self, name)))
        if not isinstance(self.status, CaptureReconciliationStatus):
            raise ValueError("unknown capture reconciliation status")
        differences = tuple(sorted(set(self.differences)))
        if differences != self.differences or any(not item for item in differences):
            raise ValueError("differences must be sorted unique canonical labels")
        if self.status is CaptureReconciliationStatus.MATCH and differences:
            raise ValueError("matching captures cannot contain differences")
        if self.status is not CaptureReconciliationStatus.MATCH and not differences:
            raise ValueError("mismatching captures require differences")
        if self.schema_version != CAPTURE_RECONCILIATION_SCHEMA:
            raise ValueError("unsupported capture reconciliation schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "left_capture_id": self.left_capture_id,
            "right_capture_id": self.right_capture_id,
            "left_seal_digest": self.left_seal_digest,
            "right_seal_digest": self.right_seal_digest,
            "left_scope_digest": self.left_scope_digest,
            "right_scope_digest": self.right_scope_digest,
            "left_content_digest": self.left_content_digest,
            "right_content_digest": self.right_content_digest,
            "status": self.status.value,
            "differences": list(self.differences),
        }

    @property
    def report_digest(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CaptureReconciliationReport:
        try:
            raw_differences = value["differences"]
            if not isinstance(raw_differences, list):
                raise ValueError("differences must be a list")
            return cls(
                left_capture_id=str(value["left_capture_id"]),
                right_capture_id=str(value["right_capture_id"]),
                left_seal_digest=str(value["left_seal_digest"]),
                right_seal_digest=str(value["right_seal_digest"]),
                left_scope_digest=str(value["left_scope_digest"]),
                right_scope_digest=str(value["right_scope_digest"]),
                left_content_digest=str(value["left_content_digest"]),
                right_content_digest=str(value["right_content_digest"]),
                status=CaptureReconciliationStatus(str(value["status"])),
                differences=tuple(str(item) for item in raw_differences),
                schema_version=str(value["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid capture reconciliation report") from error


def reconcile_captures(
    store: CaptureReaderWriter,
    left_capture_id: str,
    right_capture_id: str,
) -> CaptureReconciliationReport:
    left = _capture_projection(store, left_capture_id)
    right = _capture_projection(store, right_capture_id)
    differences = tuple(
        name
        for name, left_value, right_value in (
            ("IDENTITY", left.identity_digest, right.identity_digest),
            ("REPORT", left.report_digest, right.report_digest),
            ("APPROVAL", left.approval_id, right.approval_id),
            ("ENDPOINT", left.endpoint, right.endpoint),
            ("COVERAGE", left.coverage, right.coverage),
            ("REQUEST_SCOPE", left.request_scope, right.request_scope),
            ("SCHEMA", left.schemas, right.schemas),
            ("UNITS", left.units, right.units),
            ("ADJUSTMENT", left.adjustments, right.adjustments),
            ("ROW_COUNT", left.row_counts, right.row_counts),
            ("CONTENT", left.content, right.content),
        )
        if left_value != right_value
    )
    scope_labels = frozenset(
        {
            "IDENTITY",
            "REPORT",
            "APPROVAL",
            "ENDPOINT",
            "COVERAGE",
            "REQUEST_SCOPE",
            "SCHEMA",
            "UNITS",
            "ADJUSTMENT",
            "ROW_COUNT",
        }
    )
    if not differences:
        status = CaptureReconciliationStatus.MATCH
    elif scope_labels.intersection(differences):
        status = CaptureReconciliationStatus.SCOPE_MISMATCH
    else:
        status = CaptureReconciliationStatus.CONTENT_MISMATCH
    report = CaptureReconciliationReport(
        left_capture_id=left.envelope.plan.capture_id,
        right_capture_id=right.envelope.plan.capture_id,
        left_seal_digest=left.envelope.seal_digest,
        right_seal_digest=right.envelope.seal_digest,
        left_scope_digest=left.scope_digest,
        right_scope_digest=right.scope_digest,
        left_content_digest=left.content_digest,
        right_content_digest=right.content_digest,
        status=status,
        differences=tuple(sorted(differences)),
    )
    store.write_reconciliation(report)
    return report


@dataclass(frozen=True, slots=True)
class _Projection:
    envelope: CaptureEnvelope
    identity_digest: str
    report_digest: str | None
    approval_id: str | None
    endpoint: str
    coverage: object
    request_scope: object
    schemas: object
    units: object
    adjustments: object
    row_counts: object
    content: object

    @property
    def scope_digest(self) -> str:
        return _digest(
            {
                "identity_digest": self.identity_digest,
                "report_digest": self.report_digest,
                "approval_id": self.approval_id,
                "endpoint": self.endpoint,
                "coverage": self.coverage,
                "request_scope": self.request_scope,
                "schemas": self.schemas,
                "units": self.units,
                "adjustments": self.adjustments,
                "row_counts": self.row_counts,
            }
        )

    @property
    def content_digest(self) -> str:
        return _digest(self.content)


def _capture_projection(store: CaptureReaderWriter, capture_id: str) -> _Projection:
    envelope = store.read(capture_id)
    chunks = tuple(store.read_chunk(capture_id, chunk_id) for chunk_id in envelope.chunk_ids)
    requests: list[object] = []
    for chunk in chunks:
        try:
            request = json.loads(chunk.canonical_request)
            requests.append({"method": request["method"], "params": request["params"]})
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise CaptureReconciliationError("capture request evidence is invalid") from error
    plan = envelope.plan
    return _Projection(
        envelope=envelope,
        identity_digest=plan.identity_digest,
        report_digest=plan.report_digest,
        approval_id=plan.approval_id,
        endpoint=plan.endpoint,
        coverage={
            "proof": plan.coverage_proof_digest,
            "chunks": plan.expected_chunk_count,
            "rows": plan.expected_row_count,
        },
        request_scope=requests,
        schemas=[dict(chunk.schema) for chunk in chunks],
        units=[list(chunk.units) for chunk in chunks],
        adjustments=[chunk.adjust for chunk in chunks],
        row_counts=[
            {"returned": chunk.returned_count, "declared": chunk.declared_total} for chunk in chunks
        ],
        content=[chunk.response_digest for chunk in chunks],
    )

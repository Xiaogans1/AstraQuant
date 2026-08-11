"""Formal Eastmoney batch capture adapter with exact raw-call lineage."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Protocol
from zoneinfo import ZoneInfo

from astraquant_data.capture import CaptureChunk, CaptureEnvelope, CapturePlan
from astraquant_data.capture_store import CaptureStore
from astraquant_data.eastmoney_client import HistoryCall
from astraquant_data.eastmoney_protocol import HistoryPageSpec
from astraquant_data.provider_identity import ProviderIdentity
from astraquant_domain import Adjustment
from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

_ADJUSTMENTS = {
    0: Adjustment.NONE,
    1: Adjustment.FORWARD,
    2: Adjustment.BACKWARD,
}
_CHINA_ZONE = ZoneInfo("Asia/Shanghai")


class ProviderEvidenceDriftError(RuntimeError):
    """The observed SDK evidence no longer matches the pinned provider identity."""


class CaptureCanceled(RuntimeError):
    """Capture stopped without sealing; verified chunks remain resumable."""


class BatchHistoryClient(Protocol):
    def history_page_with_evidence(
        self,
        *,
        symbol: str,
        frequency: str,
        page: HistoryPageSpec,
        adjust: int,
        units: tuple[str, ...],
    ) -> HistoryCall: ...


@dataclass(frozen=True, slots=True)
class BatchCaptureRequest:
    symbol: str
    frequency: str
    pages: tuple[HistoryPageSpec, ...]
    adjust: int
    units: tuple[str, ...]
    expected_total: int
    coverage_membership_digest: str
    max_rows_per_chunk: int = 5_000

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip():
            raise ValueError("symbol must be non-empty canonical text")
        if not self.frequency or self.frequency != self.frequency.strip():
            raise ValueError("frequency must be non-empty canonical text")
        pages = tuple(self.pages)
        if not pages:
            raise ValueError("pages must not be empty")
        if tuple(page.index for page in pages) != tuple(range(len(pages))):
            raise ValueError("pages must be ordered and contiguous")
        if any(page.page_count != len(pages) for page in pages):
            raise ValueError("page_count must match the complete page plan")
        if any(previous.end_at > current.start_at for previous, current in pairwise(pages)):
            raise ValueError("page ranges must not overlap")
        object.__setattr__(self, "pages", pages)
        if self.adjust not in _ADJUSTMENTS:
            raise ValueError("adjust must be 0, 1 or 2")
        units = tuple(sorted(self.units))
        if not units or len(units) != len(set(units)):
            raise ValueError("units must be non-empty and unique")
        object.__setattr__(self, "units", units)
        if self.expected_total < 0:
            raise ValueError("expected_total must be non-negative")
        object.__setattr__(
            self,
            "coverage_membership_digest",
            validate_digest("coverage_membership_digest", self.coverage_membership_digest),
        )
        if self.max_rows_per_chunk <= 0:
            raise ValueError("max_rows_per_chunk must be positive")
        if self.expected_total > len(pages) * self.max_rows_per_chunk:
            raise ValueError("expected rows exceed planned chunk capacity")

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "frequency": self.frequency,
            "pages": [
                {
                    "index": page.index,
                    "page_count": page.page_count,
                    "cursor": page.cursor,
                    "start_at": page.start_at.isoformat(),
                    "end_at": page.end_at.isoformat(),
                }
                for page in self.pages
            ],
            "adjust": self.adjust,
            "units": list(self.units),
            "expected_total": self.expected_total,
            "coverage_membership_digest": self.coverage_membership_digest,
            "max_rows_per_chunk": self.max_rows_per_chunk,
        }

    @property
    def coverage_proof_digest(self) -> str:
        return _digest(self.to_dict())


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def plan_session_coverage(
    *,
    symbol: str,
    frequency: str,
    sessions: tuple[date, ...],
    rows_per_session: int,
    adjust: int,
    units: tuple[str, ...] = ("price=CNY", "volume=share"),
    max_rows_per_chunk: int = 5_000,
) -> BatchCaptureRequest:
    """Create explicit non-overlapping chunks from a pinned lifecycle/session set."""

    exact_sessions = tuple(sessions)
    if not exact_sessions:
        raise ValueError("sessions must not be empty")
    if tuple(sorted(set(exact_sessions))) != exact_sessions:
        raise ValueError("sessions must be unique and strictly increasing")
    if rows_per_session <= 0:
        raise ValueError("rows_per_session must be positive")
    if max_rows_per_chunk < rows_per_session:
        raise ValueError("one session exceeds qualified chunk capacity")
    sessions_per_chunk = max_rows_per_chunk // rows_per_session
    groups = tuple(
        exact_sessions[index : index + sessions_per_chunk]
        for index in range(0, len(exact_sessions), sessions_per_chunk)
    )
    page_count = len(groups)
    pages: list[HistoryPageSpec] = []
    for index, group in enumerate(groups):
        start_at = datetime.combine(group[0], time.min, tzinfo=_CHINA_ZONE).astimezone(UTC)
        end_at = datetime.combine(
            group[-1] + timedelta(days=1),
            time.min,
            tzinfo=_CHINA_ZONE,
        ).astimezone(UTC) - timedelta(microseconds=1)
        pages.append(
            HistoryPageSpec(
                index=index,
                page_count=page_count,
                cursor=f"{group[0].isoformat()}/{group[-1].isoformat()}",
                start_at=start_at,
                end_at=end_at,
            )
        )
    return BatchCaptureRequest(
        symbol=symbol,
        frequency=frequency,
        pages=tuple(pages),
        adjust=adjust,
        units=units,
        expected_total=len(exact_sessions) * rows_per_session,
        coverage_membership_digest=_digest(
            {
                "sessions": [item.isoformat() for item in exact_sessions],
                "rows_per_session": rows_per_session,
            }
        ),
        max_rows_per_chunk=max_rows_per_chunk,
    )


class EastmoneyBatchAdapter:
    """Persist exact bridge results; never emit canonical bars directly."""

    def __init__(
        self,
        *,
        client: BatchHistoryClient,
        store: CaptureStore,
        identity: ProviderIdentity,
    ) -> None:
        self._client = client
        self._store = store
        self._identity = identity

    def capture(
        self,
        request: BatchCaptureRequest,
        *,
        plan: CapturePlan,
        recorded_at: datetime,
        should_cancel: Callable[[], bool] | None = None,
    ) -> CaptureEnvelope:
        if plan.identity_digest != self._identity.identity_digest:
            raise ProviderEvidenceDriftError("capture plan identity does not match provider")
        if plan.endpoint != self._identity.endpoint:
            raise ProviderEvidenceDriftError("capture plan endpoint does not match provider")
        if plan.expected_chunk_count != len(request.pages):
            raise ValueError("capture plan chunk count does not match request")
        if plan.expected_row_count != request.expected_total:
            raise ValueError("capture plan row count does not match request proof")
        if plan.coverage_proof_digest != request.coverage_proof_digest:
            raise ValueError("capture plan coverage proof does not match exact request")
        self._store.begin(plan)
        cancellation_requested = should_cancel or (lambda: False)
        stored_chunks = tuple(
            self._store.read_chunk(plan.capture_id, chunk_id)
            for chunk_id in self._store.list_chunk_ids(plan.capture_id)
        )
        existing_chunks = {chunk.sequence: chunk for chunk in stored_chunks}
        recorded_times = [chunk.recorded_at for chunk in existing_chunks.values()]
        for page_spec in request.pages:
            if page_spec.index in existing_chunks:
                existing = existing_chunks[page_spec.index]
                expected_adjust = _ADJUSTMENTS[request.adjust].name
                if (
                    existing.page_cursor != page_spec.cursor
                    or existing.page_count != page_spec.page_count
                    or existing.adjust != expected_adjust
                    or existing.units != request.units
                    or _digest(dict(existing.schema)) != self._identity.schema_fingerprint
                ):
                    raise ProviderEvidenceDriftError(
                        "stored capture chunk does not match resumed request"
                    )
                continue
            if cancellation_requested():
                raise CaptureCanceled("capture canceled before next page")
            call = self._client.history_page_with_evidence(
                symbol=request.symbol,
                frequency=request.frequency,
                page=page_spec,
                adjust=request.adjust,
                units=request.units,
            )
            if call.page.evidence.spec != page_spec:
                raise ProviderEvidenceDriftError("bridge page does not match page plan")
            evidence = call.response.evidence
            if evidence.interface != self._identity.interface:
                raise ProviderEvidenceDriftError("provider interface drift")
            if evidence.interface_build != self._identity.interface_build:
                raise ProviderEvidenceDriftError("provider interface build drift")
            if evidence.permission_tier != self._identity.permission_tier:
                raise ProviderEvidenceDriftError("provider permission tier drift")
            if _digest(evidence.observed_schema) != self._identity.schema_fingerprint:
                raise ProviderEvidenceDriftError("provider schema fingerprint drift")
            page = call.page.evidence
            if page.returned_count > request.max_rows_per_chunk:
                raise ProviderEvidenceDriftError("provider exceeded qualified chunk capacity")
            chunk_recorded_at = max(recorded_at, evidence.received_at)
            chunk = CaptureChunk(
                sequence=page.spec.index,
                canonical_request=canonical_json_bytes(evidence.canonical_request),
                canonical_response=canonical_json_bytes(call.response.result),
                response_representation=evidence.representation,
                requested_at=evidence.requested_at,
                received_at=evidence.received_at,
                recorded_at=chunk_recorded_at,
                serialization_version=evidence.serialization_version,
                dtype=str(evidence.observed_schema.get("kind", "unknown")),
                schema=evidence.observed_schema,
                units=page.units,
                adjust=_ADJUSTMENTS[page.adjust].name,
                page_cursor=page.spec.cursor,
                page_count=page.spec.page_count,
                returned_count=page.returned_count,
                declared_total=page.declared_total,
                attempt=evidence.attempt,
                retry_of_request_digest=evidence.retry_of_request_digest,
            )
            if chunk.request_digest != evidence.request_digest:
                raise ProviderEvidenceDriftError("provider request digest drift")
            if chunk.response_digest != evidence.response_digest:
                raise ProviderEvidenceDriftError("provider response digest drift")
            self._store.append_chunk(plan.capture_id, chunk)
            recorded_times.append(chunk_recorded_at)
            if cancellation_requested():
                raise CaptureCanceled("capture canceled after persisted page")
        return self._store.seal(plan.capture_id, sealed_at=max(recorded_times))

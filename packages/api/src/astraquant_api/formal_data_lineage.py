"""Resolve an incremental formal capture only from a verified sealed predecessor."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Protocol

from astraquant_api.formal_data_schemas import (
    FormalCaptureRequest,
    FormalIncrementRequest,
    ResolvedFormalCaptureCommand,
)
from astraquant_api.formal_data_service import FormalCaptureAdmissionError
from astraquant_data.capture import CaptureChunk, CaptureEnvelope, CapturePurpose
from astraquant_data.eastmoney_protocol import from_eastmoney_symbol
from astraquant_domain import Adjustment, BarFrequency


class SealedCaptureReader(Protocol):
    def read(self, capture_id: str) -> CaptureEnvelope: ...

    def read_chunk(self, capture_id: str, chunk_id: str) -> CaptureChunk: ...


class CaptureAdmission(Protocol):
    def resolve(
        self,
        request: FormalCaptureRequest,
        *,
        created_at: datetime,
    ) -> ResolvedFormalCaptureCommand: ...


_FREQUENCIES = {
    "1d": BarFrequency.DAY,
    "60s": BarFrequency.MINUTE,
}
_ADJUSTMENTS = {
    0: Adjustment.NONE,
    1: Adjustment.FORWARD,
    2: Adjustment.BACKWARD,
}


class FormalCaptureLineageService:
    def __init__(self, *, store: SealedCaptureReader, admission: CaptureAdmission) -> None:
        self._store = store
        self._admission = admission

    def resolve_increment(
        self,
        request: FormalIncrementRequest,
        *,
        created_at: datetime,
    ) -> ResolvedFormalCaptureCommand:
        envelope = self._store.read(request.predecessor_capture_id)
        plan = envelope.plan
        if plan.purpose is not CapturePurpose.FORMAL_DATA:
            raise FormalCaptureAdmissionError("increment predecessor is not formal data")
        if plan.approval_id is None or plan.report_digest is None:
            raise FormalCaptureAdmissionError("increment predecessor lacks approval lineage")
        chunks = tuple(
            self._store.read_chunk(request.predecessor_capture_id, chunk_id)
            for chunk_id in envelope.chunk_ids
        )
        instrument_id, frequency, adjustment, last_session = _capture_scope(chunks)
        start = last_session + timedelta(days=1)
        if request.end < start:
            raise FormalCaptureAdmissionError("increment end precedes the next capture date")
        resolved = self._admission.resolve(
            FormalCaptureRequest(
                approval_id=plan.approval_id,
                instrument_id=instrument_id,
                frequency=frequency,
                start=start,
                end=request.end,
                adjustment=adjustment,
            ),
            created_at=created_at,
        )
        if (
            resolved.identity_digest != plan.identity_digest
            or resolved.report_digest != plan.report_digest
            or resolved.approval_id != plan.approval_id
        ):
            raise FormalCaptureAdmissionError("increment approval lineage drift")
        return ResolvedFormalCaptureCommand.model_validate(
            {
                **resolved.model_dump(mode="json"),
                "predecessor_capture_id": request.predecessor_capture_id,
            }
        )


def _capture_scope(
    chunks: tuple[CaptureChunk, ...],
) -> tuple[str, BarFrequency, Adjustment, date]:
    if not chunks:
        raise FormalCaptureAdmissionError("increment predecessor has no chunks")
    scopes: set[tuple[str, str, int]] = set()
    for chunk in chunks:
        try:
            request = json.loads(chunk.canonical_request)
            params = request["params"]
            page = params["page"]
            if request["method"] != "history_range" or page["cursor"] != chunk.page_cursor:
                raise ValueError
            scopes.add(
                (
                    str(params["symbol"]),
                    str(params["frequency"]),
                    int(params["adjust"]),
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise FormalCaptureAdmissionError(
                "increment predecessor request evidence is invalid"
            ) from error
    if len(scopes) != 1:
        raise FormalCaptureAdmissionError("increment predecessor scope drift")
    symbol, raw_frequency, raw_adjustment = scopes.pop()
    try:
        frequency = _FREQUENCIES[raw_frequency]
        adjustment = _ADJUSTMENTS[raw_adjustment]
        last_session = date.fromisoformat(chunks[-1].page_cursor.split("/")[1])
        instrument_id = str(from_eastmoney_symbol(symbol))
    except (KeyError, IndexError, ValueError) as error:
        raise FormalCaptureAdmissionError("increment predecessor scope is unsupported") from error
    return instrument_id, frequency, adjustment, last_session

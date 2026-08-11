"""Filesystem store for append-only capture chunks and atomic parent seals."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from astraquant_domain.run_manifest import canonical_json_bytes

from .capture import CaptureChunk, CaptureEnvelope, CapturePlan


class CaptureStoreError(RuntimeError):
    pass


class CaptureConflictError(CaptureStoreError):
    pass


class CaptureIntegrityError(CaptureStoreError):
    pass


class IncompleteCaptureError(CaptureStoreError):
    pass


class SealedCaptureError(CaptureStoreError):
    pass


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CaptureIntegrityError(f"invalid capture object: {path.name}") from error
    if not isinstance(value, dict):
        raise CaptureIntegrityError(f"capture object is not a mapping: {path.name}")
    return value


def _create_immutable(path: Path, value: object) -> None:
    body = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == body:
            return
        raise CaptureConflictError(f"immutable capture object conflicts: {path.name}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != body:
                raise CaptureConflictError(
                    f"immutable capture object conflicts: {path.name}"
                ) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class CaptureStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    @staticmethod
    def _digest_name(digest: str) -> str:
        return digest.removeprefix("sha256:")

    def _capture_root(self, capture_id: str) -> Path:
        name = self._digest_name(capture_id)
        return self.root / "captures" / name[:2] / name

    def _plan_path(self, capture_id: str) -> Path:
        return self._capture_root(capture_id) / "plan.json"

    def _seal_path(self, capture_id: str) -> Path:
        return self._capture_root(capture_id) / "seal.json"

    def _chunks_root(self, capture_id: str) -> Path:
        return self._capture_root(capture_id) / "chunks"

    def chunk_path(self, capture_id: str, chunk_id: str) -> Path:
        return self._chunks_root(capture_id) / f"{self._digest_name(chunk_id)}.json"

    def read_chunk(self, capture_id: str, chunk_id: str) -> CaptureChunk:
        self._read_plan(capture_id)
        path = self.chunk_path(capture_id, chunk_id)
        if not path.exists():
            raise CaptureIntegrityError("capture chunk does not exist")
        return self._read_chunk(path)

    def list_chunk_ids(self, capture_id: str) -> tuple[str, ...]:
        self._read_plan(capture_id)
        return tuple(chunk.chunk_id for chunk in self._ordered_chunks(capture_id))

    def begin(self, plan: CapturePlan) -> str:
        _create_immutable(self._plan_path(plan.capture_id), plan.to_dict())
        return plan.capture_id

    def _read_plan(self, capture_id: str) -> CapturePlan:
        try:
            plan = CapturePlan.from_dict(_read_object(self._plan_path(capture_id)))
        except ValueError as error:
            raise CaptureIntegrityError("capture plan is invalid") from error
        if plan.capture_id != capture_id:
            raise CaptureIntegrityError("capture plan digest does not match path")
        return plan

    def append_chunk(self, capture_id: str, chunk: CaptureChunk) -> str:
        plan = self._read_plan(capture_id)
        if self._seal_path(capture_id).exists():
            raise SealedCaptureError("sealed capture cannot accept chunks")
        if chunk.sequence >= plan.expected_chunk_count:
            raise CaptureConflictError("chunk sequence is outside capture plan")
        if chunk.page_count != plan.expected_chunk_count:
            raise CaptureConflictError("chunk page_count does not match capture plan")
        chunks_root = self._chunks_root(capture_id)
        if chunks_root.exists():
            for path in chunks_root.glob("*.json"):
                existing = self._read_chunk(path)
                if existing.sequence == chunk.sequence and existing.chunk_id != chunk.chunk_id:
                    raise CaptureConflictError(
                        f"capture sequence {chunk.sequence} already has different content"
                    )
                if (
                    existing.sequence != chunk.sequence
                    and existing.page_cursor == chunk.page_cursor
                ):
                    raise CaptureConflictError("capture page cursor is duplicated")
        _create_immutable(self.chunk_path(capture_id, chunk.chunk_id), chunk.to_dict())
        return chunk.chunk_id

    @staticmethod
    def _read_chunk(path: Path) -> CaptureChunk:
        value = _read_object(path)
        try:
            chunk = CaptureChunk.from_dict(value)
        except ValueError as error:
            raise CaptureIntegrityError("capture chunk digest/content is invalid") from error
        expected_name = f"{chunk.chunk_id.removeprefix('sha256:')}.json"
        if path.name != expected_name:
            raise CaptureIntegrityError("capture chunk digest does not match path")
        return chunk

    def _ordered_chunks(self, capture_id: str) -> tuple[CaptureChunk, ...]:
        root = self._chunks_root(capture_id)
        paths = tuple(root.glob("*.json")) if root.exists() else ()
        chunks = tuple(sorted((self._read_chunk(path) for path in paths), key=lambda x: x.sequence))
        if tuple(chunk.sequence for chunk in chunks) != tuple(range(len(chunks))):
            raise IncompleteCaptureError("capture chunks are not contiguous")
        return chunks

    def seal(
        self,
        capture_id: str,
        *,
        sealed_at: datetime | None = None,
    ) -> CaptureEnvelope:
        plan = self._read_plan(capture_id)
        existing = self._seal_path(capture_id)
        if existing.exists():
            return self.read(capture_id)
        chunks = self._ordered_chunks(capture_id)
        if len(chunks) != plan.expected_chunk_count:
            raise IncompleteCaptureError(
                f"expected {plan.expected_chunk_count} chunks, found {len(chunks)}"
            )
        semantic_shapes = {
            (
                chunk.adjust,
                chunk.units,
                canonical_json_bytes(dict(chunk.schema)),
                chunk.response_representation,
                chunk.serialization_version,
                chunk.dtype,
            )
            for chunk in chunks
        }
        if len(semantic_shapes) != 1:
            raise IncompleteCaptureError("capture adjustment/units/schema drift across chunks")
        declared_values = tuple(chunk.declared_total for chunk in chunks)
        if any(value is None for value in declared_values) and any(
            value is not None for value in declared_values
        ):
            raise IncompleteCaptureError("capture declared total is inconsistent")
        if all(value is not None for value in declared_values):
            declared_totals = {value for value in declared_values if value is not None}
            if len(declared_totals) != 1:
                raise IncompleteCaptureError("capture declared total is inconsistent")
            proof_total = next(iter(declared_totals))
            if proof_total != plan.expected_row_count:
                raise IncompleteCaptureError("provider total disagrees with coverage proof")
        else:
            proof_total = plan.expected_row_count
        if sum(chunk.returned_count for chunk in chunks) != proof_total:
            raise IncompleteCaptureError("capture total does not match returned rows")
        envelope = CaptureEnvelope(
            plan=plan,
            chunk_ids=tuple(chunk.chunk_id for chunk in chunks),
            sealed_at=sealed_at or datetime.now(UTC),
        )
        _create_immutable(self._seal_path(capture_id), envelope.to_dict())
        return envelope

    def read(self, capture_id: str) -> CaptureEnvelope:
        plan = self._read_plan(capture_id)
        seal_path = self._seal_path(capture_id)
        if not seal_path.exists():
            raise IncompleteCaptureError("capture is not sealed")
        try:
            envelope = CaptureEnvelope.from_dict(_read_object(seal_path))
        except ValueError as error:
            raise CaptureIntegrityError("capture seal is invalid") from error
        if envelope.plan != plan:
            raise CaptureIntegrityError("capture seal plan does not match stored plan")
        chunks = self._ordered_chunks(capture_id)
        actual_ids = tuple(chunk.chunk_id for chunk in chunks)
        if actual_ids != envelope.chunk_ids:
            raise CaptureIntegrityError("capture chunk digest set does not match seal")
        return envelope

"""Authenticated local data catalog and import routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.params import Depends
from fastapi.responses import JSONResponse

from astraquant_api.data_repository import (
    DataCatalogRepository,
    DataDatasetRecord,
    DataSnapshotRecord,
)
from astraquant_api.data_schemas import (
    BarPreview,
    DataImportRequest,
    DatasetSummary,
    SnapshotSummary,
)
from astraquant_api.data_worker import run_data_import_worker
from astraquant_api.repository import TaskRepository
from astraquant_api.schemas import TaskResponse
from astraquant_api.task_model import TaskRecord
from astraquant_data.query import MarketDataQuery


class ImportSupervisor(Protocol):
    def start(
        self,
        task: TaskRecord,
        worker_target: Callable[..., None],
        worker_args: tuple[object, ...],
    ) -> TaskRecord: ...


class DataRouteState(Protocol):
    @property
    def repository(self) -> TaskRepository: ...

    @property
    def data_catalog(self) -> DataCatalogRepository: ...

    @property
    def supervisor(self) -> ImportSupervisor: ...

    @property
    def state_dir(self) -> Path: ...

    @property
    def allowed_data_instruments(self) -> frozenset[str]: ...

    @property
    def enable_akshare(self) -> bool: ...

    @property
    def shutting_down(self) -> bool: ...


def build_data_router(state: DataRouteState, authenticated: Depends) -> APIRouter:
    router = APIRouter(prefix="/v1/data", dependencies=[authenticated])

    @router.post("/imports", response_model=TaskResponse)
    def create_import(
        request: DataImportRequest,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        key = _idempotency_key(idempotency_key)
        existing = state.repository.get_by_idempotency_key(key)
        if existing is not None:
            return _task_json(existing, 200)
        if state.shutting_down:
            raise HTTPException(503, "runtime is shutting down")
        if request.instrument_id not in state.allowed_data_instruments:
            raise HTTPException(403, "instrument is not enabled for local imports")
        if request.provider == "akshare" and not state.enable_akshare:
            raise HTTPException(403, "AKShare imports are disabled")
        task = TaskRecord.create("data.import", key)
        state.repository.create(task, event_type="task.created")
        running = state.supervisor.start(
            task,
            run_data_import_worker,
            (request.model_dump(mode="json"), str(state.state_dir)),
        )
        return _task_json(running, 201)

    @router.get("/datasets", response_model=list[DatasetSummary])
    def list_datasets() -> list[DatasetSummary]:
        return [_dataset_summary(item) for item in state.data_catalog.list_datasets()]

    @router.get(
        "/datasets/{dataset_id}/snapshots",
        response_model=list[SnapshotSummary],
    )
    def list_snapshots(dataset_id: str) -> list[SnapshotSummary]:
        datasets = {item.dataset_id for item in state.data_catalog.list_datasets()}
        if dataset_id not in datasets:
            raise HTTPException(404, "dataset not found")
        return [
            _snapshot_summary(state.data_catalog, item)
            for item in state.data_catalog.list_snapshots(dataset_id)
        ]

    @router.get("/snapshots/{snapshot_id}", response_model=SnapshotSummary)
    def get_snapshot(snapshot_id: str) -> SnapshotSummary:
        snapshot = state.data_catalog.get_visible_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(404, "snapshot not found")
        return _snapshot_summary(state.data_catalog, snapshot)

    @router.get(
        "/snapshots/{snapshot_id}/bars",
        response_model=list[BarPreview],
    )
    def preview_bars(
        snapshot_id: str,
        limit: int = Query(10, ge=1, le=100),
    ) -> list[BarPreview]:
        snapshot = state.data_catalog.get_visible_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(404, "snapshot not found")
        query = MarketDataQuery.from_manifest(
            data_root=state.state_dir / "data",
            manifest_path=Path(snapshot.manifest_path),
        )
        try:
            bars = query.bars_as_of(
                instrument_ids=_manifest_instruments(query),
                decision_time=datetime.max.replace(tzinfo=UTC),
            )
        finally:
            query.close()
        return [
            BarPreview(
                instrument_id=str(bar.instrument_id),
                event_time=bar.event_time.isoformat(),
                available_time=bar.available_time.isoformat(),
                open=str(bar.open),
                high=str(bar.high),
                low=str(bar.low),
                close=str(bar.close),
                volume=str(bar.volume),
            )
            for bar in bars[-limit:]
        ]

    return router


def _manifest_instruments(query: MarketDataQuery) -> list[str]:
    return query.instrument_ids()


def _idempotency_key(value: str | None) -> str:
    if value is None or not 8 <= len(value) <= 200:
        raise HTTPException(400, "invalid Idempotency-Key")
    if any(ord(character) < 33 or ord(character) > 126 for character in value):
        raise HTTPException(400, "invalid Idempotency-Key")
    return value


def _task_json(task: TaskRecord, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=TaskResponse.from_record(task).model_dump(mode="json"),
    )


def _dataset_summary(record: DataDatasetRecord) -> DatasetSummary:
    return DatasetSummary.model_validate(record, from_attributes=True)


def _snapshot_summary(
    catalog: DataCatalogRepository,
    record: DataSnapshotRecord,
) -> SnapshotSummary:
    issues = catalog.list_quality_issues(record.snapshot_id)
    status: Literal["PUBLISHED", "REJECTED"] = (
        "PUBLISHED" if record.status.value == "PUBLISHED" else "REJECTED"
    )
    return SnapshotSummary(
        snapshot_id=record.snapshot_id,
        dataset_id=record.dataset_id,
        status=status,
        row_count=record.row_count,
        provider_id=record.provider_id,
        created_at=record.created_at.isoformat(),
        min_event_time=record.min_event_time.isoformat(),
        max_event_time=record.max_event_time.isoformat(),
        quality_issues=[
            {
                "code": issue.code.value,
                "severity": issue.severity.value,
                "count": issue.count,
                "samples": list(issue.sample_keys),
            }
            for issue in issues
        ],
    )

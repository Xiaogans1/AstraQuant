"""Cancellable market-data import worker."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict

from astraquant_api.worker import DataImportResult, WorkerMessage, WorkerMessageKind
from astraquant_data.adapters.akshare import AkShareDailyBarProvider
from astraquant_data.calendars import TradingSession
from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_data.providers import HistoryRequest
from astraquant_domain import (
    Adjustment,
    Bar,
    BarFrequency,
    Clock,
    InstrumentId,
    SystemClock,
    Venue,
)

_EQUITY_VENUES = frozenset({Venue.SSE, Venue.SZSE, Venue.BSE})


class _ProviderDetails(TypedDict):
    calendar_version: str
    availability_policy: str
    series_kind: str
    roll_policy: str | None


class _EstimatedCalendar:
    calendar_version = "estimated-weekday-session-v1"

    def __init__(self, venue: Venue) -> None:
        self._venue = venue

    def is_session(self, trading_date: date) -> bool:
        return trading_date.weekday() < 5

    def session(self, trading_date: date) -> TradingSession:
        close = datetime.combine(trading_date, time(7), tzinfo=UTC)
        return TradingSession(
            venue=self._venue,
            trading_date=trading_date,
            session_open=close - timedelta(hours=6),
            session_close=close,
        )


def run_data_import_worker(
    task_id: str,
    queue: Any,
    cancel: Any,
    request_values: dict[str, object],
    legacy_data_root_value: str,
    *,
    clock: Clock | None = None,
) -> None:
    try:
        runtime_clock = clock or SystemClock()
        request = _history_request(request_values)
        _progress(queue, task_id, 10, "fetch")
        bars, provider, metadata = _fetch(request_values["provider"], request)
        observed_received_time = runtime_clock.now()
        _progress(queue, task_id, 25, "normalize")
        _progress(queue, task_id, 40, "validate")
        if _cancelled(queue, cancel, task_id, 40):
            return

        legacy_data_root = Path(legacy_data_root_value).resolve()
        dataset_id = _dataset_id(request)
        _progress(queue, task_id, 55, "stage_files")
        snapshot = ParquetSnapshotStore(legacy_data_root, clock=runtime_clock).publish_bars(
            dataset_id=dataset_id,
            bars=bars,
            provider=provider,
            calendar_version=metadata["calendar_version"],
            availability_policy=metadata["availability_policy"],
            series_kind=metadata["series_kind"],
            roll_policy=metadata["roll_policy"],
            source_fetched_at=observed_received_time,
        )
        if _cancelled(queue, cancel, task_id, 55):
            return

        _progress(queue, task_id, 70, "files_published")
        if _cancelled(queue, cancel, task_id, 70):
            return
        asset_class = "equity" if request.instrument_id.venue in _EQUITY_VENUES else "futures"
        queue.put(
            WorkerMessage(
                task_id=task_id,
                kind=WorkerMessageKind.SUCCEEDED,
                progress=100,
                current_step="completed",
                payload=DataImportResult(
                    dataset_id=dataset_id,
                    snapshot_id=snapshot.snapshot_id,
                    manifest_path=str(snapshot.manifest_path),
                    manifest_digest=_sha256_file(snapshot.manifest_path),
                    row_count=len(bars),
                    name=f"{request.instrument_id} 日线",
                    asset_class=asset_class,
                    frequency=request.frequency.value,
                    semantic_class="LEGACY_SEMANTICS",
                    evidence_class="LEGACY_UNVERIFIED",
                    run_class="EXPLORATORY",
                    observed_received_time=observed_received_time,
                ),
            )
        )
    except Exception as error:
        queue.put(
            WorkerMessage(
                task_id=task_id,
                kind=WorkerMessageKind.FAILED,
                progress=0,
                current_step="failed",
                payload={"error_type": type(error).__name__},
            )
        )


def _history_request(values: dict[str, object]) -> HistoryRequest:
    return HistoryRequest(
        instrument_id=InstrumentId.parse(str(values["instrument_id"])),
        frequency=BarFrequency(str(values["frequency"])),
        start=date.fromisoformat(str(values["start"])),
        end=date.fromisoformat(str(values["end"])),
        adjustment=Adjustment(str(values["adjustment"])),
    )


def _fetch(
    provider_id: object,
    request: HistoryRequest,
) -> tuple[tuple[Bar, ...], dict[str, str], _ProviderDetails]:
    if provider_id == "fixture":
        bars = _fixture_bars(request)
        return (
            bars,
            {"id": "fixture", "interface": "generated", "version": "1"},
            {
                "calendar_version": "fixture-weekdays-v1",
                "availability_policy": "estimated_session_close_plus_1m",
                "series_kind": (
                    "continuous" if request.instrument_id.symbol.endswith("0") else "instrument"
                ),
                "roll_policy": (
                    "fixture_upstream" if request.instrument_id.symbol.endswith("0") else None
                ),
            },
        )
    if provider_id == "akshare":
        calendar = _EstimatedCalendar(request.instrument_id.venue)
        adapter = AkShareDailyBarProvider(calendars={request.instrument_id.venue: calendar})
        metadata = adapter.provider_metadata(request)
        return (
            tuple(adapter.fetch_bars(request)),
            {
                "id": metadata.provider_id,
                "interface": metadata.interface,
                "version": metadata.version,
            },
            {
                "calendar_version": metadata.calendar_version,
                "availability_policy": metadata.availability_policy,
                "series_kind": metadata.series_kind,
                "roll_policy": metadata.roll_policy,
            },
        )
    raise ValueError("unsupported data provider")


def _fixture_bars(request: HistoryRequest) -> tuple[Bar, ...]:
    days: list[date] = []
    current = request.start
    while current <= request.end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    if not days:
        raise ValueError("fixture range contains no weekday sessions")
    bars: list[Bar] = []
    for index, trading_date in enumerate(days):
        close = Decimal("10") + Decimal(index) / Decimal("10")
        event_time = datetime.combine(trading_date, time(7), tzinfo=UTC)
        is_equity = request.instrument_id.venue in _EQUITY_VENUES
        bars.append(
            Bar(
                instrument_id=request.instrument_id,
                frequency=request.frequency,
                trading_date=trading_date,
                event_time=event_time,
                available_time=event_time + timedelta(minutes=1),
                open=close - Decimal("0.1"),
                high=close + Decimal("0.2"),
                low=close - Decimal("0.2"),
                close=close,
                volume=Decimal(1000 + index * 100),
                turnover=(Decimal(10000 + index * 1000) if is_equity else None),
                open_interest=(None if is_equity else Decimal(5000 + index * 10)),
                settlement=(None if is_equity else close),
                adjustment=request.adjustment,
                availability_estimated=True,
            )
        )
    return tuple(bars)


def _dataset_id(request: HistoryRequest) -> str:
    asset_class = "equity" if request.instrument_id.venue in _EQUITY_VENUES else "futures"
    instrument = str(request.instrument_id).lower().replace(".", "-")
    return f"cn-{asset_class}-{instrument}-{request.frequency.value}-{request.adjustment.value}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _progress(
    queue: Any,
    task_id: str,
    progress: int,
    current_step: str,
) -> None:
    queue.put(
        WorkerMessage(
            task_id=task_id,
            kind=WorkerMessageKind.PROGRESS,
            progress=progress,
            current_step=current_step,
        )
    )


def _cancelled(queue: Any, cancel: Any, task_id: str, progress: int) -> bool:
    if not cancel.is_set():
        return False
    queue.put(
        WorkerMessage(
            task_id=task_id,
            kind=WorkerMessageKind.CANCELED,
            progress=progress,
            current_step="canceled",
        )
    )
    return True

"""Resumable, bounded AKShare batch collection for exploratory training data."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from astraquant_data.evidence import EvidenceRef
from astraquant_data.providers import HistoryRequest
from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId

_SCHEMA_VERSION = "astraquant.akshare-5m-checkpoint/v1"


class FiveMinuteProvider(Protocol):
    def fetch_bars(self, request: HistoryRequest) -> Sequence[Bar]: ...


@dataclass(frozen=True, slots=True)
class BatchFailure:
    instrument_id: InstrumentId
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class BatchCollectionResult:
    bars: tuple[Bar, ...]
    completed: tuple[InstrumentId, ...]
    failures: tuple[BatchFailure, ...]
    resumed: tuple[InstrumentId, ...]
    evidence: EvidenceRef
    checkpoint_path: Path


class AkShareFiveMinuteBatchCollector:
    """Fetch one trading day for many instruments with durable per-item checkpoints."""

    def __init__(
        self,
        *,
        provider: FiveMinuteProvider,
        checkpoint_path: Path,
        max_workers: int = 4,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 1 <= max_workers <= 32:
            raise ValueError("max_workers must be between 1 and 32")
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
        self._provider = provider
        self._checkpoint_path = checkpoint_path.resolve()
        self._max_workers = max_workers
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def collect(
        self,
        *,
        instruments: Sequence[InstrumentId],
        trading_date: date,
        adjustment: Adjustment = Adjustment.NONE,
    ) -> BatchCollectionResult:
        unique = tuple(sorted(set(instruments), key=str))
        if not unique:
            raise ValueError("at least one instrument is required")
        self._checkpoint_path.mkdir(parents=True, exist_ok=True)
        request_digest = self._prepare_request(unique, trading_date, adjustment)

        collected: dict[InstrumentId, tuple[Bar, ...]] = {}
        resumed: list[InstrumentId] = []
        pending: list[InstrumentId] = []
        for instrument in unique:
            cached = self._load_cached(instrument, request_digest)
            if cached is None:
                pending.append(instrument)
            else:
                collected[instrument] = cached
                resumed.append(instrument)

        failures: list[BatchFailure] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(
                    self._fetch_with_retry,
                    instrument,
                    trading_date,
                    adjustment,
                    request_digest,
                ): instrument
                for instrument in pending
            }
            for future in as_completed(futures):
                instrument = futures[future]
                try:
                    collected[instrument] = future.result()
                except Exception as error:
                    failures.append(
                        BatchFailure(
                            instrument_id=instrument,
                            error_type=type(error).__name__,
                            message=str(error),
                        )
                    )

        completed = tuple(sorted(collected, key=str))
        bars = tuple(
            sorted(
                (bar for instrument in completed for bar in collected[instrument]),
                key=lambda bar: (str(bar.instrument_id), bar.event_time),
            )
        )
        digest = _digest_json([_bar_to_dict(bar) for bar in bars])
        evidence = EvidenceRef.exploratory(
            artifact_id=f"akshare-5m-batch:{digest.removeprefix('sha256:')}",
            digest=digest,
        )
        ordered_failures = tuple(sorted(failures, key=lambda item: str(item.instrument_id)))
        self._write_summary(
            request_digest=request_digest,
            completed=completed,
            failures=ordered_failures,
            row_count=len(bars),
            content_digest=digest,
        )
        return BatchCollectionResult(
            bars=bars,
            completed=completed,
            failures=ordered_failures,
            resumed=tuple(resumed),
            evidence=evidence,
            checkpoint_path=self._checkpoint_path,
        )

    def _prepare_request(
        self,
        instruments: tuple[InstrumentId, ...],
        trading_date: date,
        adjustment: Adjustment,
    ) -> str:
        request = {
            "schema_version": _SCHEMA_VERSION,
            "provider_id": "akshare",
            "interface": "stock_zh_a_hist_min_em",
            "frequency": BarFrequency.FIVE_MINUTE.value,
            "trading_date": trading_date.isoformat(),
            "adjustment": adjustment.value,
            "instruments": [str(value) for value in instruments],
        }
        digest = _digest_json(request)
        path = self._checkpoint_path / "request.json"
        document = {**request, "request_digest": digest}
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != document:
                raise ValueError("checkpoint belongs to a different batch request")
        else:
            _atomic_json(path, document)
        (self._checkpoint_path / "items").mkdir(exist_ok=True)
        return digest

    def _fetch_with_retry(
        self,
        instrument: InstrumentId,
        trading_date: date,
        adjustment: Adjustment,
        request_digest: str,
    ) -> tuple[Bar, ...]:
        request = HistoryRequest(
            instrument_id=instrument,
            frequency=BarFrequency.FIVE_MINUTE,
            start=trading_date,
            end=trading_date,
            adjustment=adjustment,
        )
        for attempt in range(1, self._max_attempts + 1):
            try:
                bars = tuple(self._provider.fetch_bars(request))
                if not bars:
                    raise ValueError("provider returned no bars")
                _validate_item(bars, request)
                payload = {
                    "schema_version": _SCHEMA_VERSION,
                    "request_digest": request_digest,
                    "instrument_id": str(instrument),
                    "bars": [_bar_to_dict(bar) for bar in bars],
                }
                payload["content_digest"] = _digest_json(payload["bars"])
                _atomic_json(self._item_path(instrument), payload)
                return bars
            except Exception:
                if attempt == self._max_attempts:
                    raise
                self._sleep(self._backoff_seconds * (2 ** (attempt - 1)))
        raise AssertionError("unreachable retry state")

    def _load_cached(
        self,
        instrument: InstrumentId,
        request_digest: str,
    ) -> tuple[Bar, ...] | None:
        path = self._item_path(instrument)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("request_digest") != request_digest:
            raise ValueError(f"checkpoint item request mismatch: {instrument}")
        bars_raw = raw.get("bars")
        if not isinstance(bars_raw, list) or raw.get("content_digest") != _digest_json(bars_raw):
            raise ValueError(f"checkpoint item digest mismatch: {instrument}")
        bars = tuple(_bar_from_dict(value) for value in bars_raw)
        return bars

    def _item_path(self, instrument: InstrumentId) -> Path:
        return self._checkpoint_path / "items" / f"{str(instrument).lower()}.json"

    def _write_summary(
        self,
        *,
        request_digest: str,
        completed: tuple[InstrumentId, ...],
        failures: tuple[BatchFailure, ...],
        row_count: int,
        content_digest: str,
    ) -> None:
        _atomic_json(
            self._checkpoint_path / "summary.json",
            {
                "schema_version": _SCHEMA_VERSION,
                "request_digest": request_digest,
                "updated_at": datetime.now(UTC).isoformat(),
                "completed": [str(value) for value in completed],
                "failures": [
                    {
                        "instrument_id": str(value.instrument_id),
                        "error_type": value.error_type,
                        "message": value.message,
                    }
                    for value in failures
                ],
                "row_count": row_count,
                "content_digest": content_digest,
                "evidence_class": "EXPLORATORY_ONLY",
                "run_class": "EXPLORATORY",
            },
        )


def _validate_item(bars: tuple[Bar, ...], request: HistoryRequest) -> None:
    keys: set[datetime] = set()
    for bar in bars:
        if bar.instrument_id != request.instrument_id:
            raise ValueError("provider returned a different instrument")
        if bar.frequency is not BarFrequency.FIVE_MINUTE:
            raise ValueError("provider returned a non-5m bar")
        if bar.trading_date != request.start:
            raise ValueError("provider returned a bar outside the requested trading day")
        if bar.event_time in keys:
            raise ValueError("provider returned duplicate bar timestamps")
        keys.add(bar.event_time)


def _bar_to_dict(bar: Bar) -> dict[str, object]:
    return {
        "instrument_id": str(bar.instrument_id),
        "frequency": bar.frequency.value,
        "trading_date": bar.trading_date.isoformat(),
        "event_time": bar.event_time.isoformat(),
        "available_time": bar.available_time.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "turnover": None if bar.turnover is None else str(bar.turnover),
        "open_interest": None if bar.open_interest is None else str(bar.open_interest),
        "settlement": None if bar.settlement is None else str(bar.settlement),
        "adjustment": bar.adjustment.value,
        "availability_estimated": bar.availability_estimated,
    }


def _bar_from_dict(value: object) -> Bar:
    if not isinstance(value, dict):
        raise ValueError("invalid checkpoint bar")
    return Bar(
        instrument_id=InstrumentId.parse(str(value["instrument_id"])),
        frequency=BarFrequency(str(value["frequency"])),
        trading_date=date.fromisoformat(str(value["trading_date"])),
        event_time=datetime.fromisoformat(str(value["event_time"])),
        available_time=datetime.fromisoformat(str(value["available_time"])),
        open=Decimal(str(value["open"])),
        high=Decimal(str(value["high"])),
        low=Decimal(str(value["low"])),
        close=Decimal(str(value["close"])),
        volume=Decimal(str(value["volume"])),
        turnover=_optional_decimal(value.get("turnover")),
        open_interest=_optional_decimal(value.get("open_interest")),
        settlement=_optional_decimal(value.get("settlement")),
        adjustment=Adjustment(str(value["adjustment"])),
        availability_estimated=bool(value["availability_estimated"]),
    )


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _digest_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)

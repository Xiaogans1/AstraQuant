"""Staged publication of immutable, partitioned Parquet snapshots."""

import hashlib
import os
import re
import shutil
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.arrow_schema import bars_to_table
from astraquant_data.manifests import SnapshotFile, SnapshotManifest
from astraquant_data.quality import QualityReport, evaluate_bars
from astraquant_domain import Bar, Clock, SystemClock, Venue

_DATASET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_EQUITY_VENUES = frozenset({Venue.SSE, Venue.SZSE, Venue.BSE})


class SnapshotRejected(ValueError):
    def __init__(self, report: QualityReport) -> None:
        self.report = report
        super().__init__("snapshot failed data-quality publication rules")


@dataclass(frozen=True, slots=True)
class PublishedSnapshot:
    snapshot_id: str
    snapshot_path: Path
    manifest_path: Path
    manifest: SnapshotManifest


class ParquetSnapshotStore:
    def __init__(self, data_root: Path, *, clock: Clock | None = None) -> None:
        self._data_root = data_root.resolve()
        self._clock = clock or SystemClock()
        self._staging_root = self._data_root / ".staging"
        self._datasets_root = self._data_root / "datasets"
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._datasets_root.mkdir(parents=True, exist_ok=True)

    def publish_bars(
        self,
        *,
        dataset_id: str,
        bars: Sequence[Bar],
        provider: Mapping[str, str],
        calendar_version: str,
        availability_policy: str,
        series_kind: str = "instrument",
        roll_policy: str | None = None,
        source_fetched_at: datetime | None = None,
        expected_trading_dates: set[date] | None = None,
    ) -> PublishedSnapshot:
        if not _DATASET_ID_PATTERN.fullmatch(dataset_id):
            raise ValueError(f"invalid dataset_id: {dataset_id!r}")
        if set(provider) != {"id", "interface", "version"}:
            raise ValueError("provider must contain id, interface and version")
        if not calendar_version or not availability_policy:
            raise ValueError("calendar and availability policy must not be empty")
        fetched_at = source_fetched_at or self._clock.now()
        expected_dates = expected_trading_dates or {bar.trading_date for bar in bars}
        quality = evaluate_bars(
            bars,
            expected_trading_dates=expected_dates,
            source_fetched_at=fetched_at,
        )
        if not quality.publishable:
            raise SnapshotRejected(quality)
        created_at = self._clock.now()
        staging_path = self._staging_root / str(uuid4())
        staging_path.mkdir()
        try:
            files = self._write_partitions(staging_path, bars)
            adjustments = {bar.adjustment.value for bar in bars}
            manifest = SnapshotManifest.create(
                dataset_id=dataset_id,
                kind="bars",
                created_at=created_at,
                source_fetched_at=fetched_at,
                provider=dict(provider),
                adjustment=(next(iter(adjustments)) if len(adjustments) == 1 else "mixed"),
                calendar_version=calendar_version,
                series_kind=series_kind,
                roll_policy=roll_policy,
                availability_policy=availability_policy,
                row_count=len(bars),
                min_event_time=min(bar.event_time for bar in bars),
                max_event_time=max(bar.event_time for bar in bars),
                files=files,
                quality=quality,
            )
            manifest_path = staging_path / "manifest.json"
            manifest_path.write_text(manifest.to_json(), encoding="utf-8", newline="\n")
            _fsync_file(manifest_path)
            target = self._datasets_root / dataset_id / "snapshots" / manifest.snapshot_id
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                existing = SnapshotManifest.from_path(target / "manifest.json")
                if existing != manifest:
                    raise RuntimeError("snapshot hash collision with different manifest")
                shutil.rmtree(staging_path)
            else:
                os.replace(staging_path, target)
            return PublishedSnapshot(
                snapshot_id=manifest.snapshot_id,
                snapshot_path=target,
                manifest_path=target / "manifest.json",
                manifest=manifest,
            )
        except Exception:
            if staging_path.exists():
                shutil.rmtree(staging_path)
            raise

    def _write_partitions(
        self,
        staging_path: Path,
        bars: Sequence[Bar],
    ) -> tuple[SnapshotFile, ...]:
        groups: dict[tuple[str, str, str], list[Bar]] = defaultdict(list)
        for bar in bars:
            asset_class = "equity" if bar.instrument_id.venue in _EQUITY_VENUES else "futures"
            groups[(asset_class, bar.frequency.value, bar.trading_date.isoformat())].append(bar)
        files: list[SnapshotFile] = []
        for (asset_class, frequency, trading_date), partition_bars in sorted(groups.items()):
            relative = Path(
                "market=cn",
                f"asset_class={asset_class}",
                f"frequency={frequency}",
                f"trading_date={trading_date}",
                "part-0.parquet",
            )
            path = staging_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                bars_to_table(partition_bars),
                path,
                compression="zstd",
                version="2.6",
            )
            _fsync_file(path)
            files.append(
                SnapshotFile(
                    path=relative.as_posix(),
                    sha256=_sha256_file(path),
                    rows=len(partition_bars),
                )
            )
        return tuple(files)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb+") as handle:
        os.fsync(handle.fileno())

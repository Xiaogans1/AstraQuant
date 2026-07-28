"""Safe, point-in-time market-data queries over approved snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from astraquant_data.arrow_schema import BAR_SCHEMA, table_to_bars
from astraquant_data.manifests import SnapshotManifest
from astraquant_domain import Bar


class MarketDataQuery:
    """Expose fixed queries without accepting caller-provided SQL or file paths."""

    def __init__(self, table: pa.Table) -> None:
        self._connection = duckdb.connect(":memory:")
        self._connection.register("approved_bars", table)
        self._instrument_ids = tuple(sorted(set(table.column("instrument_id").to_pylist())))

    @classmethod
    def from_manifest(
        cls,
        *,
        data_root: Path,
        manifest_path: Path,
    ) -> Self:
        approved_root = data_root.resolve()
        approved_manifest = manifest_path.resolve()
        _require_inside(approved_manifest, approved_root, label="manifest")
        manifest = SnapshotManifest.from_path(approved_manifest)
        if manifest.kind != "bars":
            raise ValueError("manifest does not describe bar data")

        snapshot_root = approved_manifest.parent
        tables: list[pa.Table] = []
        for item in manifest.files:
            path = (snapshot_root / item.path).resolve()
            _require_inside(path, snapshot_root, label="snapshot file")
            _require_inside(path, approved_root, label="snapshot file")
            tables.append(pq.ParquetFile(path).read().cast(BAR_SCHEMA))
        if not tables:
            raise ValueError("snapshot manifest contains no Parquet files")
        return cls(pa.concat_tables(tables))

    def bars_between(
        self,
        *,
        instrument_ids: Sequence[str],
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        instruments = _validate_instruments(instrument_ids)
        normalized_start = _require_aware("start", start)
        normalized_end = _require_aware("end", end)
        if normalized_start > normalized_end:
            raise ValueError("start must not exceed end")
        table = self._connection.execute(
            """
            SELECT *
            FROM approved_bars
            WHERE instrument_id IN (SELECT unnest(?))
              AND event_time >= ?
              AND event_time <= ?
            ORDER BY event_time, instrument_id, available_time
            """,
            [instruments, normalized_start, normalized_end],
        ).to_arrow_table()
        return list(table_to_bars(table.cast(BAR_SCHEMA)))

    def bars_as_of(
        self,
        *,
        instrument_ids: Sequence[str],
        decision_time: datetime,
    ) -> list[Bar]:
        instruments = _validate_instruments(instrument_ids)
        cutoff = _require_aware("decision_time", decision_time)
        table = self._connection.execute(
            """
            SELECT *
            FROM approved_bars
            WHERE instrument_id IN (SELECT unnest(?))
              AND event_time <= ?
              AND available_time <= ?
            QUALIFY row_number() OVER (
              PARTITION BY instrument_id, frequency, event_time
              ORDER BY available_time DESC
            ) = 1
            ORDER BY event_time, instrument_id
            """,
            [instruments, cutoff, cutoff],
        ).to_arrow_table()
        return list(table_to_bars(table.cast(BAR_SCHEMA)))

    def close(self) -> None:
        self._connection.close()

    def instrument_ids(self) -> list[str]:
        return list(self._instrument_ids)


def _validate_instruments(instrument_ids: Sequence[str]) -> list[str]:
    instruments = list(instrument_ids)
    if not instruments:
        raise ValueError("instrument_ids must not be empty")
    if any(not instrument for instrument in instruments):
        raise ValueError("instrument_ids must not contain empty values")
    return instruments


def _require_aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_inside(path: Path, root: Path, *, label: str) -> None:
    if not path.is_relative_to(root):
        raise ValueError(f"{label} must be inside the configured data root")

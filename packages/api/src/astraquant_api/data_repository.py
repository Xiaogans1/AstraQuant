"""SQLite catalog for immutable local market-data snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import Engine, RowMapping
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from astraquant_api.repository import metadata
from astraquant_data.parquet_store import PublishedSnapshot
from astraquant_data.quality import QualityCode, QualitySeverity

data_datasets = sa.Table(
    "data_datasets",
    metadata,
    sa.Column("dataset_id", sa.String(100), primary_key=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("asset_class", sa.String(32), nullable=False),
    sa.Column("frequency", sa.String(32), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

data_snapshots = sa.Table(
    "data_snapshots",
    metadata,
    sa.Column("snapshot_id", sa.String(64), primary_key=True),
    sa.Column(
        "dataset_id",
        sa.String(100),
        sa.ForeignKey("data_datasets.dataset_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("row_count", sa.Integer(), nullable=False),
    sa.Column("min_event_time", sa.DateTime(timezone=True), nullable=False),
    sa.Column("max_event_time", sa.DateTime(timezone=True), nullable=False),
    sa.Column("provider_id", sa.String(100), nullable=False),
    sa.Column("manifest_path", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "status IN ('STAGED', 'PUBLISHED', 'REJECTED')",
        name="ck_data_snapshots_status",
    ),
    sa.UniqueConstraint(
        "dataset_id",
        "snapshot_id",
        name="uq_data_snapshots_dataset_snapshot",
    ),
    sa.Index("ix_data_snapshots_dataset_created", "dataset_id", "created_at"),
)

data_quality_issues = sa.Table(
    "data_quality_issues",
    metadata,
    sa.Column(
        "snapshot_id",
        sa.String(64),
        sa.ForeignKey("data_snapshots.snapshot_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("code", sa.String(100), primary_key=True),
    sa.Column("severity", sa.String(16), nullable=False),
    sa.Column("count", sa.Integer(), nullable=False),
    sa.Column("samples_json", sa.Text(), nullable=False),
)


class SnapshotStatus(StrEnum):
    STAGED = "STAGED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class DataSnapshotRecord:
    snapshot_id: str
    dataset_id: str
    status: SnapshotStatus
    row_count: int
    min_event_time: datetime
    max_event_time: datetime
    provider_id: str
    manifest_path: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DataQualityIssueRecord:
    snapshot_id: str
    code: QualityCode
    severity: QualitySeverity
    count: int
    sample_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataDatasetRecord:
    dataset_id: str
    name: str
    asset_class: str
    frequency: str
    snapshot_count: int
    latest_snapshot_id: str | None


class DataCatalogRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def stage_snapshot(
        self,
        snapshot: PublishedSnapshot,
        *,
        name: str,
        asset_class: str,
        frequency: str,
    ) -> None:
        manifest = snapshot.manifest
        dataset_statement = sqlite_insert(data_datasets).values(
            dataset_id=manifest.dataset_id,
            name=name,
            asset_class=asset_class,
            frequency=frequency,
            created_at=manifest.created_at,
        )
        dataset_statement = dataset_statement.on_conflict_do_nothing(
            index_elements=[data_datasets.c.dataset_id]
        )
        snapshot_statement = sqlite_insert(data_snapshots).values(
            snapshot_id=manifest.snapshot_id,
            dataset_id=manifest.dataset_id,
            status=SnapshotStatus.STAGED.value,
            row_count=manifest.row_count,
            min_event_time=manifest.min_event_time,
            max_event_time=manifest.max_event_time,
            provider_id=manifest.provider["id"],
            manifest_path=str(snapshot.manifest_path),
            created_at=manifest.created_at,
        )
        snapshot_statement = snapshot_statement.on_conflict_do_nothing(
            index_elements=[data_snapshots.c.snapshot_id]
        )
        with self._engine.begin() as connection:
            connection.execute(dataset_statement)
            result = connection.execute(snapshot_statement)
            if result.rowcount != 1:
                return
            quality_values = [
                {
                    "snapshot_id": manifest.snapshot_id,
                    "code": issue.code.value,
                    "severity": issue.severity.value,
                    "count": issue.count,
                    "samples_json": json.dumps(
                        issue.sample_keys,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
                for issue in manifest.quality.issues
            ]
            if quality_values:
                connection.execute(data_quality_issues.insert(), quality_values)

    def mark_published(self, snapshot_id: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                data_snapshots.update()
                .where(data_snapshots.c.snapshot_id == snapshot_id)
                .where(data_snapshots.c.status == SnapshotStatus.STAGED.value)
                .values(status=SnapshotStatus.PUBLISHED.value)
            )
            if result.rowcount == 1:
                return True
            status = connection.execute(
                sa.select(data_snapshots.c.status).where(
                    data_snapshots.c.snapshot_id == snapshot_id
                )
            ).scalar_one_or_none()
        return status == SnapshotStatus.PUBLISHED.value

    def get_snapshot(self, snapshot_id: str) -> DataSnapshotRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(data_snapshots).where(data_snapshots.c.snapshot_id == snapshot_id)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _row_to_snapshot(row)

    def get_visible_snapshot(self, snapshot_id: str) -> DataSnapshotRecord | None:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None or snapshot.status is SnapshotStatus.STAGED:
            return None
        return snapshot

    def list_datasets(self) -> list[DataDatasetRecord]:
        visible = data_snapshots.c.status != SnapshotStatus.STAGED.value
        statement = (
            sa.select(
                data_datasets,
                sa.func.count(data_snapshots.c.snapshot_id).label("snapshot_count"),
            )
            .join(
                data_snapshots,
                sa.and_(
                    data_snapshots.c.dataset_id == data_datasets.c.dataset_id,
                    visible,
                ),
            )
            .group_by(data_datasets.c.dataset_id)
            .order_by(data_datasets.c.created_at.desc())
        )
        with self._engine.connect() as connection:
            rows = list(connection.execute(statement).mappings())
            records: list[DataDatasetRecord] = []
            for row in rows:
                latest = connection.execute(
                    sa.select(data_snapshots.c.snapshot_id)
                    .where(data_snapshots.c.dataset_id == row["dataset_id"])
                    .where(visible)
                    .order_by(data_snapshots.c.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                records.append(
                    DataDatasetRecord(
                        dataset_id=row["dataset_id"],
                        name=row["name"],
                        asset_class=row["asset_class"],
                        frequency=row["frequency"],
                        snapshot_count=row["snapshot_count"],
                        latest_snapshot_id=latest,
                    )
                )
        return records

    def list_staged_snapshots(self) -> list[DataSnapshotRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.select(data_snapshots).where(
                    data_snapshots.c.status == SnapshotStatus.STAGED.value
                )
            ).mappings()
            return [_row_to_snapshot(row) for row in rows]

    def reconcile_staged(self) -> int:
        recovered = 0
        for snapshot in self.list_staged_snapshots():
            if not Path(snapshot.manifest_path).is_file():
                continue
            recovered += int(self.mark_published(snapshot.snapshot_id))
        return recovered

    def list_snapshots(self, dataset_id: str) -> list[DataSnapshotRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.select(data_snapshots)
                .where(data_snapshots.c.dataset_id == dataset_id)
                .where(data_snapshots.c.status != SnapshotStatus.STAGED.value)
                .order_by(data_snapshots.c.created_at.desc())
            ).mappings()
            return [_row_to_snapshot(row) for row in rows]

    def list_quality_issues(
        self,
        snapshot_id: str,
    ) -> list[DataQualityIssueRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.select(data_quality_issues)
                .where(data_quality_issues.c.snapshot_id == snapshot_id)
                .order_by(data_quality_issues.c.code)
            ).mappings()
            return [
                DataQualityIssueRecord(
                    snapshot_id=row["snapshot_id"],
                    code=QualityCode(row["code"]),
                    severity=QualitySeverity(row["severity"]),
                    count=row["count"],
                    sample_keys=tuple(json.loads(row["samples_json"])),
                )
                for row in rows
            ]


def _row_to_snapshot(row: RowMapping) -> DataSnapshotRecord:
    return DataSnapshotRecord(
        snapshot_id=row["snapshot_id"],
        dataset_id=row["dataset_id"],
        status=SnapshotStatus(row["status"]),
        row_count=row["row_count"],
        min_event_time=_as_utc(row["min_event_time"]),
        max_event_time=_as_utc(row["max_event_time"]),
        provider_id=row["provider_id"],
        manifest_path=row["manifest_path"],
        created_at=_as_utc(row["created_at"]),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

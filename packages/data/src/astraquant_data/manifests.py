"""Canonical immutable snapshot manifests."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Self

from astraquant_data.evidence import EvidenceRef
from astraquant_data.quality import (
    QualityCode,
    QualityIssue,
    QualityReport,
    QualitySeverity,
)
from astraquant_data.snapshot_v2 import (
    SnapshotContentV2,
    SnapshotFileV2,
    SnapshotManifestV2,
    SnapshotPublicationV2,
)

__all__ = [
    "SnapshotContentV2",
    "SnapshotFileV2",
    "SnapshotManifestV2",
    "SnapshotPublicationV2",
]


@dataclass(frozen=True, slots=True)
class SnapshotFile:
    path: str
    sha256: str
    rows: int

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "rows": self.rows}


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    snapshot_id: str
    dataset_id: str
    kind: str
    created_at: datetime
    source_fetched_at: datetime
    provider: dict[str, str]
    adjustment: str
    calendar_version: str
    series_kind: str
    roll_policy: str | None
    availability_policy: str
    row_count: int
    min_event_time: datetime
    max_event_time: datetime
    files: tuple[SnapshotFile, ...]
    quality: QualityReport
    schema_version: int = 1

    @classmethod
    def create(
        cls,
        *,
        dataset_id: str,
        kind: str,
        created_at: datetime,
        source_fetched_at: datetime,
        provider: dict[str, str],
        adjustment: str,
        calendar_version: str,
        series_kind: str,
        roll_policy: str | None,
        availability_policy: str,
        row_count: int,
        min_event_time: datetime,
        max_event_time: datetime,
        files: tuple[SnapshotFile, ...],
        quality: QualityReport,
    ) -> Self:
        body = {
            "schema_version": 1,
            "dataset_id": dataset_id,
            "kind": kind,
            "created_at": created_at.isoformat(),
            "source_fetched_at": source_fetched_at.isoformat(),
            "provider": dict(sorted(provider.items())),
            "adjustment": adjustment,
            "calendar_version": calendar_version,
            "series_kind": series_kind,
            "roll_policy": roll_policy,
            "availability_policy": availability_policy,
            "row_count": row_count,
            "min_event_time": min_event_time.isoformat(),
            "max_event_time": max_event_time.isoformat(),
            "files": [file.to_dict() for file in files],
            "quality": _quality_to_dict(quality),
        }
        snapshot_id = hashlib.sha256(_canonical_json(body)).hexdigest()
        return cls(
            snapshot_id=snapshot_id,
            dataset_id=dataset_id,
            kind=kind,
            created_at=created_at,
            source_fetched_at=source_fetched_at,
            provider=dict(sorted(provider.items())),
            adjustment=adjustment,
            calendar_version=calendar_version,
            series_kind=series_kind,
            roll_policy=roll_policy,
            availability_policy=availability_policy,
            row_count=row_count,
            min_event_time=min_event_time,
            max_event_time=max_event_time,
            files=files,
            quality=quality,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "dataset_id": self.dataset_id,
            "kind": self.kind,
            "created_at": self.created_at.isoformat(),
            "source_fetched_at": self.source_fetched_at.isoformat(),
            "provider": self.provider,
            "adjustment": self.adjustment,
            "calendar_version": self.calendar_version,
            "series_kind": self.series_kind,
            "roll_policy": self.roll_policy,
            "availability_policy": self.availability_policy,
            "row_count": self.row_count,
            "min_event_time": self.min_event_time.isoformat(),
            "max_event_time": self.max_event_time.isoformat(),
            "files": [file.to_dict() for file in self.files],
            "quality": _quality_to_dict(self.quality),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict()).decode() + "\n"

    def to_evidence_ref(self) -> EvidenceRef:
        """Project this legacy schema into evidence without upgrading its trust."""

        return EvidenceRef.legacy(
            artifact_id=self.snapshot_id,
            digest=f"sha256:{self.snapshot_id}",
            manifest_schema_version=self.schema_version,
        )

    @classmethod
    def from_path(cls, path: Path) -> Self:
        raw = json.loads(path.read_text(encoding="utf-8"))
        quality_raw = raw["quality"]
        quality = QualityReport(
            row_count=raw["row_count"],
            issues=tuple(
                QualityIssue(
                    code=QualityCode(issue["code"]),
                    severity=QualitySeverity(issue["severity"]),
                    count=issue["count"],
                    sample_keys=tuple(issue["sample_keys"]),
                )
                for issue in quality_raw["issues"]
            ),
        )
        manifest = cls(
            schema_version=raw["schema_version"],
            snapshot_id=raw["snapshot_id"],
            dataset_id=raw["dataset_id"],
            kind=raw["kind"],
            created_at=datetime.fromisoformat(raw["created_at"]),
            source_fetched_at=datetime.fromisoformat(raw["source_fetched_at"]),
            provider=dict(raw["provider"]),
            adjustment=raw["adjustment"],
            calendar_version=raw["calendar_version"],
            series_kind=raw["series_kind"],
            roll_policy=raw["roll_policy"],
            availability_policy=raw["availability_policy"],
            row_count=raw["row_count"],
            min_event_time=datetime.fromisoformat(raw["min_event_time"]),
            max_event_time=datetime.fromisoformat(raw["max_event_time"]),
            files=tuple(SnapshotFile(**item) for item in raw["files"]),
            quality=quality,
        )
        expected = cls.create(
            dataset_id=manifest.dataset_id,
            kind=manifest.kind,
            created_at=manifest.created_at,
            source_fetched_at=manifest.source_fetched_at,
            provider=manifest.provider,
            adjustment=manifest.adjustment,
            calendar_version=manifest.calendar_version,
            series_kind=manifest.series_kind,
            roll_policy=manifest.roll_policy,
            availability_policy=manifest.availability_policy,
            row_count=manifest.row_count,
            min_event_time=manifest.min_event_time,
            max_event_time=manifest.max_event_time,
            files=manifest.files,
            quality=manifest.quality,
        )
        if expected.snapshot_id != manifest.snapshot_id:
            raise ValueError("snapshot manifest hash does not match its content")
        return manifest


def _quality_to_dict(report: QualityReport) -> dict[str, object]:
    return {
        "publishable": report.publishable,
        "issues": [
            {
                "code": issue.code.value,
                "severity": issue.severity.value,
                "count": issue.count,
                "sample_keys": list(issue.sample_keys),
            }
            for issue in report.issues
        ],
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

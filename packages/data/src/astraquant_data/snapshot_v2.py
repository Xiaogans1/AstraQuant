"""Formal snapshot v2 identities with stable content and concrete publication lineage."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Self

from astraquant_data.canonical import (
    CANONICAL_BAR_SCHEMA_VERSION,
    CanonicalBarObservation,
    validate_canonical_observations,
)
from astraquant_data.temporal import PitFidelity, VintageMode
from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

SNAPSHOT_MANIFEST_V2_SCHEMA = "astraquant.snapshot-manifest/v2"
SNAPSHOT_CONTENT_V2_SCHEMA = "astraquant.snapshot-content/v2"
_DATASET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _verified_digest(name: str, value: str) -> str:
    digest = validate_digest(name, value)
    if digest == f"sha256:{'0' * 64}":
        raise ValueError(f"{name} must not be a sentinel digest")
    return digest


def _digests(name: str, values: tuple[str, ...], *, required: bool) -> tuple[str, ...]:
    exact = tuple(sorted(_verified_digest(name, value) for value in values))
    if required and not exact:
        raise ValueError(f"{name} must not be empty")
    if len(set(exact)) != len(exact):
        raise ValueError(f"{name} must be unique")
    return exact


def _aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _object_list(name: str, value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _object_dict(name: str, value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return value


def _integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _stable_observation_projection(value: CanonicalBarObservation) -> dict[str, object]:
    return {
        "instrument_id": str(value.instrument_id),
        "frequency": value.frequency.value,
        "trading_date": value.trading_date.isoformat(),
        "interval_start": value.interval_start.isoformat(),
        "interval_end": value.interval_end.isoformat(),
        "event_time": value.event_time.isoformat(),
        "source_available_time": value.source_available_time.isoformat(),
        "source_revision_time": (
            None if value.source_revision_time is None else value.source_revision_time.isoformat()
        ),
        "source_revision_id": value.source_revision_id,
        "vintage_kind": value.vintage_kind.value,
        "availability_basis": value.availability_basis.value,
        "calendar_snapshot_id": value.calendar_snapshot_id,
        "value_hash": value.value_hash,
        "adjustment": value.adjustment.value,
        "units": list(value.units),
    }


def _canonical_rows_digest(observations: tuple[CanonicalBarObservation, ...]) -> str:
    projections = tuple(
        sorted(
            (_stable_observation_projection(value) for value in observations),
            key=canonical_json_bytes,
        )
    )
    return _digest(projections)


@dataclass(frozen=True, slots=True)
class SnapshotFileV2:
    path: str
    file_digest: str
    rows: int

    def __post_init__(self) -> None:
        pure = PurePosixPath(self.path)
        if not self.path or pure.is_absolute() or ".." in pure.parts or "\\" in self.path:
            raise ValueError("snapshot file path must be safe relative POSIX text")
        object.__setattr__(self, "file_digest", _verified_digest("file_digest", self.file_digest))
        if self.rows <= 0:
            raise ValueError("snapshot file rows must be positive")

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "file_digest": self.file_digest, "rows": self.rows}


@dataclass(frozen=True, slots=True)
class SnapshotContentV2:
    dataset_id: str
    canonical_schema: str
    row_count: int
    min_event_time: datetime
    max_event_time: datetime
    canonical_rows_digest: str
    data_vintage_cutoff: datetime
    availability_policy_id: str
    revision_policy_id: str
    vintage_mode: VintageMode
    pit_fidelity: PitFidelity
    coverage_digest: str
    quality_digest: str
    code_digest: str
    environment_digest: str
    parent_content_digests: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    content_digest: str
    schema_version: str = SNAPSHOT_CONTENT_V2_SCHEMA

    @classmethod
    def create(
        cls,
        *,
        dataset_id: str,
        observations: tuple[CanonicalBarObservation, ...] | list[CanonicalBarObservation],
        data_vintage_cutoff: datetime,
        availability_policy_id: str,
        revision_policy_id: str,
        vintage_mode: VintageMode,
        pit_fidelity: PitFidelity,
        coverage_digest: str,
        quality_digest: str,
        code_digest: str,
        environment_digest: str,
        parent_content_digests: tuple[str, ...] = (),
        evidence_digests: tuple[str, ...] = (),
    ) -> Self:
        if not _DATASET_ID_PATTERN.fullmatch(dataset_id):
            raise ValueError(f"invalid dataset_id: {dataset_id!r}")
        rows = validate_canonical_observations(observations)
        if not rows:
            raise ValueError("snapshot observations must not be empty")
        values: dict[str, object] = {
            "schema_version": SNAPSHOT_CONTENT_V2_SCHEMA,
            "dataset_id": dataset_id,
            "canonical_schema": CANONICAL_BAR_SCHEMA_VERSION,
            "row_count": len(rows),
            "min_event_time": min(value.event_time for value in rows).isoformat(),
            "max_event_time": max(value.event_time for value in rows).isoformat(),
            "canonical_rows_digest": _canonical_rows_digest(rows),
            "data_vintage_cutoff": _aware("data_vintage_cutoff", data_vintage_cutoff).isoformat(),
            "availability_policy_id": _verified_digest(
                "availability_policy_id", availability_policy_id
            ),
            "revision_policy_id": _verified_digest("revision_policy_id", revision_policy_id),
            "vintage_mode": vintage_mode.value,
            "pit_fidelity": pit_fidelity.value,
            "coverage_digest": _verified_digest("coverage_digest", coverage_digest),
            "quality_digest": _verified_digest("quality_digest", quality_digest),
            "code_digest": _verified_digest("code_digest", code_digest),
            "environment_digest": _verified_digest("environment_digest", environment_digest),
            "parent_content_digests": list(
                _digests(
                    "parent_content_digests",
                    parent_content_digests,
                    required=False,
                )
            ),
            "evidence_digests": list(_digests("evidence_digests", evidence_digests, required=True)),
        }
        return cls._from_body(values, expected_digest=_digest(values))

    @classmethod
    def _from_body(cls, body: dict[str, object], *, expected_digest: str) -> Self:
        if body.get("schema_version") != SNAPSHOT_CONTENT_V2_SCHEMA:
            raise ValueError("unknown snapshot content schema")
        actual_digest = _digest(body)
        if actual_digest != expected_digest:
            raise ValueError("snapshot content digest does not match content")
        return cls(
            dataset_id=str(body["dataset_id"]),
            canonical_schema=str(body["canonical_schema"]),
            row_count=_integer("row_count", body["row_count"]),
            min_event_time=_aware(
                "min_event_time", datetime.fromisoformat(str(body["min_event_time"]))
            ),
            max_event_time=_aware(
                "max_event_time", datetime.fromisoformat(str(body["max_event_time"]))
            ),
            canonical_rows_digest=_verified_digest(
                "canonical_rows_digest", str(body["canonical_rows_digest"])
            ),
            data_vintage_cutoff=_aware(
                "data_vintage_cutoff",
                datetime.fromisoformat(str(body["data_vintage_cutoff"])),
            ),
            availability_policy_id=_verified_digest(
                "availability_policy_id", str(body["availability_policy_id"])
            ),
            revision_policy_id=_verified_digest(
                "revision_policy_id", str(body["revision_policy_id"])
            ),
            vintage_mode=VintageMode(str(body["vintage_mode"])),
            pit_fidelity=PitFidelity(str(body["pit_fidelity"])),
            coverage_digest=_verified_digest("coverage_digest", str(body["coverage_digest"])),
            quality_digest=_verified_digest("quality_digest", str(body["quality_digest"])),
            code_digest=_verified_digest("code_digest", str(body["code_digest"])),
            environment_digest=_verified_digest(
                "environment_digest", str(body["environment_digest"])
            ),
            parent_content_digests=_digests(
                "parent_content_digests",
                tuple(
                    str(value)
                    for value in _object_list(
                        "parent_content_digests", body["parent_content_digests"]
                    )
                ),
                required=False,
            ),
            evidence_digests=_digests(
                "evidence_digests",
                tuple(
                    str(value)
                    for value in _object_list("evidence_digests", body["evidence_digests"])
                ),
                required=True,
            ),
            content_digest=actual_digest,
        )

    def body_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "canonical_schema": self.canonical_schema,
            "row_count": self.row_count,
            "min_event_time": self.min_event_time.isoformat(),
            "max_event_time": self.max_event_time.isoformat(),
            "canonical_rows_digest": self.canonical_rows_digest,
            "data_vintage_cutoff": self.data_vintage_cutoff.isoformat(),
            "availability_policy_id": self.availability_policy_id,
            "revision_policy_id": self.revision_policy_id,
            "vintage_mode": self.vintage_mode.value,
            "pit_fidelity": self.pit_fidelity.value,
            "coverage_digest": self.coverage_digest,
            "quality_digest": self.quality_digest,
            "code_digest": self.code_digest,
            "environment_digest": self.environment_digest,
            "parent_content_digests": list(self.parent_content_digests),
            "evidence_digests": list(self.evidence_digests),
        }

    def assert_matches_observations(
        self,
        observations: tuple[CanonicalBarObservation, ...] | list[CanonicalBarObservation],
    ) -> tuple[CanonicalBarObservation, ...]:
        rows = validate_canonical_observations(observations)
        matches = (
            bool(rows)
            and len(rows) == self.row_count
            and min(value.event_time for value in rows) == self.min_event_time
            and max(value.event_time for value in rows) == self.max_event_time
            and _canonical_rows_digest(rows) == self.canonical_rows_digest
        )
        if not matches:
            raise ValueError("snapshot content does not match observations")
        return rows

    def to_dict(self) -> dict[str, object]:
        return {"content_digest": self.content_digest, **self.body_dict()}


@dataclass(frozen=True, slots=True)
class SnapshotPublicationV2:
    created_at: datetime
    capture_digests: tuple[str, ...]
    raw_digests: tuple[str, ...]
    files: tuple[SnapshotFileV2, ...]
    parent_snapshot_ids: tuple[str, ...]
    supersedes_snapshot_id: str | None
    evidence_manifest_digest: str
    run_manifest_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _aware("created_at", self.created_at))
        object.__setattr__(
            self,
            "capture_digests",
            _digests("capture_digests", self.capture_digests, required=True),
        )
        object.__setattr__(
            self, "raw_digests", _digests("raw_digests", self.raw_digests, required=True)
        )
        exact_files = tuple(sorted(self.files, key=lambda value: value.path))
        if not exact_files or len({value.path for value in exact_files}) != len(exact_files):
            raise ValueError("files must be non-empty with unique paths")
        object.__setattr__(self, "files", exact_files)
        object.__setattr__(
            self,
            "parent_snapshot_ids",
            _digests("parent_snapshot_ids", self.parent_snapshot_ids, required=False),
        )
        if self.supersedes_snapshot_id is not None:
            object.__setattr__(
                self,
                "supersedes_snapshot_id",
                _verified_digest("supersedes_snapshot_id", self.supersedes_snapshot_id),
            )
        object.__setattr__(
            self,
            "evidence_manifest_digest",
            _verified_digest("evidence_manifest_digest", self.evidence_manifest_digest),
        )
        object.__setattr__(
            self,
            "run_manifest_digest",
            _verified_digest("run_manifest_digest", self.run_manifest_digest),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "created_at": self.created_at.isoformat(),
            "capture_digests": list(self.capture_digests),
            "raw_digests": list(self.raw_digests),
            "files": [value.to_dict() for value in self.files],
            "parent_snapshot_ids": list(self.parent_snapshot_ids),
            "supersedes_snapshot_id": self.supersedes_snapshot_id,
            "evidence_manifest_digest": self.evidence_manifest_digest,
            "run_manifest_digest": self.run_manifest_digest,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> Self:
        return cls(
            created_at=datetime.fromisoformat(str(value["created_at"])),
            capture_digests=tuple(
                str(item) for item in _object_list("capture_digests", value["capture_digests"])
            ),
            raw_digests=tuple(
                str(item) for item in _object_list("raw_digests", value["raw_digests"])
            ),
            files=tuple(
                SnapshotFileV2(
                    path=str(file_value["path"]),
                    file_digest=str(file_value["file_digest"]),
                    rows=_integer("files.rows", file_value["rows"]),
                )
                for file_value in (
                    _object_dict("files[]", item) for item in _object_list("files", value["files"])
                )
            ),
            parent_snapshot_ids=tuple(
                str(item)
                for item in _object_list("parent_snapshot_ids", value["parent_snapshot_ids"])
            ),
            supersedes_snapshot_id=(
                None
                if value["supersedes_snapshot_id"] is None
                else str(value["supersedes_snapshot_id"])
            ),
            evidence_manifest_digest=str(value["evidence_manifest_digest"]),
            run_manifest_digest=str(value["run_manifest_digest"]),
        )


@dataclass(frozen=True, slots=True)
class SnapshotManifestV2:
    snapshot_id: str
    content: SnapshotContentV2
    publication: SnapshotPublicationV2
    schema_version: str = SNAPSHOT_MANIFEST_V2_SCHEMA

    @classmethod
    def create(cls, content: SnapshotContentV2, publication: SnapshotPublicationV2) -> Self:
        body = {
            "schema_version": SNAPSHOT_MANIFEST_V2_SCHEMA,
            "content_digest": content.content_digest,
            "publication": publication.to_dict(),
        }
        return cls(snapshot_id=_digest(body), content=content, publication=publication)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "content": self.content.to_dict(),
            "publication": self.publication.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json_bytes(self.to_dict()).decode("utf-8") + "\n"

    @classmethod
    def from_path(cls, path: Path) -> Self:
        raw = _object_dict("manifest", json.loads(path.read_text(encoding="utf-8")))
        if raw.get("schema_version") != SNAPSHOT_MANIFEST_V2_SCHEMA:
            raise ValueError("unknown snapshot manifest schema")
        content_raw = dict(_object_dict("content", raw["content"]))
        claimed_content_digest = str(content_raw.pop("content_digest"))
        content = SnapshotContentV2._from_body(content_raw, expected_digest=claimed_content_digest)
        publication = SnapshotPublicationV2.from_dict(
            _object_dict("publication", raw["publication"])
        )
        expected = cls.create(content, publication)
        if expected.snapshot_id != raw.get("snapshot_id"):
            raise ValueError("snapshot digest does not match manifest publication")
        return expected

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from astraquant_data.canonical import (
    CanonicalBarInput,
    CanonicalBarObservation,
    CaptureRowLineage,
    normalize_bar,
)
from astraquant_data.snapshot_v2 import (
    SNAPSHOT_MANIFEST_V2_SCHEMA,
    SnapshotContentV2,
    SnapshotFileV2,
    SnapshotManifestV2,
    SnapshotPublicationV2,
)
from astraquant_data.temporal import PitFidelity, VintageMode
from astraquant_domain import (
    Adjustment,
    AvailabilityBasis,
    BarFrequency,
    InstrumentId,
    ObservationInterval,
    VintageKind,
)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _bar(
    *, received: datetime, capture_character: str, close: str = "10.5"
) -> CanonicalBarObservation:
    return normalize_bar(
        CanonicalBarInput(
            instrument_id=InstrumentId.parse("600000.SSE"),
            frequency=BarFrequency.DAY,
            trading_date=date(2010, 1, 4),
            source_available_time=datetime(2010, 1, 4, 7, 1, tzinfo=UTC),
            observed_received_time=received,
            recorded_time=received + timedelta(seconds=1),
            first_received_time=received,
            source_revision_time=None,
            source_revision_id=None,
            vintage_proven_time=received,
            vintage_kind=VintageKind.AS_DELIVERED_UNVERSIONED,
            availability_basis=AvailabilityBasis.SESSION_CLOSE,
            open=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal(close),
            volume=Decimal("1000"),
            turnover=Decimal("10500"),
            open_interest=None,
            settlement=None,
            adjustment=Adjustment.NONE,
            source_adjustment=Adjustment.NONE,
            units=("price=CNY", "turnover=CNY", "volume=share"),
        ),
        interval=ObservationInterval(
            interval_start=datetime(2010, 1, 4, 1, 30, tzinfo=UTC),
            interval_end=datetime(2010, 1, 4, 7, 0, tzinfo=UTC),
            event_time=datetime(2010, 1, 4, 7, 0, tzinfo=UTC),
            calendar_snapshot_id=_digest("1"),
        ),
        lineage=CaptureRowLineage(
            capture_id=_digest(capture_character),
            chunk_id=_digest("2"),
            row_index=0,
        ),
    )


def _content(*, bar=None, **changes: object) -> SnapshotContentV2:  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "dataset_id": "cn-equity-daily-formal",
        "observations": (
            bar
            or _bar(
                received=datetime(2026, 8, 11, tzinfo=UTC),
                capture_character="3",
            ),
        ),
        "data_vintage_cutoff": datetime(2026, 8, 11, 1, tzinfo=UTC),
        "availability_policy_id": _digest("4"),
        "revision_policy_id": _digest("5"),
        "vintage_mode": VintageMode.REPLAY_PIT_STRICT,
        "pit_fidelity": PitFidelity.OBSERVED_ONLY,
        "coverage_digest": _digest("6"),
        "quality_digest": _digest("7"),
        "code_digest": _digest("8"),
        "environment_digest": _digest("9"),
        "parent_content_digests": (_digest("a"),),
        "evidence_digests": (_digest("b"),),
    }
    values.update(changes)
    return SnapshotContentV2.create(**values)  # type: ignore[arg-type]


def _publication(
    *, capture: str = "c", file_digest: str = "d", minute: int = 0
) -> SnapshotPublicationV2:
    return SnapshotPublicationV2(
        created_at=datetime(2026, 8, 11, 2, minute, tzinfo=UTC),
        capture_digests=(_digest(capture),),
        raw_digests=(_digest("e"),),
        files=(
            SnapshotFileV2(
                path="market=cn/frequency=1d/trading_date=2010-01-04/part-0.parquet",
                file_digest=_digest(file_digest),
                rows=1,
            ),
        ),
        parent_snapshot_ids=(_digest("f"),),
        supersedes_snapshot_id=None,
        evidence_manifest_digest=_digest("1"),
        run_manifest_digest=_digest("2"),
    )


def test_refetch_keeps_content_identity_but_changes_publication_identity() -> None:
    first_bar = _bar(received=datetime(2026, 8, 11, tzinfo=UTC), capture_character="3")
    refetched_bar = _bar(received=datetime(2026, 8, 12, tzinfo=UTC), capture_character="4")
    first_content = _content(bar=first_bar)
    refetched_content = _content(bar=refetched_bar)
    first = SnapshotManifestV2.create(first_content, _publication())
    refetched = SnapshotManifestV2.create(
        refetched_content, _publication(capture="a", file_digest="b", minute=1)
    )

    assert first_content.content_digest == refetched_content.content_digest
    assert first.snapshot_id != refetched.snapshot_id
    assert first.schema_version == SNAPSHOT_MANIFEST_V2_SCHEMA


@pytest.mark.parametrize(
    "changes",
    [
        {"data_vintage_cutoff": datetime(2026, 8, 12, tzinfo=UTC)},
        {"availability_policy_id": _digest("c")},
        {"revision_policy_id": _digest("c")},
        {"vintage_mode": VintageMode.REPLAY_AS_DELIVERED},
        {"pit_fidelity": PitFidelity.NOMINAL_ONLY},
        {"coverage_digest": _digest("c")},
        {"quality_digest": _digest("c")},
        {"code_digest": _digest("c")},
        {"environment_digest": _digest("c")},
        {"parent_content_digests": (_digest("c"),)},
        {"evidence_digests": (_digest("c"),)},
    ],
)
def test_content_identity_binds_every_semantic_policy(changes: dict[str, object]) -> None:
    assert _content(**changes).content_digest != _content().content_digest


def test_value_change_alters_content_and_file_change_alters_snapshot() -> None:
    original = _content()
    changed_value = _content(
        bar=_bar(
            received=datetime(2026, 8, 11, tzinfo=UTC),
            capture_character="3",
            close="10.6",
        )
    )
    first = SnapshotManifestV2.create(original, _publication(file_digest="d"))
    changed_file = SnapshotManifestV2.create(original, _publication(file_digest="c"))

    assert changed_value.content_digest != original.content_digest
    assert changed_file.snapshot_id != first.snapshot_id


def test_manifest_round_trip_rejects_tampering(tmp_path: Path) -> None:
    manifest = SnapshotManifestV2.create(_content(), _publication())
    path = tmp_path / "manifest.json"
    path.write_text(manifest.to_json(), encoding="utf-8")

    assert SnapshotManifestV2.from_path(path) == manifest

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["content"]["quality_digest"] = _digest("c")
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        SnapshotManifestV2.from_path(path)


def test_manifest_rejects_missing_or_sentinel_lineage_digest() -> None:
    with pytest.raises(ValueError, match="capture_digests"):
        replace(_publication(), capture_digests=())
    with pytest.raises(ValueError, match="file_digest"):
        SnapshotFileV2(path="part.parquet", file_digest=_digest("0"), rows=1)

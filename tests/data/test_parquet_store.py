import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from astraquant_data.parquet_store import (
    CanonicalSnapshotStoreV2,
    ParquetSnapshotStore,
    SnapshotRejected,
)
from astraquant_data.snapshot_v2 import SNAPSHOT_MANIFEST_V2_SCHEMA, SnapshotManifestV2
from astraquant_domain import FixedClock

from .factories import make_bar
from .test_snapshot_v2 import _bar, _content, _digest

PROVIDER = {
    "id": "fixture",
    "interface": "synthetic_csv",
    "version": "1",
}


def test_publish_is_immutable_partitioned_and_reproducible(tmp_path: Path) -> None:
    clock = FixedClock(datetime(2026, 7, 28, tzinfo=UTC))
    store = ParquetSnapshotStore(tmp_path, clock=clock)

    first = store.publish_bars(
        dataset_id="cn-equity-daily",
        bars=[make_bar(availability_estimated=False)],
        provider=PROVIDER,
        calendar_version="fixture-calendar-v1",
        availability_policy="fixture_known_at_close_plus_1m",
    )
    second = store.publish_bars(
        dataset_id="cn-equity-daily",
        bars=[make_bar(availability_estimated=False)],
        provider=PROVIDER,
        calendar_version="fixture-calendar-v1",
        availability_policy="fixture_known_at_close_plus_1m",
    )

    assert second.snapshot_id == first.snapshot_id
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["snapshot_id"] == first.snapshot_id
    assert manifest["row_count"] == 1
    assert manifest["files"][0]["path"].startswith(
        "market=cn/asset_class=equity/frequency=1d/trading_date=2026-07-24/"
    )
    assert (first.snapshot_path / manifest["files"][0]["path"]).is_file()
    assert not any((tmp_path / ".staging").iterdir())


def test_rejected_snapshot_leaves_no_visible_manifest(tmp_path: Path) -> None:
    store = ParquetSnapshotStore(
        tmp_path,
        clock=FixedClock(datetime(2026, 7, 28, tzinfo=UTC)),
    )
    duplicate = make_bar(symbol="RB2610.SHFE", availability_estimated=False)

    with pytest.raises(SnapshotRejected):
        store.publish_bars(
            dataset_id="cn-futures-daily",
            bars=[duplicate, duplicate],
            provider=PROVIDER,
            calendar_version="fixture-calendar-v1",
            availability_policy="fixture_known_at_close_plus_1m",
        )

    assert list(tmp_path.rglob("manifest.json")) == []
    assert not any((tmp_path / ".staging").iterdir())


def test_dataset_id_cannot_escape_the_data_root(tmp_path: Path) -> None:
    store = ParquetSnapshotStore(
        tmp_path,
        clock=FixedClock(datetime(2026, 7, 28, tzinfo=UTC)),
    )

    with pytest.raises(ValueError, match="dataset_id"):
        store.publish_bars(
            dataset_id="../escape",
            bars=[make_bar()],
            provider=PROVIDER,
            calendar_version="fixture-calendar-v1",
            availability_policy="estimated",
        )


def _publish_v2(tmp_path: Path):  # type: ignore[no-untyped-def]
    observation = _bar(
        received=datetime(2026, 8, 11, tzinfo=UTC),
        capture_character="3",
    )
    content = _content(bar=observation)
    published = CanonicalSnapshotStoreV2(tmp_path).publish(
        content=content,
        observations=[observation],
        created_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
        capture_digests=(_digest("c"),),
        raw_digests=(_digest("d"),),
        evidence_manifest_digest=_digest("e"),
        run_manifest_digest=_digest("f"),
    )
    return observation, content, published


def test_v2_publish_is_atomic_canonical_and_idempotent(tmp_path: Path) -> None:
    observation, content, first = _publish_v2(tmp_path)
    _, _, second = _publish_v2(tmp_path)

    assert first.snapshot_id == second.snapshot_id
    assert first.manifest.content.content_digest == content.content_digest
    assert first.manifest.schema_version == SNAPSHOT_MANIFEST_V2_SCHEMA
    assert SnapshotManifestV2.from_path(first.manifest_path) == first.manifest
    assert len(list((tmp_path / "formal" / "datasets").rglob("manifest.json"))) == 1
    file_path = first.snapshot_path / first.manifest.publication.files[0].path
    table = pq.read_table(file_path)
    assert table.num_rows == 1
    assert table.schema.metadata == {b"schema_version": observation.schema_version.encode("ascii")}
    assert not any((tmp_path / "formal" / ".staging").iterdir())


def test_v2_publish_rejects_content_observation_mismatch(tmp_path: Path) -> None:
    observation = _bar(
        received=datetime(2026, 8, 11, tzinfo=UTC),
        capture_character="3",
    )
    content = _content(bar=observation)
    changed_observation = _bar(
        received=datetime(2026, 8, 11, tzinfo=UTC),
        capture_character="3",
        close="10.6",
    )

    with pytest.raises(ValueError, match="content does not match observations"):
        CanonicalSnapshotStoreV2(tmp_path).publish(
            content=content,
            observations=[changed_observation],
            created_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
            capture_digests=(_digest("c"),),
            raw_digests=(_digest("d"),),
            evidence_manifest_digest=_digest("e"),
            run_manifest_digest=_digest("f"),
        )

    assert list((tmp_path / "formal").rglob("manifest.json")) == []


def test_v2_write_failure_never_exposes_partial_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observation = _bar(
        received=datetime(2026, 8, 11, tzinfo=UTC),
        capture_character="3",
    )
    content = _content(bar=observation)

    def fail_write(*args: object, **kwargs: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(pq, "write_table", fail_write)
    with pytest.raises(OSError, match="simulated disk failure"):
        CanonicalSnapshotStoreV2(tmp_path).publish(
            content=content,
            observations=[observation],
            created_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
            capture_digests=(_digest("c"),),
            raw_digests=(_digest("d"),),
            evidence_manifest_digest=_digest("e"),
            run_manifest_digest=_digest("f"),
        )

    assert list((tmp_path / "formal").rglob("manifest.json")) == []
    assert not any((tmp_path / "formal" / ".staging").iterdir())

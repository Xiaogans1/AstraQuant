from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from astraquant_data.features import FeatureSnapshotStore
from astraquant_domain import FeatureFrame, FeatureRow, InstrumentId


def _frame(*, second_value: float = 1.2) -> FeatureFrame:
    decision = datetime(2026, 7, 24, 7, 2, tzinfo=UTC)
    return FeatureFrame(
        decision_time=decision,
        definition_version="baseline-v1",
        rows=(
            FeatureRow(
                InstrumentId.parse("600000.SSE"),
                decision - timedelta(minutes=2),
                decision - timedelta(minutes=1),
                {"return_1d": 0.01, "volume_z": 0.8},
            ),
            FeatureRow(
                InstrumentId.parse("000001.SZSE"),
                decision - timedelta(minutes=1),
                decision,
                {"return_1d": 0.02, "volume_z": second_value},
            ),
        ),
    )


def test_feature_snapshot_identity_is_reproducible(tmp_path: Path) -> None:
    store = FeatureSnapshotStore(tmp_path)

    first = store.publish(
        _frame(),
        input_snapshot_ids=["bars-b", "bars-a"],
        code_revision="abc123",
        parameters={"window": 20, "clip": 3.0},
    )
    second = store.publish(
        _frame(),
        input_snapshot_ids=["bars-a", "bars-b"],
        code_revision="abc123",
        parameters={"clip": 3.0, "window": 20},
    )
    changed = store.publish(
        _frame(second_value=1.3),
        input_snapshot_ids=["bars-a", "bars-b"],
        code_revision="abc123",
        parameters={"clip": 3.0, "window": 20},
    )

    assert second.snapshot_id == first.snapshot_id
    assert changed.snapshot_id != first.snapshot_id
    assert first.manifest_path.is_file()
    assert first.parquet_path.is_file()


def test_loading_with_an_earlier_cutoff_hides_later_features(tmp_path: Path) -> None:
    store = FeatureSnapshotStore(tmp_path)
    published = store.publish(
        _frame(),
        input_snapshot_ids=["bars-a"],
        code_revision="abc123",
        parameters={},
    )
    cutoff = datetime(2026, 7, 24, 7, 1, tzinfo=UTC)

    loaded = store.load(published.manifest_path, decision_time=cutoff)

    assert loaded.decision_time == cutoff
    assert [str(row.instrument_id) for row in loaded.rows] == ["600000.SSE"]


@pytest.mark.parametrize("code_revision", ["", "  ", "abc123-dirty"])
def test_feature_snapshot_rejects_unusable_code_revision(
    tmp_path: Path,
    code_revision: str,
) -> None:
    with pytest.raises(ValueError, match="code_revision"):
        FeatureSnapshotStore(tmp_path).publish(
            _frame(),
            input_snapshot_ids=["bars-a"],
            code_revision=code_revision,
            parameters={},
        )

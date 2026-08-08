from datetime import UTC, datetime, timedelta

import pytest

from astraquant_domain import FeatureFrame, FeatureRow, InstrumentId


def test_feature_row_rejects_a_value_available_after_decision_time() -> None:
    decision = datetime(2026, 7, 24, 7, 1, tzinfo=UTC)
    row = FeatureRow(
        instrument_id=InstrumentId.parse("600000.SSE"),
        event_time=decision,
        available_time=decision + timedelta(seconds=1),
        values={"return_1d": 0.01},
    )

    with pytest.raises(ValueError, match="decision_time"):
        FeatureFrame(
            decision_time=decision,
            definition_version="baseline-v1",
            rows=(row,),
        )


def test_feature_frame_requires_one_stable_feature_schema() -> None:
    now = datetime(2026, 7, 24, 7, 1, tzinfo=UTC)
    first = FeatureRow(
        InstrumentId.parse("600000.SSE"),
        now,
        now,
        {"return_1d": 0.01},
    )
    second = FeatureRow(
        InstrumentId.parse("000001.SZSE"),
        now,
        now,
        {"volume_z": 1.2},
    )

    with pytest.raises(ValueError, match="feature schema"):
        FeatureFrame(
            decision_time=now,
            definition_version="baseline-v1",
            rows=(first, second),
        )


def test_feature_values_are_immutable_and_canonically_ordered() -> None:
    now = datetime(2026, 7, 24, 7, 1, tzinfo=UTC)
    values = {"volume_z": 1.2, "return_1d": 0.01}
    row = FeatureRow(InstrumentId.parse("600000.SSE"), now, now, values)
    values["return_1d"] = 99

    assert tuple(row.values) == ("return_1d", "volume_z")
    assert row.values["return_1d"] == 0.01
    with pytest.raises(TypeError):
        row.values["return_1d"] = 1.0  # type: ignore[index]

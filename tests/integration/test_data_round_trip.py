from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from tests.integration.test_runtime_round_trip import (
    running_runtime,
    wait_for_terminal_task,
)

from astraquant_data.features import (
    BASELINE_FEATURE_VERSION,
    FeatureSnapshotStore,
    build_baseline_features,
)
from astraquant_data.query import MarketDataQuery


def test_fixture_import_catalog_query_and_feature_snapshot_round_trip(
    tmp_path: Path,
) -> None:
    with running_runtime(tmp_path) as (_, client):
        equity_task = _import_fixture(client, "600000.SSE", "phase2-e2e-equity-0001")
        futures_task = _import_fixture(client, "RB0.SHFE", "phase2-e2e-futures-0001")

        _assert_published_snapshot(client, equity_task)
        _assert_published_snapshot(client, futures_task)

        snapshot_id = equity_task["result"]["snapshot_id"]
        dataset_id = equity_task["result"]["dataset_id"]
        manifest_path = (
            tmp_path
            / "data"
            / "datasets"
            / dataset_id
            / "snapshots"
            / snapshot_id
            / "manifest.json"
        )
        query = MarketDataQuery.from_manifest(
            data_root=tmp_path / "data",
            manifest_path=manifest_path,
        )
        try:
            decision_time = datetime(2026, 7, 24, 7, 2, tzinfo=UTC)
            bars = query.bars_as_of(
                instrument_ids=["600000.SSE"],
                decision_time=decision_time,
            )
        finally:
            query.close()

        frame = build_baseline_features(bars, decision_time)
        assert frame.definition_version == BASELINE_FEATURE_VERSION
        assert len(frame.rows) == 4
        assert tuple(frame.rows[-1].values) == (
            "return_1d",
            "volume_change_1d",
        )

        store = FeatureSnapshotStore(tmp_path / "data")
        first = store.publish(
            frame,
            input_snapshot_ids=[snapshot_id],
            code_revision="phase2-acceptance",
            parameters={"builder": BASELINE_FEATURE_VERSION},
        )
        repeated = store.publish(
            frame,
            input_snapshot_ids=[snapshot_id],
            code_revision="phase2-acceptance",
            parameters={"builder": BASELINE_FEATURE_VERSION},
        )
        assert repeated.snapshot_id == first.snapshot_id


def _import_fixture(
    client: httpx.Client,
    instrument_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    response = client.post(
        "/v1/data/imports",
        headers={"Idempotency-Key": idempotency_key},
        json={
            "provider": "fixture",
            "instrument_id": instrument_id,
            "frequency": "1d",
            "start": "2026-07-20",
            "end": "2026-07-24",
            "adjustment": "none",
        },
    )
    assert response.status_code == 201
    task = wait_for_terminal_task(client, response.json()["task_id"])
    assert task["status"] == "SUCCEEDED"
    return task


def _assert_published_snapshot(
    client: httpx.Client,
    task: dict[str, Any],
) -> None:
    snapshots = (
        client.get(
            f"/v1/data/datasets/{task['result']['dataset_id']}/snapshots",
        )
        .raise_for_status()
        .json()
    )
    assert snapshots[0]["snapshot_id"] == task["result"]["snapshot_id"]
    assert snapshots[0]["status"] == "PUBLISHED"
    assert snapshots[0]["row_count"] > 0

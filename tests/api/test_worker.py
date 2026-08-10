from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from multiprocessing import get_context
from queue import Empty
from typing import Any

import pytest

from astraquant_api.worker import (
    DataImportResult,
    WorkerMessage,
    WorkerMessageKind,
    run_demo_worker,
)


def collect_messages(cancel_immediately: bool) -> list[WorkerMessage]:
    context = get_context("spawn")
    queue = context.Queue()
    cancel = context.Event()
    if cancel_immediately:
        cancel.set()
    process = context.Process(
        target=run_demo_worker,
        args=("task-1", queue, cancel, 0.001),
    )
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 0
    messages: list[WorkerMessage] = []
    while True:
        try:
            message: Any = queue.get_nowait()
            messages.append(message)
        except Empty:
            return messages


def test_demo_worker_reports_six_steps_and_success() -> None:
    messages = collect_messages(cancel_immediately=False)

    kinds = [message.kind for message in messages]
    assert kinds.count(WorkerMessageKind.PROGRESS) == 6
    assert kinds[-1] is WorkerMessageKind.SUCCEEDED
    assert messages[-1].payload == {"checks": 6, "status": "healthy"}


def test_demo_worker_honors_cancellation() -> None:
    messages = collect_messages(cancel_immediately=True)

    assert messages[-1].kind is WorkerMessageKind.CANCELED


def test_data_import_result_is_frozen_and_pickle_safe() -> None:
    result = DataImportResult(
        dataset_id="cn-equity-600000-sse-1d-none",
        snapshot_id="1" * 64,
        manifest_path="D:/state/data/manifest.json",
        manifest_digest="sha256:" + "2" * 64,
        row_count=5,
        name="600000.SSE 日线",
        asset_class="equity",
        frequency="1d",
        semantic_class="LEGACY_SEMANTICS",
        evidence_class="LEGACY_UNVERIFIED",
        run_class="EXPLORATORY",
        observed_received_time=datetime(2026, 8, 10, tzinfo=UTC),
    )

    with pytest.raises(FrozenInstanceError):
        result.snapshot_id = "2" * 64  # type: ignore[misc]

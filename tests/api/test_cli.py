from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from astraquant_api.database import create_database, migrate_database
from astraquant_api.repository import TaskRepository
from astraquant_api.task_model import TaskRecord, TaskStatus


def test_ready_message_uses_bound_port_after_recovery(tmp_path: Path) -> None:
    token = "c" * 43
    database_path = tmp_path / "state" / "astraquant.sqlite3"
    database_path.parent.mkdir(parents=True)
    database_url = f"sqlite:///{database_path}"
    migrate_database(database_url)
    engine = create_database(database_url)
    repository = TaskRepository(engine)
    task = TaskRecord.create("demo.self_check", "cli-recovery")
    repository.create(task, event_type="task.created")
    running = task.evolve(
        status=TaskStatus.RUNNING,
        current_step="working",
        started_at=datetime.now(UTC),
    )
    assert repository.update(
        running,
        expected_revision=task.revision,
        event_type="task.started",
    )
    engine.dispose()

    environment = os.environ.copy()
    environment.update(
        {
            "ASTRAQUANT_SESSION_TOKEN": token,
            "ASTRAQUANT_STATE_DIR": str(tmp_path),
            "PYTHONUNBUFFERED": "1",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "astraquant_api.cli", "serve"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    try:
        assert process.stdout is not None
        ready = json.loads(process.stdout.readline())
        assert set(ready) == {"type", "protocol_version", "host", "port", "pid"}
        assert ready["port"] > 0
        base_url = f"http://127.0.0.1:{ready['port']}"
        headers = {"Authorization": f"Bearer {token}"}

        with httpx.Client(trust_env=False, timeout=5) as client:
            recovered = client.get(
                f"{base_url}/v1/tasks/{task.task_id}",
                headers=headers,
            )
            assert recovered.status_code == 200
            assert recovered.json()["status"] == "INTERRUPTED"

            shutdown = client.post(
                f"{base_url}/internal/shutdown",
                headers=headers,
            )
        assert shutdown.status_code == 202
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

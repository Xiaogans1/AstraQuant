from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest


@contextmanager
def running_runtime(state_dir: Path) -> Iterator[tuple[subprocess.Popen[str], httpx.Client]]:
    token = secrets.token_urlsafe(32)
    assert len(token) == 43
    environment = os.environ.copy()
    environment.update(
        {
            "ASTRAQUANT_SESSION_TOKEN": token,
            "ASTRAQUANT_STATE_DIR": str(state_dir),
            "PYTHONUNBUFFERED": "1",
        }
    )
    executable = sys.executable
    if sys.platform == "win32":
        virtual_environment = Path(sys.prefix)
        configuration = (virtual_environment / "pyvenv.cfg").read_text(encoding="utf-8")
        home = ""
        for line in configuration.splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "home":
                home = value.strip()
                break
        if not home:
            raise AssertionError("virtual environment does not declare its base interpreter")
        executable = str(Path(home) / "python.exe")
        repository_root = Path(__file__).resolve().parents[2]
        python_paths = [
            virtual_environment / "Lib" / "site-packages",
            repository_root / "packages" / "api" / "src",
            repository_root / "packages" / "data" / "src",
            repository_root / "packages" / "domain" / "src",
            repository_root / "packages" / "paper" / "src",
            repository_root / "packages" / "quant" / "src",
        ]
        environment["PYTHONPATH"] = os.pathsep.join(map(str, python_paths))
        environment["PYTHONNOUSERSITE"] = "1"
    process = subprocess.Popen(
        [executable, "-m", "astraquant_api.cli", "serve"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    client: httpx.Client | None = None
    try:
        assert process.stdout is not None
        ready_line = process.stdout.readline()
        if not ready_line:
            stderr = "" if process.stderr is None else process.stderr.read()
            raise AssertionError(f"runtime exited before ready handshake: {stderr}")
        ready = json.loads(ready_line)
        assert ready["type"] == "ready"
        assert ready["protocol_version"] == 1
        assert ready["host"] == "127.0.0.1"
        assert ready["pid"] == process.pid
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{ready['port']}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=2,
            trust_env=False,
        )
        wait_until_healthy(client)
        yield process, client
    finally:
        if client is not None:
            client.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def wait_until_healthy(client: httpx.Client) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise AssertionError("runtime health endpoint did not become ready")


def wait_for_terminal_task(client: httpx.Client, task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        task: dict[str, Any] = client.get(f"/v1/tasks/{task_id}").raise_for_status().json()
        if task["status"] in {"SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"}:
            return task
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not reach a terminal state")


def test_runtime_completes_a_real_task_and_shuts_down(tmp_path: Path) -> None:
    with running_runtime(tmp_path) as (process, client):
        health = client.get("/health").raise_for_status().json()
        assert health["status"] == "ok"

        created = (
            client.post(
                "/v1/tasks/demo",
                headers={"Idempotency-Key": "integration-complete"},
            )
            .raise_for_status()
            .json()
        )
        task = wait_for_terminal_task(client, created["task_id"])
        assert task["status"] == "SUCCEEDED"
        assert task["progress"] == 100
        assert task["result"] == {"checks": 6, "status": "healthy"}

        response = client.post("/internal/shutdown")
        assert response.status_code == 202
        assert process.wait(timeout=10) == 0

    assert (tmp_path / "state" / "astraquant.sqlite3").exists()
    assert list((tmp_path / "logs").glob("*.jsonl"))


def test_runtime_cancels_a_real_task(tmp_path: Path) -> None:
    with running_runtime(tmp_path) as (process, client):
        created = (
            client.post(
                "/v1/tasks/demo",
                headers={"Idempotency-Key": "integration-cancel"},
            )
            .raise_for_status()
            .json()
        )
        requested = client.post(f"/v1/tasks/{created['task_id']}/cancel").raise_for_status().json()
        assert requested["status"] == "CANCEL_REQUESTED"

        canceled = wait_for_terminal_task(client, created["task_id"])
        assert canceled["status"] == "CANCELED"
        assert canceled["result"] is None

        client.post("/internal/shutdown").raise_for_status()
        assert process.wait(timeout=10) == 0


@pytest.mark.windows_runtime
def test_runtime_recovers_an_active_task_as_interrupted(tmp_path: Path) -> None:
    with running_runtime(tmp_path) as (first_process, first_client):
        created = (
            first_client.post(
                "/v1/tasks/demo",
                headers={"Idempotency-Key": "integration-recovery"},
            )
            .raise_for_status()
            .json()
        )
        assert created["status"] == "RUNNING"
        first_process.terminate()
        first_process.wait(timeout=5)

    with running_runtime(tmp_path) as (second_process, second_client):
        recovered = second_client.get(f"/v1/tasks/{created['task_id']}").raise_for_status().json()
        assert recovered["status"] == "INTERRUPTED"
        assert recovered["current_step"] == "interrupted"
        second_client.post("/internal/shutdown").raise_for_status()
        assert second_process.wait(timeout=10) == 0

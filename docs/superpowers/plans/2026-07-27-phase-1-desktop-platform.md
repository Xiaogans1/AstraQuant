# Phase 1 Desktop Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a development-mode Tauri desktop that securely starts a loopback FastAPI service, runs and cancels a real spawned demo worker, persists task history and settings in SQLite, and presents the result through the Astra Minimal/Light React workspace.

**Architecture:** Keep platform task and persistence logic in the `astraquant-api` Python package, expose only versioned loopback HTTP contracts, and let the Tauri Rust shell own the service process and session token. React obtains connection metadata through a Tauri command and uses authenticated polling; workers communicate with the service through process-safe queues and never write SQLite directly.

**Tech Stack:** Python 3.12, uv, FastAPI 0.140, Pydantic 2.13, SQLAlchemy 2.0, Alembic 1.18, Tauri 2.11, Rust 1.96, React 19.2, TypeScript 7, Vite 8, TanStack Query 5, Vitest 4, pnpm 11.

---

## Execution rules

- Work in `.worktrees/phase-1-desktop-platform` on branch
  `feature/phase-1-desktop-platform`.
- Follow red-green-refactor for each behavior task. Record the expected failure before adding
  implementation.
- Commit only the files named by the current task.
- Never add `.astraquant/`, SQLite files, JSONL logs, `node_modules/`, Rust `target/`, tokens,
  credentials, generated screenshots, or `.superpowers/`.
- Run the repository policy before every push.
- Push only the feature branch and open a Draft PR. Do not merge it automatically.

## Planned file map

```text
package.json                         Root pnpm commands and pinned package manager
pnpm-workspace.yaml                  Node workspace membership
pnpm-lock.yaml                       Reproducible Node dependency graph
pyproject.toml                       Python workspace and quality targets
uv.lock                              Reproducible Python dependency graph

packages/api/
  pyproject.toml                     FastAPI package and console entry point
  alembic.ini                        Migration runner configuration
  migrations/
    env.py                           SQLAlchemy metadata bridge
    script.py.mako                   Alembic revision template
    versions/0001_platform.py        Initial tasks/events/settings schema
  src/astraquant_api/
    __init__.py                      Public package metadata
    config.py                        Validated process environment
    task_model.py                    Task states, records, transitions
    database.py                      Engine creation and migration entry point
    repository.py                    SQLite task/settings persistence
    worker.py                        Spawned demo worker protocol
    supervisor.py                    Worker lifecycle and queue consumption
    logging.py                       Redacted JSONL logging and activity buffer
    schemas.py                       Versioned HTTP request/response models
    app.py                           FastAPI application factory and routes
    cli.py                           Loopback server, ready handshake, shutdown

apps/desktop/
  package.json                       React/Tauri dependencies and scripts
  index.html                         Vite entry document
  tsconfig.json                      Strict TypeScript configuration
  vite.config.ts                     Vite and Vitest configuration
  src/
    main.tsx                         React bootstrap
    App.tsx                          Runtime bootstrap and workspace routing
    api/contracts.ts                 HTTP contract types
    api/client.ts                    Authenticated fetch client
    api/queries.ts                   TanStack Query hooks and polling
    runtime/tauri.ts                 Tauri command adapter
    theme/tokens.css                 Fixed semantic and theme tokens
    theme/theme.ts                   Theme preference application
    components/                      Focused visual components
    pages/                           Overview, tasks, activity, settings
    styles/app.css                   Workspace layout and responsive rules
    test/setup.ts                    DOM test setup
  src-tauri/
    Cargo.toml                       Tauri and process dependencies
    build.rs                         Tauri build hook
    tauri.conf.json                  Development desktop configuration
    capabilities/default.json       Minimum Tauri permissions
    src/main.rs                      Binary entry
    src/lib.rs                       App setup and commands
    src/handshake.rs                 Ready-message parser and validation
    src/runtime.rs                   Child process ownership and shutdown

tests/api/                           Python unit and integration tests
.github/workflows/ci.yml             Python, frontend and Rust quality gates
README.md                            Phase 1 development quick start
```

### Task 1: Extend the polyglot workspace

**Files:**
- Modify: `docs/superpowers/specs/2026-07-27-phase-1-desktop-platform-design.md`
- Modify: `pyproject.toml`
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `packages/api/pyproject.toml`
- Create: `packages/api/src/astraquant_api/__init__.py`
- Modify: `uv.lock`
- Create: `pnpm-lock.yaml`

- [x] **Step 1: Mark the approved design**

Change the specification header to:

```markdown
日期：2026-07-27
状态：已批准
```

- [x] **Step 2: Add the root Node workspace**

Create `package.json`:

```json
{
  "name": "astraquant",
  "private": true,
  "packageManager": "pnpm@11.9.0",
  "engines": {
    "node": ">=24.0.0"
  },
  "scripts": {
    "dev": "pnpm --dir apps/desktop tauri dev",
    "frontend:check": "pnpm --dir apps/desktop check",
    "frontend:test": "pnpm --dir apps/desktop test",
    "rust:check": "cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml",
    "rust:test": "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml"
  }
}
```

Create `pnpm-workspace.yaml`:

```yaml
packages:
  - apps/*
```

- [x] **Step 3: Register the API package in uv**

Update the root workspace:

```toml
[tool.uv.workspace]
members = ["packages/domain", "packages/api"]
```

Add API and migration sources to Ruff and mypy:

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
src = ["packages/domain/src", "packages/api/src"]

[tool.ruff.lint.isort]
known-first-party = ["astraquant_api", "astraquant_domain", "tools"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["packages/domain/src", "packages/api/src", "tools", "tests"]
```

Add HTTP test support to the root development group:

```toml
[dependency-groups]
dev = [
  "httpx>=0.28,<1",
  "mypy>=1.19,<2",
  "pytest>=9.1,<10",
  "ruff>=0.14,<1",
]
```

Create `packages/api/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "astraquant-api"
version = "0.1.0"
description = "Local control service for AstraQuant"
requires-python = ">=3.12,<3.13"
dependencies = [
  "alembic>=1.18,<2",
  "astraquant-domain",
  "fastapi>=0.140,<1",
  "pydantic>=2.13,<3",
  "sqlalchemy>=2.0,<3",
  "structlog>=26.1,<27",
  "uvicorn>=0.51,<1",
]

[project.scripts]
astraquant-api = "astraquant_api.cli:main"

[tool.uv.sources]
astraquant-domain = { workspace = true }

[tool.hatch.build.targets.wheel]
packages = ["src/astraquant_api"]
```

Create `packages/api/src/astraquant_api/__init__.py`:

```python
"""Local control-plane package for AstraQuant."""

__version__ = "0.1.0"
```

- [x] **Step 4: Lock and synchronize both ecosystems**

Run:

```powershell
uv lock
uv sync --locked --all-packages
pnpm install
uv run python -c "import astraquant_api; print(astraquant_api.__version__)"
```

Expected: dependency synchronization succeeds and prints `0.1.0`.

- [x] **Step 5: Run existing gates**

Run:

```powershell
uv run ruff check .
uv run mypy
uv run pytest
uv run python -m tools.repository_policy
git diff --check
```

Expected: existing 29 tests pass and repository policy passes.

- [x] **Step 6: Commit the workspace**

```powershell
git add docs/superpowers/specs/2026-07-27-phase-1-desktop-platform-design.md `
  pyproject.toml package.json pnpm-workspace.yaml pnpm-lock.yaml uv.lock packages/api
git commit -m "build: 扩展桌面平台工作区"
```

### Task 2: Define platform task contracts

**Files:**
- Create: `tests/api/test_task_model.py`
- Create: `packages/api/src/astraquant_api/task_model.py`
- Modify: `packages/api/src/astraquant_api/__init__.py`

- [x] **Step 1: Write failing task-state tests**

Create `tests/api/test_task_model.py`:

```python
from datetime import UTC, datetime
from uuid import UUID

import pytest

from astraquant_api.task_model import (
    ACTIVE_TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
    InvalidTaskTransition,
    TaskRecord,
    TaskStatus,
    transition_task,
)


def test_create_pending_task() -> None:
    task = TaskRecord.create("demo.self_check", "idem-1")

    assert UUID(task.task_id)
    assert UUID(task.correlation_id)
    assert task.status is TaskStatus.PENDING
    assert task.progress == 0
    assert task.revision == 0
    assert task.idempotency_key == "idem-1"
    assert task.created_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.RUNNING),
        (TaskStatus.PENDING, TaskStatus.CANCELED),
        (TaskStatus.PENDING, TaskStatus.INTERRUPTED),
        (TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED),
        (TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
        (TaskStatus.RUNNING, TaskStatus.FAILED),
        (TaskStatus.CANCEL_REQUESTED, TaskStatus.CANCELED),
    ],
)
def test_allow_valid_transition(current: TaskStatus, target: TaskStatus) -> None:
    assert transition_task(current, target) is target


@pytest.mark.parametrize("terminal", sorted(TERMINAL_TASK_STATUSES))
def test_terminal_state_rejects_transition(terminal: TaskStatus) -> None:
    with pytest.raises(InvalidTaskTransition):
        transition_task(terminal, TaskStatus.RUNNING)


def test_status_sets_are_disjoint() -> None:
    assert ACTIVE_TASK_STATUSES.isdisjoint(TERMINAL_TASK_STATUSES)


def test_progress_must_be_bounded() -> None:
    with pytest.raises(ValueError, match="progress"):
        TaskRecord(
            task_id="1",
            task_type="demo.self_check",
            status=TaskStatus.RUNNING,
            progress=101,
            current_step="invalid",
            correlation_id="2",
            idempotency_key="idem",
            worker_pid=None,
            created_at=datetime.now(UTC),
            started_at=None,
            finished_at=None,
            result=None,
            error_code=None,
            error_message=None,
            revision=0,
        )
```

- [x] **Step 2: Run the tests and observe the missing module**

Run:

```powershell
uv run pytest tests/api/test_task_model.py -v
```

Expected: collection fails with `ModuleNotFoundError: astraquant_api.task_model`.

- [x] **Step 3: Implement the task model**

Create `packages/api/src/astraquant_api/task_model.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    INTERRUPTED = "INTERRUPTED"


ACTIVE_TASK_STATUSES = frozenset(
    {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}
)
TERMINAL_TASK_STATUSES = frozenset(
    {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELED, TaskStatus.INTERRUPTED}
)

_TRANSITIONS = MappingProxyType(
    {
        TaskStatus.PENDING: frozenset(
            {TaskStatus.RUNNING, TaskStatus.CANCELED, TaskStatus.INTERRUPTED}
        ),
        TaskStatus.RUNNING: frozenset(
            {
                TaskStatus.CANCEL_REQUESTED,
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.INTERRUPTED,
            }
        ),
        TaskStatus.CANCEL_REQUESTED: frozenset(
            {
                TaskStatus.CANCELED,
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.INTERRUPTED,
            }
        ),
        TaskStatus.SUCCEEDED: frozenset(),
        TaskStatus.FAILED: frozenset(),
        TaskStatus.CANCELED: frozenset(),
        TaskStatus.INTERRUPTED: frozenset(),
    }
)


class InvalidTaskTransition(ValueError):
    pass


def transition_task(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if target not in _TRANSITIONS[current]:
        raise InvalidTaskTransition(f"cannot transition task from {current} to {target}")
    return target


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    task_type: str
    status: TaskStatus
    progress: int
    current_step: str
    correlation_id: str
    idempotency_key: str
    worker_pid: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    revision: int

    def __post_init__(self) -> None:
        if not 0 <= self.progress <= 100:
            raise ValueError("progress must be between 0 and 100")
        for value in (self.created_at, self.started_at, self.finished_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("task timestamps must be timezone-aware")

    @classmethod
    def create(cls, task_type: str, idempotency_key: str) -> TaskRecord:
        now = datetime.now(UTC)
        return cls(
            task_id=str(uuid4()),
            task_type=task_type,
            status=TaskStatus.PENDING,
            progress=0,
            current_step="queued",
            correlation_id=str(uuid4()),
            idempotency_key=idempotency_key,
            worker_pid=None,
            created_at=now,
            started_at=None,
            finished_at=None,
            result=None,
            error_code=None,
            error_message=None,
            revision=0,
        )

    def evolve(self, **changes: object) -> TaskRecord:
        return replace(self, revision=self.revision + 1, **changes)
```

Export the stable symbols from `astraquant_api.__init__`.

- [x] **Step 4: Run the task tests**

Run:

```powershell
uv run pytest tests/api/test_task_model.py -v
uv run ruff check packages/api/src/astraquant_api/task_model.py tests/api/test_task_model.py
uv run mypy
```

Expected: all task-model tests pass and static checks succeed.

- [x] **Step 5: Commit task contracts**

```powershell
git add packages/api/src/astraquant_api tests/api/test_task_model.py
git commit -m "feat(api): 定义平台任务状态契约"
```

### Task 3: Add SQLite migrations and repository recovery

**Files:**
- Create: `packages/api/alembic.ini`
- Create: `packages/api/migrations/env.py`
- Create: `packages/api/migrations/script.py.mako`
- Create: `packages/api/migrations/versions/0001_platform.py`
- Create: `packages/api/src/astraquant_api/database.py`
- Create: `packages/api/src/astraquant_api/repository.py`
- Create: `tests/api/test_repository.py`

- [x] **Step 1: Write failing persistence tests**

Create `tests/api/test_repository.py`:

```python
from pathlib import Path

from astraquant_api.database import create_database, migrate_database
from astraquant_api.repository import TaskRepository
from astraquant_api.task_model import TaskRecord, TaskStatus


def build_repository(tmp_path: Path) -> TaskRepository:
    database_url = f"sqlite:///{tmp_path / 'state.sqlite3'}"
    migrate_database(database_url)
    return TaskRepository(create_database(database_url))


def test_save_and_load_task(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    task = TaskRecord.create("demo.self_check", "idem-save")

    repository.create(task, event_type="task.created")

    assert repository.get(task.task_id) == task
    assert repository.list_tasks() == [task]
    assert repository.get_by_idempotency_key("idem-save") == task


def test_compare_and_swap_rejects_stale_revision(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    task = TaskRecord.create("demo.self_check", "idem-cas")
    repository.create(task, event_type="task.created")

    running = task.evolve(status=TaskStatus.RUNNING, current_step="started")
    repository.update(running, expected_revision=0, event_type="task.started")

    stale = task.evolve(status=TaskStatus.CANCELED, current_step="canceled")
    assert repository.update(stale, expected_revision=0, event_type="task.canceled") is False


def test_recover_active_tasks_as_interrupted(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    task = TaskRecord.create("demo.self_check", "idem-recover")
    repository.create(task, event_type="task.created")
    running = task.evolve(status=TaskStatus.RUNNING, current_step="working")
    assert repository.update(running, expected_revision=0, event_type="task.started")

    recovered = repository.interrupt_active_tasks("service_restarted")

    assert recovered == 1
    stored = repository.get(task.task_id)
    assert stored is not None
    assert stored.status is TaskStatus.INTERRUPTED
    assert stored.finished_at is not None
    assert repository.list_events(task.task_id)[-1].reason == "service_restarted"


def test_round_trip_settings(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)

    repository.set_setting("theme", "astra-light")

    assert repository.get_setting("theme") == "astra-light"
```

- [x] **Step 2: Run the tests and verify missing persistence modules**

Run:

```powershell
uv run pytest tests/api/test_repository.py -v
```

Expected: collection fails because `astraquant_api.database` is missing.

- [x] **Step 3: Implement engine and migration entry points**

`database.py` must:

- accept only `sqlite:///` URLs;
- register `PRAGMA foreign_keys=ON`, `PRAGMA journal_mode=WAL`, and
  `PRAGMA busy_timeout=5000`;
- expose `create_database(database_url) -> Engine`;
- expose `migrate_database(database_url)` using the package-local Alembic config.

Use this migration schema in `0001_platform.py`:

```python
def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("current_step", sa.String(200), nullable=False),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("worker_pid", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result_json", sa.Text()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_tasks_progress"),
    )
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])
    op.create_table(
        "task_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("tasks.task_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(200)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])
    op.create_table(
        "settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("ix_task_events_task_id", table_name="task_events")
    op.drop_table("task_events")
    op.drop_index("ix_tasks_created_at", table_name="tasks")
    op.drop_table("tasks")
```

- [x] **Step 4: Implement repository operations**

`repository.py` exposes exactly these operations:

```python
@dataclass(frozen=True, slots=True)
class TaskEventRecord:
    event_id: str
    task_id: str
    event_type: str
    status: TaskStatus
    progress: int
    reason: str | None
    occurred_at: datetime
    revision: int


class TaskRepository:
    """SQLite-backed task and settings repository.

    Public methods:
    - __init__(engine)
    - create(task, event_type)
    - get(task_id)
    - get_by_idempotency_key(key)
    - list_tasks(limit=100)
    - update(task, expected_revision, event_type, reason=None)
    - list_events(task_id, limit=100)
    - interrupt_active_tasks(reason)
    - get_setting(key)
    - set_setting(key, value)
    """
```

`create` inserts the task and first event inside `engine.begin()`. `update` builds a SQLAlchemy
`update(tasks)` statement filtered by both `task_id` and `expected_revision`, checks
`rowcount == 1`, and appends the event in the same transaction only when the compare-and-swap
succeeds. `get` and list operations convert SQLAlchemy rows through one `_row_to_task` helper.
Serialize datetimes as UTC-aware values and JSON with deterministic key ordering.
`interrupt_active_tasks` loads active rows, applies the public transition function, sets
`finished_at=datetime.now(UTC)`, and persists one `task.interrupted` event per row.

- [x] **Step 5: Run persistence checks**

Run:

```powershell
uv run pytest tests/api/test_repository.py -v
uv run ruff check packages/api tests/api
uv run mypy
```

Expected: persistence and recovery tests pass.

- [x] **Step 6: Commit persistence**

```powershell
git add packages/api/alembic.ini packages/api/migrations `
  packages/api/src/astraquant_api/database.py `
  packages/api/src/astraquant_api/repository.py tests/api/test_repository.py
git commit -m "feat(api): 增加任务持久化与恢复"
```

### Task 4: Implement spawned demo workers

**Files:**
- Create: `packages/api/src/astraquant_api/worker.py`
- Create: `packages/api/src/astraquant_api/supervisor.py`
- Create: `tests/api/test_worker.py`
- Create: `tests/api/test_supervisor.py`

- [x] **Step 1: Write failing worker protocol tests**

Create `tests/api/test_worker.py`:

```python
from multiprocessing import get_context
from queue import Empty

from astraquant_api.worker import WorkerMessageKind, run_demo_worker


def collect_messages(cancel_immediately: bool) -> list[object]:
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
    messages: list[object] = []
    while True:
        try:
            messages.append(queue.get_nowait())
        except Empty:
            return messages


def test_demo_worker_reports_six_steps_and_success() -> None:
    messages = collect_messages(cancel_immediately=False)

    kinds = [message.kind for message in messages]  # type: ignore[attr-defined]
    assert kinds.count(WorkerMessageKind.PROGRESS) == 6
    assert kinds[-1] is WorkerMessageKind.SUCCEEDED


def test_demo_worker_honors_cancellation() -> None:
    messages = collect_messages(cancel_immediately=True)

    assert messages[-1].kind is WorkerMessageKind.CANCELED  # type: ignore[attr-defined]
```

Create `tests/api/test_supervisor.py` using a temporary repository. Verify:

- `start_demo` moves `PENDING` to `RUNNING` and records the worker PID;
- queue progress changes `progress`, `current_step`, and revision;
- success produces `SUCCEEDED` and a result;
- `cancel` is idempotent and produces `CANCEL_REQUESTED`;
- a dead process without a terminal message produces `FAILED` with
  `error_code="worker_exited"`;
- `shutdown` cancels all live jobs and joins them within the supplied timeout.

- [x] **Step 2: Run tests and observe missing worker modules**

Run:

```powershell
uv run pytest tests/api/test_worker.py tests/api/test_supervisor.py -v
```

Expected: collection fails because worker modules are missing.

- [x] **Step 3: Implement the process-safe worker protocol**

`worker.py` must define picklable top-level values:

```python
class WorkerMessageKind(StrEnum):
    PROGRESS = "PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


@dataclass(frozen=True, slots=True)
class WorkerMessage:
    task_id: str
    kind: WorkerMessageKind
    progress: int
    current_step: str
    payload: dict[str, object] | None = None


DEMO_STEPS = (
    "check_runtime",
    "check_state_directory",
    "check_database",
    "check_worker_channel",
    "check_logging",
    "finalize",
)
```

`run_demo_worker` must check the cancel event before each step, sleep only for the injected
`step_delay`, report progress as `round(index / 6 * 100)`, and finish with:

```python
WorkerMessage(
    task_id=task_id,
    kind=WorkerMessageKind.SUCCEEDED,
    progress=100,
    current_step="completed",
    payload={"checks": 6, "status": "healthy"},
)
```

Catch ordinary exceptions and emit a redacted `FAILED` message. Do not include tracebacks or
environment values in the queue payload.

- [x] **Step 4: Implement the supervisor**

`supervisor.py` must:

- always use `multiprocessing.get_context("spawn")`;
- own process, queue, and cancel-event handles in a lock-protected dictionary;
- have one monitor thread that consumes queue messages and updates the repository;
- implement `start_demo(task)`, `cancel(task_id)`, `active_count()`, and
  `shutdown(timeout_seconds)`;
- call repository compare-and-swap updates;
- remove process handles after terminal state and close queues;
- mark unexpected exits as `FAILED`.

Keep process objects out of Pydantic models and SQLite.

- [x] **Step 5: Run worker and supervisor tests**

Run:

```powershell
uv run pytest tests/api/test_worker.py tests/api/test_supervisor.py -v
uv run ruff check packages/api tests/api
uv run mypy
```

Expected: spawned-process tests pass on Windows.

- [x] **Step 6: Commit workers**

```powershell
git add packages/api/src/astraquant_api/worker.py `
  packages/api/src/astraquant_api/supervisor.py `
  tests/api/test_worker.py tests/api/test_supervisor.py
git commit -m "feat(api): 增加示例 Worker 生命周期"
```

### Task 5: Add settings, redacted logs, and HTTP schemas

**Files:**
- Create: `packages/api/src/astraquant_api/config.py`
- Create: `packages/api/src/astraquant_api/logging.py`
- Create: `packages/api/src/astraquant_api/schemas.py`
- Create: `tests/api/test_config.py`
- Create: `tests/api/test_logging.py`
- Create: `tests/api/test_schemas.py`

- [x] **Step 1: Write failing configuration tests**

Create `tests/api/test_config.py` with:

```python
def test_load_config_requires_token_and_loopback(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ASTRAQUANT_SESSION_TOKEN", "x" * 43)
    monkeypatch.setenv("ASTRAQUANT_STATE_DIR", str(tmp_path))
    config = RuntimeConfig.from_environment()
    assert config.host == "127.0.0.1"
    assert config.port == 0
    assert config.database_path.parent == tmp_path / "state"


def test_reject_short_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ASTRAQUANT_SESSION_TOKEN", "short")
    monkeypatch.setenv("ASTRAQUANT_STATE_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="session token"):
        RuntimeConfig.from_environment()
```

Create `tests/api/test_schemas.py` with parametrized assertions that accept only:

- themes `astra-minimal` and `astra-light`;
- `reduced_motion` as boolean;
- `sidebar_collapsed` as boolean;
- `background_effect` in `none`, `nebula`, `grid`.

Create `tests/api/test_logging.py` with:

```python
def test_redacts_nested_sensitive_values(tmp_path: Path) -> None:
    activity = ActivityBuffer()
    logger = configure_logging(tmp_path, activity)

    logger.info(
        "runtime.started",
        session_token="secret-token",
        nested={"Authorization": "Bearer value", "safe": "visible"},
        password="hidden",
    )

    record = json.loads(next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()[0])
    assert record["session_token"] == "[REDACTED]"
    assert record["nested"]["Authorization"] == "[REDACTED]"
    assert record["nested"]["safe"] == "visible"
    assert record["password"] == "[REDACTED]"
```

- [x] **Step 2: Run tests and observe missing modules**

```powershell
uv run pytest tests/api/test_config.py tests/api/test_logging.py tests/api/test_schemas.py -v
```

Expected: missing-module failures.

- [x] **Step 3: Implement validated runtime configuration**

`RuntimeConfig` is a frozen dataclass with:

```python
session_token: str
state_dir: Path
host: Literal["127.0.0.1"] = "127.0.0.1"
port: int = 0
shutdown_grace_seconds: float = 5.0
```

Derived paths are `state/astraquant.sqlite3` and `logs/`. Resolve and create only descendants of
`state_dir`; reject tokens shorter than 43 characters and ports outside `0..65535`.

- [x] **Step 4: Implement logging and API schemas**

Use Structlog processors to add UTC ISO timestamps and JSON output. Add a recursive redaction
processor before the JSON renderer. Maintain an in-memory `deque[ActivityItem]` capped at 200 items
for the activity endpoint.

Define strict Pydantic response models for health, runtime, tasks, events, activity and settings.
All models set:

```python
model_config = ConfigDict(extra="forbid")
```

Task responses convert datetimes to UTC ISO 8601 and expose no database implementation fields.

- [x] **Step 5: Run configuration checks**

```powershell
uv run pytest tests/api/test_config.py tests/api/test_logging.py tests/api/test_schemas.py -v
uv run ruff check packages/api tests/api
uv run mypy
```

Expected: all new tests pass.

- [x] **Step 6: Commit platform configuration**

```powershell
git add packages/api/src/astraquant_api/config.py `
  packages/api/src/astraquant_api/logging.py `
  packages/api/src/astraquant_api/schemas.py `
  tests/api/test_config.py tests/api/test_logging.py tests/api/test_schemas.py
git commit -m "feat(api): 增加本地配置与脱敏日志"
```

### Task 6: Expose the authenticated FastAPI control service

**Files:**
- Create: `packages/api/src/astraquant_api/app.py`
- Create: `packages/api/src/astraquant_api/cli.py`
- Create: `tests/api/test_app.py`
- Create: `tests/api/test_cli.py`

- [ ] **Step 1: Write failing API tests**

Build the app with a temporary database and a fake supervisor. Test:

```python
def test_health_is_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "protocol_version": 1,
        "service_version": "0.1.0",
    }


def test_v1_requires_bearer_token(client: TestClient) -> None:
    assert client.get("/v1/runtime").status_code == 401
    assert client.get("/v1/runtime", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_create_demo_task_is_idempotent(auth_client: TestClient) -> None:
    headers = {"Idempotency-Key": "demo-1"}
    first = auth_client.post("/v1/tasks/demo", headers=headers)
    second = auth_client.post("/v1/tasks/demo", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["task_id"] == second.json()["task_id"]


def test_cancel_terminal_task_is_idempotent(auth_client: TestClient) -> None:
    created = auth_client.post(
        "/v1/tasks/demo", headers={"Idempotency-Key": "demo-terminal"}
    ).json()
    task_id = created["task_id"]
    fake_supervisor.finish(task_id)

    first = auth_client.post(f"/v1/tasks/{task_id}/cancel")
    second = auth_client.post(f"/v1/tasks/{task_id}/cancel")

    assert first.json()["status"] == "SUCCEEDED"
    assert second.json() == first.json()
```

Add named tests `test_list_tasks_newest_first`, `test_missing_task_returns_404`,
`test_settings_reject_unknown_theme`, `test_activity_honors_limit`,
`test_runtime_reports_active_worker_count`, and `test_shutdown_requires_authentication`.
Each test creates its own task or setting through the temporary repository and asserts the complete
HTTP status and JSON response.

Create `tests/api/test_cli.py::test_ready_message_uses_bound_port_after_recovery`. Seed a running
task in the temporary database, start the CLI subprocess, parse the first stdout line as JSON, and
assert its keys equal `{"type", "protocol_version", "host", "port", "pid"}`, `port > 0`, and the
seeded task is `INTERRUPTED` before terminating the service through the authenticated shutdown
endpoint.

- [ ] **Step 2: Run tests and observe missing app**

```powershell
uv run pytest tests/api/test_app.py tests/api/test_cli.py -v
```

Expected: missing-module failures.

- [ ] **Step 3: Implement dependency-owned application state**

Define:

```python
@dataclass(slots=True)
class AppState:
    repository: TaskRepository
    supervisor: TaskSupervisor
    activity: ActivityBuffer
    session_token: str
    state_dir: Path
    shutting_down: bool = False
```

`create_app(state)` registers:

- constant-time bearer comparison with `secrets.compare_digest`;
- loopback-only CORS origins from explicit development/Tauri values;
- all routes from the design specification;
- `503 runtime_shutting_down` for task creation after shutdown begins;
- `Idempotency-Key` validation between 8 and 200 visible ASCII characters;
- exception handlers returning stable `{"code", "message"}` payloads.

- [ ] **Step 4: Implement CLI lifecycle and ready handshake**

`cli.main()` must:

1. parse only the `serve` command;
2. load `RuntimeConfig`;
3. migrate SQLite;
4. create repository and interrupt active tasks;
5. bind a TCP socket to `127.0.0.1:<configured-port>`;
6. create activity, supervisor, and app state;
7. print the compact ready JSON to stdout with `flush=True`;
8. pass the already-bound socket to Uvicorn;
9. on shutdown, stop the supervisor and close the database engine.

Logs and Uvicorn access output go to stderr or the JSONL sink, never stdout.

- [ ] **Step 5: Run API and full Python gates**

```powershell
uv run pytest tests/api/test_app.py tests/api/test_cli.py -v
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv run python -m tools.repository_policy
```

Expected: all Python tests and repository policy pass.

- [ ] **Step 6: Commit the API**

```powershell
git add packages/api/src/astraquant_api/app.py `
  packages/api/src/astraquant_api/cli.py tests/api/test_app.py tests/api/test_cli.py
git commit -m "feat(api): 提供本地控制服务"
```

### Task 7: Scaffold Tauri and validate the service handshake

**Files:**
- Create: `apps/desktop/package.json`
- Create: `apps/desktop/index.html`
- Create: `apps/desktop/tsconfig.json`
- Create: `apps/desktop/vite.config.ts`
- Create: `apps/desktop/src/main.tsx`
- Create: `apps/desktop/src/App.tsx`
- Create: `apps/desktop/src/test/setup.ts`
- Create: `apps/desktop/src-tauri/Cargo.toml`
- Create: `apps/desktop/src-tauri/build.rs`
- Create: `apps/desktop/src-tauri/tauri.conf.json`
- Create: `apps/desktop/src-tauri/capabilities/default.json`
- Create: `apps/desktop/src-tauri/src/main.rs`
- Create: `apps/desktop/src-tauri/src/lib.rs`
- Create: `apps/desktop/src-tauri/src/handshake.rs`
- Create: `apps/desktop/src-tauri/src/runtime.rs`
- Modify: `pnpm-lock.yaml`
- Create: `apps/desktop/src-tauri/Cargo.lock`

- [ ] **Step 1: Create the frontend package**

Use exact dependency families:

```json
{
  "name": "@astraquant/desktop",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "check": "tsc -b --pretty false",
    "test": "vitest run",
    "tauri": "tauri"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.101.4",
    "@tauri-apps/api": "^2.11.1",
    "react": "^19.2.8",
    "react-dom": "^19.2.8"
  },
  "devDependencies": {
    "@tauri-apps/cli": "^2.11.4",
    "@testing-library/jest-dom": "^7.0.0",
    "@testing-library/react": "^16.3.2",
    "@types/react": "^19",
    "@types/react-dom": "^19",
    "@vitejs/plugin-react": "^5",
    "jsdom": "^27",
    "typescript": "~7.0.2",
    "vite": "^8.1.5",
    "vitest": "^4.1.10"
  }
}
```

Configure strict TypeScript, React JSX, Vite port `1420`, clear-screen false, and Vitest `jsdom`
with `src/test/setup.ts`.

Use a temporary `App.tsx` that renders `AstraQuant desktop bootstrap` so Rust work can be tested
before the full UI.

- [ ] **Step 2: Write failing Rust handshake tests**

Create `apps/desktop/src-tauri/Cargo.toml` before writing the test:

```toml
[package]
name = "astraquant-desktop"
version = "0.1.0"
description = "AstraQuant local-first desktop"
edition = "2024"
rust-version = "1.96"

[lib]
name = "astraquant_desktop_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2.6", features = [] }

[dependencies]
base64 = "0.22"
rand = "0.9"
reqwest = { version = "0.13", default-features = false, features = ["blocking", "json", "rustls"] }
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
tauri = { version = "2.11", features = [] }
tauri-plugin-opener = "2"
thiserror = "2"
```

Create `build.rs`:

```rust
fn main() {
    tauri_build::build()
}
```

Create `src/main.rs`:

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    astraquant_desktop_lib::run();
}
```

Create `tauri.conf.json` with product name `AstraQuant`, identifier
`com.xiaogans1.astraquant`, `beforeDevCommand: "pnpm dev"`, `devUrl:
"http://localhost:1420"`, `beforeBuildCommand: "pnpm build"`, and `frontendDist: "../dist"`.
Configure one 1440 by 900 window with minimum size 1024 by 700. Disable bundling because packaging
is outside Phase 1.

In `handshake.rs`, write tests before implementation:

```rust
#[test]
fn parses_valid_ready_message() {
    let message = r#"{"type":"ready","protocol_version":1,"host":"127.0.0.1","port":43127,"pid":12040}"#;
    let parsed = ReadyMessage::parse_and_validate(message, 12040).unwrap();
    assert_eq!(parsed.base_url(), "http://127.0.0.1:43127");
}

#[test]
fn rejects_non_loopback_host() {
    let message = r#"{"type":"ready","protocol_version":1,"host":"0.0.0.0","port":43127,"pid":12040}"#;
    assert!(matches!(
        ReadyMessage::parse_and_validate(message, 12040),
        Err(HandshakeError::InvalidHost)
    ));
}

#[test]
fn rejects_wrong_protocol_or_pid() {
    let protocol = r#"{"type":"ready","protocol_version":2,"host":"127.0.0.1","port":43127,"pid":12040}"#;
    let pid = r#"{"type":"ready","protocol_version":1,"host":"127.0.0.1","port":43127,"pid":99}"#;
    assert!(matches!(
        ReadyMessage::parse_and_validate(protocol, 12040),
        Err(HandshakeError::UnsupportedProtocol(2))
    ));
    assert!(matches!(
        ReadyMessage::parse_and_validate(pid, 12040),
        Err(HandshakeError::PidMismatch { .. })
    ));
}
```

- [ ] **Step 3: Run Rust tests and observe missing types**

```powershell
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml handshake
```

Expected: compilation fails because handshake types are not implemented.

- [ ] **Step 4: Implement handshake validation**

Use Serde with `deny_unknown_fields`. Accept only:

- `type == "ready"`;
- `protocol_version == 1`;
- `host == "127.0.0.1"`;
- `1 <= port <= 65535`;
- ready PID equals the spawned child PID.

Expose only `base_url` and protocol version to the frontend; never expose the child PID.

- [ ] **Step 5: Implement process ownership**

`runtime.rs` must define:

```rust
#[derive(Clone, serde::Serialize)]
pub struct RuntimeConnection {
    pub base_url: String,
    pub protocol_version: u16,
    pub session_token: String,
}

pub enum RuntimeStatus {
    Starting,
    Online(RuntimeConnection),
    Offline(String),
}

pub struct RuntimeManager {
    state: std::sync::Mutex<RuntimeStatus>,
    child: std::sync::Mutex<Option<std::process::Child>>,
}
```

Startup behavior:

- generate a 32-byte token with the operating-system RNG and URL-safe base64;
- resolve the repository root from `CARGO_MANIFEST_DIR`;
- start `uv run astraquant-api serve` in the repository root;
- pass `ASTRAQUANT_SESSION_TOKEN` and `.astraquant` state directory through environment variables;
- pipe stdout/stderr;
- read exactly one stdout line with a 10-second timeout;
- validate the handshake and store `RuntimeConnection`;
- drain stderr to a local diagnostic file without logging the token.

Tauri commands:

```rust
#[tauri::command]
fn runtime_connection(state: tauri::State<'_, RuntimeManager>)
    -> Result<RuntimeConnection, String>;

#[tauri::command]
fn open_log_directory(state: tauri::State<'_, RuntimeManager>)
    -> Result<(), String>;
```

On application exit, send authenticated `POST /internal/shutdown`, wait up to five seconds, then
kill and wait for the child if it remains alive.

- [ ] **Step 6: Run Rust and frontend bootstrap checks**

```powershell
pnpm install
pnpm --dir apps/desktop check
pnpm --dir apps/desktop test
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Expected: TypeScript and Rust checks pass.

- [ ] **Step 7: Commit desktop process management**

```powershell
git add apps/desktop package.json pnpm-lock.yaml
git commit -m "feat(desktop): 管理本地服务生命周期"
```

### Task 8: Add the typed frontend API and polling

**Files:**
- Create: `apps/desktop/src/api/contracts.ts`
- Create: `apps/desktop/src/api/client.ts`
- Create: `apps/desktop/src/api/client.test.ts`
- Create: `apps/desktop/src/api/queries.ts`
- Create: `apps/desktop/src/runtime/tauri.ts`

- [ ] **Step 1: Write failing client tests**

Use a mocked `fetch` and verify:

```typescript
it("adds bearer and idempotency headers", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(taskFixture), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }),
  );
  const client = new ApiClient(connectionFixture, fetchMock);

  await client.createDemoTask("idem-12345678");

  expect(fetchMock).toHaveBeenCalledWith(
    "http://127.0.0.1:43127/v1/tasks/demo",
    expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({
        Authorization: "Bearer session-token",
        "Idempotency-Key": "idem-12345678",
      }),
    }),
  );
});

it("maps structured API errors", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ code: "runtime_shutting_down", message: "正在关闭" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    }),
  );
  const client = new ApiClient(connectionFixture, fetchMock);

  await expect(client.createDemoTask("idem-12345678")).rejects.toMatchObject({
    code: "runtime_shutting_down",
    status: 503,
  });
});
```

- [ ] **Step 2: Run frontend tests and observe missing client**

```powershell
pnpm --dir apps/desktop test -- src/api/client.test.ts
```

Expected: module resolution fails.

- [ ] **Step 3: Implement exact frontend contracts**

Define discriminated string unions matching Python:

```typescript
export type TaskStatus =
  | "PENDING"
  | "RUNNING"
  | "CANCEL_REQUESTED"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED"
  | "INTERRUPTED";

export interface RuntimeConnection {
  base_url: string;
  protocol_version: number;
  session_token: string;
}

export interface Task {
  task_id: string;
  task_type: "demo.self_check";
  status: TaskStatus;
  progress: number;
  current_step: string;
  correlation_id: string;
  worker_pid: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  revision: number;
}
```

Add corresponding `Health`, `Runtime`, `ActivityItem`, and `Settings` interfaces.

- [ ] **Step 4: Implement authenticated fetch and Query hooks**

`ApiClient` must set authorization centrally, require JSON responses, map non-2xx responses to
`ApiError`, and implement every public `/v1` endpoint.

Query behavior:

- runtime refetches every 3 seconds;
- task list refetches every 500 ms while any task is active, otherwise every 3 seconds;
- activity refetches every 2 seconds;
- mutations invalidate only affected keys;
- network errors keep cached data and expose `isStale`.

The Tauri adapter contains the only direct `invoke("runtime_connection")` and
`invoke("open_log_directory")` calls.

- [ ] **Step 5: Run client checks**

```powershell
pnpm --dir apps/desktop test -- src/api/client.test.ts
pnpm --dir apps/desktop check
```

Expected: client tests and strict TypeScript pass.

- [ ] **Step 6: Commit frontend contracts**

```powershell
git add apps/desktop/src/api apps/desktop/src/runtime
git commit -m "feat(ui): 接入类型化本地 API"
```

### Task 9: Build themes and the workspace shell

**Files:**
- Create: `apps/desktop/src/theme/tokens.css`
- Create: `apps/desktop/src/theme/theme.ts`
- Create: `apps/desktop/src/theme/theme.test.ts`
- Create: `apps/desktop/src/styles/app.css`
- Create: `apps/desktop/src/components/Sidebar.tsx`
- Create: `apps/desktop/src/components/StatusRail.tsx`
- Create: `apps/desktop/src/components/Panel.tsx`
- Create: `apps/desktop/src/components/EmptyState.tsx`
- Modify: `apps/desktop/src/App.tsx`
- Modify: `apps/desktop/src/main.tsx`

- [ ] **Step 1: Write failing theme tests**

Verify:

```typescript
it("applies only supported themes", () => {
  applyTheme("astra-light");
  expect(document.documentElement.dataset.theme).toBe("astra-light");
  expect(() => applyTheme("unknown" as ThemeName)).toThrow("Unsupported theme");
});

it("keeps safety tokens outside theme overrides", () => {
  expect(SAFETY_TOKEN_NAMES).toEqual([
    "--safety-live",
    "--safety-paper",
    "--safety-risk",
    "--safety-buy",
    "--safety-sell",
    "--safety-emergency",
  ]);
});
```

- [ ] **Step 2: Implement the token hierarchy**

`:root` defines immutable safety colors. `[data-theme="astra-minimal"]` and
`[data-theme="astra-light"]` define only:

- canvas, panel, elevated surface;
- primary, secondary, muted text;
- border and focus ring;
- accent and accent-soft;
- shadow, blur, radius and motion duration.

Add `prefers-reduced-motion` and `[data-reduced-motion="true"]` rules that reduce transitions to
near-zero without hiding progress state.

- [ ] **Step 3: Implement the workspace shell**

Build the visual structure approved in the browser mockup:

- 58-pixel top status rail;
- collapsible 220-pixel sidebar;
- enabled Overview, Tasks, Activity, Settings entries;
- disabled Data, Research, Trading entries labeled `Later`;
- responsive single-column content below 980 pixels;
- clear focus outlines and 44-pixel minimum interactive targets;
- no gradients on text and no theme-dependent safety colors.

Navigation remains local React state in Phase 1; do not add a router.

- [ ] **Step 4: Run theme and shell checks**

```powershell
pnpm --dir apps/desktop test -- src/theme/theme.test.ts
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

Expected: tests, strict typing and production frontend build pass.

- [ ] **Step 5: Commit themes and shell**

```powershell
git add apps/desktop/src/theme apps/desktop/src/styles `
  apps/desktop/src/components apps/desktop/src/App.tsx apps/desktop/src/main.tsx
git commit -m "feat(ui): 建立 Astra 工作区与主题"
```

### Task 10: Implement Phase 1 pages and interactions

**Files:**
- Create: `apps/desktop/src/pages/OverviewPage.tsx`
- Create: `apps/desktop/src/pages/OverviewPage.test.tsx`
- Create: `apps/desktop/src/pages/TasksPage.tsx`
- Create: `apps/desktop/src/pages/TasksPage.test.tsx`
- Create: `apps/desktop/src/pages/ActivityPage.tsx`
- Create: `apps/desktop/src/pages/SettingsPage.tsx`
- Create: `apps/desktop/src/components/RuntimeCard.tsx`
- Create: `apps/desktop/src/components/TaskProgress.tsx`
- Create: `apps/desktop/src/components/ActivityFeed.tsx`
- Create: `apps/desktop/src/components/ServiceError.tsx`
- Modify: `apps/desktop/src/App.tsx`

- [ ] **Step 1: Write failing page tests**

Overview tests:

```typescript
it("creates a demo task and exposes progress", async () => {
  renderOverview({ runtime: runtimeFixture, tasks: [], createDemoTask });
  await userEvent.click(screen.getByRole("button", { name: "运行示例任务" }));
  expect(createDemoTask).toHaveBeenCalledTimes(1);
});

it("disables mutations while service data is stale", () => {
  renderOverview({ runtime: runtimeFixture, tasks: [], isStale: true });
  expect(screen.getByRole("button", { name: "运行示例任务" })).toBeDisabled();
  expect(screen.getByText("本地服务连接已过期")).toBeVisible();
});
```

Tasks tests:

```typescript
it("offers cancel only for active tasks", () => {
  renderTasks([runningTask, succeededTask]);
  expect(screen.getAllByRole("button", { name: "取消任务" })).toHaveLength(1);
});

it("shows interrupted recovery reason without treating it as failure", () => {
  renderTasks([interruptedTask]);
  expect(screen.getByText("服务重启时中断")).toBeVisible();
  expect(screen.queryByText("任务失败")).not.toBeInTheDocument();
});
```

Add `SettingsPage.test.tsx::persists_all_supported_preferences`. Change theme, reduced motion,
sidebar collapse and background effect, submit once, assert the mutation received the complete
`Settings` object, resolve the mutation, and then assert `document.documentElement.dataset.theme`
changed. A second test rejects the mutation and asserts the previously applied theme remains.

- [ ] **Step 2: Run page tests and observe failures**

```powershell
pnpm --dir apps/desktop test -- src/pages
```

Expected: missing-page module failures.

- [ ] **Step 3: Build overview and task pages**

Overview:

- runtime cards for service, Worker count, today's task count and state database size;
- primary `运行示例任务` action;
- current active task with exact progress and current step;
- idempotency key generated with `crypto.randomUUID()`;
- cancel action with pending feedback;
- recent five activity items.

Tasks:

- status filter with `all`, active and terminal groups;
- rows sorted by server order;
- expandable task details;
- result and stable user-facing error message;
- copyable task and correlation IDs;
- cancel only for active states.

- [ ] **Step 4: Build activity and settings pages**

Activity displays timestamp, component, event name, task ID and correlation ID. It never displays
raw JSON or environment data.

Settings exposes:

```typescript
interface Settings {
  theme: "astra-minimal" | "astra-light";
  reduced_motion: boolean;
  sidebar_collapsed: boolean;
  background_effect: "none" | "nebula" | "grid";
}
```

`App` loads the runtime connection first, creates one `ApiClient`, then mounts one
`QueryClientProvider`. Startup, offline and protocol errors use `ServiceError` with retry and
open-log-directory actions.

- [ ] **Step 5: Run frontend gates**

```powershell
pnpm --dir apps/desktop test
pnpm --dir apps/desktop check
pnpm --dir apps/desktop build
```

Expected: all UI tests and production build pass.

- [ ] **Step 6: Commit pages**

```powershell
git add apps/desktop/src
git commit -m "feat(ui): 完成任务运行工作区"
```

### Task 11: Verify the desktop vertical slice and CI

**Files:**
- Create: `tests/integration/test_runtime_round_trip.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Create: `docs/architecture/adr/0002-desktop-runtime.md`
- Modify: `docs/superpowers/plans/2026-07-27-phase-1-desktop-platform.md`

- [ ] **Step 1: Add a real service round-trip test**

The integration test must start the CLI with:

- a random 43-character token;
- a temporary state directory;
- `PYTHONUNBUFFERED=1`.

It reads one stdout ready line, calls health, creates a demo task with authentication, polls until
`SUCCEEDED`, sends shutdown, and asserts:

```python
assert process.wait(timeout=10) == 0
assert task["progress"] == 100
assert task["result"] == {"checks": 6, "status": "healthy"}
assert (state_dir / "state" / "astraquant.sqlite3").exists()
assert list((state_dir / "logs").glob("*.jsonl"))
```

Add a second test that terminates the service during a running task, restarts it with the same
state directory, and asserts that the task is `INTERRUPTED`.

- [ ] **Step 2: Run the integration tests**

```powershell
uv run pytest tests/integration/test_runtime_round_trip.py -v
```

Expected: complete and recovery round trips pass on Windows.

- [ ] **Step 3: Extend CI**

Keep the existing Python matrix and add:

```yaml
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: pnpm/action-setup@v4
        with:
          version: 11.9.0
      - uses: actions/setup-node@v6
        with:
          node-version: 24
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - run: pnpm --dir apps/desktop check
      - run: pnpm --dir apps/desktop test
      - run: pnpm --dir apps/desktop build

  desktop-rust:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v6
      - uses: dtolnay/rust-toolchain@stable
        with:
          toolchain: "1.96.0"
          components: rustfmt
      - run: cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
      - run: cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
      - run: cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml
```

The Windows Python job runs the process round-trip tests; Ubuntu excludes only tests explicitly
marked `windows_runtime`.

- [ ] **Step 4: Document development startup**

README must state:

```powershell
uv sync --locked --all-packages
pnpm install --frozen-lockfile
pnpm dev
```

Document prerequisites Node 24, pnpm 11, Rust 1.96, uv and Tauri's Windows WebView2/C++ build
requirements. Explain that Phase 1 is development-only and all runtime data stays under
`.astraquant/`.

ADR 0002 records:

- Tauri owns the Python process and token;
- FastAPI is loopback-only;
- stdout is reserved for the ready handshake;
- workers use `spawn`;
- React polls rather than using WebSocket;
- SQLite has one writer;
- abnormal recovery produces `INTERRUPTED`.

- [ ] **Step 5: Run every local gate**

```powershell
uv sync --locked --all-packages
pnpm install --frozen-lockfile
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -v
uv run python -m tools.repository_policy
pnpm --dir apps/desktop check
pnpm --dir apps/desktop test
pnpm --dir apps/desktop build
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml
git diff --check
```

Expected: every command exits zero and no runtime data is tracked.

- [ ] **Step 6: Run the desktop manually**

Run:

```powershell
pnpm dev
```

Verify:

1. desktop reaches the online overview;
2. demo task reports all steps and succeeds;
3. a second task can be canceled;
4. task history survives restart;
5. theme survives restart;
6. closing the window leaves no `astraquant-api` or demo Worker process.

- [ ] **Step 7: Record completion and commit**

Mark every executed checkbox in this plan, then:

```powershell
git add .github/workflows/ci.yml README.md docs tests/integration
git commit -m "ci: 验证 Phase 1 桌面闭环"
```

- [ ] **Step 8: Push and open a Draft PR**

```powershell
git push -u origin feature/phase-1-desktop-platform
```

Create a Draft PR titled `feat: 建立 Phase 1 桌面平台闭环` with:

- architecture summary;
- local and CI verification commands;
- screenshots of Astra Minimal and Astra Light only if generated from the running app;
- explicit statement that market data and trading are out of scope.

- [ ] **Step 9: Verify remote checks**

Confirm the Draft PR head SHA matches local `HEAD`, and wait for Python Windows/Ubuntu, frontend,
and desktop Rust checks. Fix failures on the same feature branch; do not merge the PR automatically.

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

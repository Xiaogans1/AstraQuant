from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.engine import make_url

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _validate_database_url(database_url: str) -> None:
    url = make_url(database_url)
    if url.drivername != "sqlite" or url.database in {None, ""}:
        raise ValueError("database URL must identify a SQLite file")


def create_database(database_url: str) -> Engine:
    _validate_database_url(database_url)
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def configure_sqlite(
        connection: sqlite3.Connection,
        _connection_record: object,
    ) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def migrate_database(database_url: str) -> None:
    _validate_database_url(database_url)
    config = Config(str(_PACKAGE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_PACKAGE_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")

    from astraquant_api.schema_registry import metadata

    engine = create_engine(database_url)
    try:
        missing = set(metadata.tables) - set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    if missing:
        raise RuntimeError(f"migration head is missing registered tables: {sorted(missing)}")

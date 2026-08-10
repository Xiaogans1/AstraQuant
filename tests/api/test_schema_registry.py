from pathlib import Path
from typing import cast

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from astraquant_api.capture_repository import metadata as capture_metadata
from astraquant_api.data_repository import data_snapshots
from astraquant_api.database import create_database, migrate_database
from astraquant_api.paper_repository import metadata as paper_metadata
from astraquant_api.repository import metadata as core_metadata
from astraquant_api.schema_registry import metadata as schema_metadata


def _migrated_engine(tmp_path: Path) -> sa.Engine:
    database_url = f"sqlite:///{tmp_path / 'schema.sqlite3'}"
    migrate_database(database_url)
    return create_database(database_url)


def _metadata_constraint_names(
    table: sa.Table,
    constraint_type: type[sa.Constraint],
) -> set[str]:
    return {
        cast(str, constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and constraint.name is not None
    }


def test_schema_registry_contains_every_repository_table() -> None:
    expected = set(core_metadata.tables) | set(paper_metadata.tables) | set(capture_metadata.tables)

    assert set(schema_metadata.tables) == expected
    assert data_snapshots.metadata is core_metadata


def test_migration_head_matches_registered_metadata(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, schema_metadata)

    assert differences == []


def test_registry_and_database_have_matching_named_schema_objects(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path)
    inspector = sa.inspect(engine)

    application_tables = set(inspector.get_table_names()) - {"alembic_version"}
    assert application_tables == set(schema_metadata.tables)
    for table_name, table in schema_metadata.tables.items():
        assert {column["name"] for column in inspector.get_columns(table_name)} == set(
            table.columns.keys()
        )
        assert {index["name"] for index in inspector.get_indexes(table_name)} == {
            index.name for index in table.indexes if index.name is not None
        }
        assert {
            foreign_key["name"]
            for foreign_key in inspector.get_foreign_keys(table_name)
            if foreign_key["name"] is not None
        } == _metadata_constraint_names(table, sa.ForeignKeyConstraint)
        assert {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(table_name)
            if constraint["name"] is not None
        } == _metadata_constraint_names(table, sa.UniqueConstraint)
        assert {
            constraint["name"]
            for constraint in inspector.get_check_constraints(table_name)
            if constraint["name"] is not None
        } == _metadata_constraint_names(table, sa.CheckConstraint)

import pytest

from astraquant_api.migration_config import resolve_migration_url


def test_cli_database_url_is_used_when_ini_has_no_url() -> None:
    assert (
        resolve_migration_url(
            configured_url=None,
            cli_arguments={"database_url": "sqlite:///phase2.sqlite3"},
        )
        == "sqlite:///phase2.sqlite3"
    )


def test_missing_migration_database_url_has_an_actionable_error() -> None:
    with pytest.raises(RuntimeError, match="-x database_url"):
        resolve_migration_url(configured_url=None, cli_arguments={})

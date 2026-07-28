"""Pure configuration helpers shared by Alembic's runtime entry point."""

from collections.abc import Mapping


def resolve_migration_url(
    *,
    configured_url: str | None,
    cli_arguments: Mapping[str, str],
) -> str:
    if configured_url:
        return configured_url
    cli_url = cli_arguments.get("database_url")
    if cli_url:
        return cli_url
    raise RuntimeError(
        "migration database URL is missing; pass -x database_url=sqlite:///path"
    )

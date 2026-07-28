"""Reject private data and runtime artifacts from the Git index."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import PurePosixPath

FORBIDDEN_NAMES = {
    ".env",
    "credentials.json",
    "secrets.json",
}
FORBIDDEN_PREFIXES = (
    "credentials-",
    "secrets-",
)
FORBIDDEN_SUFFIXES = {
    ".arrow",
    ".ckpt",
    ".db",
    ".duckdb",
    ".feather",
    ".parquet",
    ".pem",
    ".pfx",
    ".p12",
    ".sqlite",
    ".sqlite3",
}
FORBIDDEN_DIRECTORIES = {
    ".astraquant",
    "artifacts",
    "checkpoints",
    "data",
    "datasets",
    "logs",
    "models",
    "reports",
}
SOURCE_DATA_PREFIXES = (
    PurePosixPath("packages/data"),
    PurePosixPath("tests/data"),
)


def _is_data_source_path(path: PurePosixPath) -> bool:
    return any(path == prefix or path.is_relative_to(prefix) for prefix in SOURCE_DATA_PREFIXES)


def find_forbidden_paths(paths: Iterable[str]) -> list[str]:
    forbidden: list[str] = []
    for raw_path in paths:
        path = PurePosixPath(raw_path)
        lowered_name = path.name.lower()
        directory_parts = {part.lower() for part in path.parts[:-1]}
        contains_forbidden_directory = bool(directory_parts & FORBIDDEN_DIRECTORIES)
        is_forbidden = (
            lowered_name in FORBIDDEN_NAMES
            or lowered_name.startswith(FORBIDDEN_PREFIXES)
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
            or (contains_forbidden_directory and not _is_data_source_path(path))
        )
        if is_forbidden:
            forbidden.append(raw_path)
    return forbidden


def tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line for line in completed.stdout.splitlines() if line]


def main() -> int:
    forbidden = find_forbidden_paths(tracked_files())
    if not forbidden:
        print("Repository policy passed.")
        return 0
    print("Forbidden tracked files:")
    for path in forbidden:
        print(f"- {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

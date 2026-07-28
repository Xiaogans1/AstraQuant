"""Reject private data and runtime artifacts from the Git index."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

MAX_FIXTURE_CSV_BYTES = 256 * 1024
MARKET_DATA_FIXTURE_ROOT = PurePosixPath("tests/fixtures/market_data")

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
    ".gguf",
    ".onnx",
    ".parquet",
    ".pem",
    ".pfx",
    ".p12",
    ".sqlite",
    ".sqlite3",
    ".pt",
    ".pth",
    ".safetensors",
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
    "state",
}
SOURCE_DATA_PREFIXES = (
    PurePosixPath("packages/data"),
    PurePosixPath("tests/data"),
)


def _is_data_source_path(path: PurePosixPath) -> bool:
    return any(path == prefix or path.is_relative_to(prefix) for prefix in SOURCE_DATA_PREFIXES)


def find_forbidden_paths(
    paths: Iterable[str],
    *,
    file_sizes: Mapping[str, int] | None = None,
) -> list[str]:
    forbidden: list[str] = []
    for raw_path in paths:
        path = PurePosixPath(raw_path)
        lowered_name = path.name.lower()
        suffix = path.suffix.lower()
        directory_parts = {part.lower() for part in path.parts[:-1]}
        contains_forbidden_directory = bool(directory_parts & FORBIDDEN_DIRECTORIES)
        is_fixture_csv = (
            suffix == ".csv"
            and path.parent == MARKET_DATA_FIXTURE_ROOT
            and file_sizes is not None
            and file_sizes.get(raw_path, MAX_FIXTURE_CSV_BYTES + 1) <= MAX_FIXTURE_CSV_BYTES
        )
        is_forbidden = (
            lowered_name in FORBIDDEN_NAMES
            or lowered_name.startswith(FORBIDDEN_PREFIXES)
            or suffix in FORBIDDEN_SUFFIXES
            or ".sqlite" in lowered_name
            or (suffix == ".csv" and not is_fixture_csv)
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
    paths = tracked_files()
    file_sizes = {path: Path(path).stat().st_size for path in paths if Path(path).is_file()}
    forbidden = find_forbidden_paths(paths, file_sizes=file_sizes)
    if not forbidden:
        print("Repository policy passed.")
        return 0
    print("Forbidden tracked files:")
    for path in forbidden:
        print(f"- {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

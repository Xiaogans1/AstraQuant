"""Reject private data and runtime artifacts from the Git index."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

MAX_FIXTURE_CSV_BYTES = 256 * 1024
MARKET_DATA_FIXTURE_ROOT = PurePosixPath("tests/fixtures/market_data")

FORBIDDEN_NAMES = {
    ".env",
    "credentials.json",
    "secrets.json",
    "eastmoney-token.txt",
    "eastmoney-quotes.json",
    "eastmoney-ticks.jsonl",
    "gm-current-dump.json",
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
    ".jsonl",
    ".ndjson",
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
FORBIDDEN_ARTIFACT_DIRECTORIES = {
    "captures",
    "qualification-reports",
    "raw-captures",
}
SOURCE_DATA_PREFIXES = (
    PurePosixPath("packages/data"),
    PurePosixPath("tests/data"),
)

_SECRET_ASSIGNMENT = re.compile(
    r"^\s*ASTRAQUANT_[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD)\s*=\s*[^\s#]+\s*$|"
    r"[\"\'](?:access_token|api_token|client_secret|eastmoney_token|password)[\"\']"
    r"\s*:\s*[\"\'](?!\[REDACTED\])[^\"\']+[\"\']",
    re.IGNORECASE | re.MULTILINE,
)
_CONTENT_SCAN_EXCEPTIONS = {
    ".env.example",
    "tests/repository/test_repository_policy.py",
}


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
        contains_forbidden_artifact_directory = bool(
            directory_parts & FORBIDDEN_ARTIFACT_DIRECTORIES
        )
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
            or contains_forbidden_artifact_directory
            or (contains_forbidden_directory and not _is_data_source_path(path))
        )
        if is_forbidden:
            forbidden.append(raw_path)
    return forbidden


def find_forbidden_content(contents: Mapping[str, str]) -> list[str]:
    """Return tracked text files containing a concrete secret assignment."""
    return [
        path
        for path, content in contents.items()
        if PurePosixPath(path).as_posix() not in _CONTENT_SCAN_EXCEPTIONS
        and _SECRET_ASSIGNMENT.search(content) is not None
    ]


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
    text_contents: dict[str, str] = {}
    for path in paths:
        candidate = Path(path)
        if not candidate.is_file() or candidate.stat().st_size > 1_000_000:
            continue
        try:
            text_contents[path] = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    forbidden.extend(find_forbidden_content(text_contents))
    forbidden = list(dict.fromkeys(forbidden))
    if not forbidden:
        print("Repository policy passed.")
        return 0
    print("Forbidden tracked files:")
    for path in forbidden:
        print(f"- {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

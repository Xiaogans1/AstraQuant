"""Command-line entry point for the isolated official Kronos runner."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from .runner import KronosBackend, run_request
from .upstream_adapter import create_official_backend

BackendFactory = Callable[..., KronosBackend]


def main(
    argv: Sequence[str] | None = None,
    *,
    backend_factory: BackendFactory = create_official_backend,
) -> int:
    parser = argparse.ArgumentParser(description="Run pinned Kronos zero-shot inference")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--upstream-root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    backend = backend_factory(
        arguments.request,
        root=arguments.root,
        upstream_root=arguments.upstream_root,
    )
    run_request(
        arguments.request,
        arguments.output,
        root=arguments.root,
        backend=backend,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from pathlib import Path

from . import run_request


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pinned Qlib folds over an AstraQuant export")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run_request(args.request, args.output)


if __name__ == "__main__":
    main()

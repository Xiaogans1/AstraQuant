from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import run_request


def run_cli_request(request: Path, output: Path) -> dict[str, Any]:
    value = json.loads(request.read_text(encoding="utf-8"))
    if isinstance(value, dict) and value.get("schema_version") == (
        "astraquant.stage-b-v2-double-ensemble-request/v1"
    ):
        from .stage_b_v2_double_ensemble import run_double_ensemble_request

        return run_double_ensemble_request(request, output)
    if isinstance(value, dict) and value.get("schema_version") == (
        "astraquant.stage-b-v2-request/v1"
    ):
        from .stage_b_v2 import run_stage_b_v2_request

        return run_stage_b_v2_request(request, output)
    if isinstance(value, dict) and value.get("schema_version") == (
        "astraquant.qlib-alpha158-request/v1"
    ):
        from .alpha158 import run_alpha158_request

        return run_alpha158_request(request, output)
    return run_request(request, output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pinned Qlib folds over an AstraQuant export")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run_cli_request(args.request, args.output)


if __name__ == "__main__":
    main()

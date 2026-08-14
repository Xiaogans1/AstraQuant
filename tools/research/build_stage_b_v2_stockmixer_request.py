"""Build a sealed Stage B v2 StockMixer temporal panel from exact local artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from astraquant_data.exports.stage_b_v2_stockmixer import (
    export_stage_b_v2_stockmixer_panel,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="build-stage-b-v2-stockmixer-request")
    parser.add_argument("raw_export_root", type=Path)
    parser.add_argument("materialization_root", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = export_stage_b_v2_stockmixer_panel(
            raw_export_root=arguments.raw_export_root,
            materialization_root=arguments.materialization_root,
            output_root=arguments.output_root,
            lookback=64,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Stage B v2 StockMixer panel failed: {error}", file=sys.stderr)
        return 1
    print(result.manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

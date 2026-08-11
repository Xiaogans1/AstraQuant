"""Submit an exact Eastmoney formal backfill through the authenticated local API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

from tools.data.formal_capture_cli import FormalCaptureCliError, post_formal_command


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--instrument-id", required=True)
    parser.add_argument("--frequency", choices=("1d", "1m"), required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--adjustment", choices=("none", "qfq", "hfq"), required=True)
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    args = _parser().parse_args(argv)
    environment = os.environ if environ is None else environ
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    try:
        response = post_formal_command(
            api_url=args.api_url,
            path="/v1/formal-data/captures",
            idempotency_key=args.idempotency_key,
            payload={
                "approval_id": args.approval_id,
                "instrument_id": args.instrument_id,
                "frequency": args.frequency,
                "start": args.start,
                "end": args.end,
                "adjustment": args.adjustment,
            },
            environ=environment,
            timeout_seconds=args.timeout_seconds,
        )
    except FormalCaptureCliError:
        print(json.dumps({"status": "FORMAL_CAPTURE_COMMAND_FAILED"}), file=errors)
        return 2
    print(
        json.dumps(
            {"task_id": response["task_id"], "status": response["status"]},
            separators=(",", ":"),
        ),
        file=output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Reconcile two exact sealed Eastmoney captures through the authenticated API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

from tools.data.formal_capture_cli import FormalCaptureCliError, post_json_command


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--left-capture-id", required=True)
    parser.add_argument("--right-capture-id", required=True)
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
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    try:
        response = post_json_command(
            api_url=args.api_url,
            path="/v1/formal-data/captures/reconcile",
            payload={
                "left_capture_id": args.left_capture_id,
                "right_capture_id": args.right_capture_id,
            },
            environ=os.environ if environ is None else environ,
            timeout_seconds=args.timeout_seconds,
        )
        status = response["status"]
        report_digest = response["report_digest"]
        differences = response["differences"]
        if not isinstance(status, str) or not isinstance(report_digest, str):
            raise KeyError
        if not isinstance(differences, list) or not all(
            isinstance(item, str) for item in differences
        ):
            raise KeyError
    except (FormalCaptureCliError, KeyError):
        print(json.dumps({"status": "FORMAL_RECONCILIATION_FAILED"}), file=errors)
        return 2
    print(
        json.dumps(
            {
                "report_digest": report_digest,
                "status": status,
                "differences": differences,
            },
            separators=(",", ":"),
        ),
        file=output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

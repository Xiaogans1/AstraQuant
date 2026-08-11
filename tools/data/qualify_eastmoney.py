"""Submit exact Eastmoney qualification evidence through the authenticated local API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, TextIO

from astraquant_data.provider_identity import (
    ProviderCapability,
    ProviderIdentity,
    ProviderTransport,
)
from astraquant_data.provider_qualification import (
    CapabilityResult,
    CheckStatus,
    ProbeEvidence,
    QualificationCheck,
    QualificationCoverage,
    QualificationReport,
    RevocationKind,
)

PROBE_SCHEMA = "astraquant.eastmoney-qualification-probe/v1"
SESSION_TOKEN_ENV = "ASTRAQUANT_SESSION_TOKEN"


class QualificationCliError(RuntimeError):
    """Safe, non-secret CLI failure."""


class ArtifactConflictError(QualificationCliError):
    pass


class ApiCommandError(QualificationCliError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualificationCliError(f"{label} is not readable canonical JSON") from error
    if not isinstance(value, dict):
        raise QualificationCliError(f"{label} must be a JSON object")
    return value


def _identity_from_dict(value: Mapping[str, object]) -> ProviderIdentity:
    try:
        return ProviderIdentity(
            vendor=str(value["vendor"]),
            product=str(value["product"]),
            endpoint=str(value["endpoint"]),
            capability=ProviderCapability(str(value["capability"])),
            interface=str(value["interface"]),
            interface_build=str(value["interface_build"]),
            transport=ProviderTransport(str(value["transport"])),
            permission_tier=str(value["permission_tier"]),
            schema_fingerprint=str(value["schema_fingerprint"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise QualificationCliError("identity artifact is invalid") from error


def _sequence(value: object, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise QualificationCliError(f"{label} must be a JSON array")
    return value


def _object_sequence(value: object, *, label: str) -> list[dict[str, Any]]:
    items = _sequence(value, label=label)
    if not all(isinstance(item, dict) for item in items):
        raise QualificationCliError(f"{label} entries must be JSON objects")
    return items


def build_report(identity_path: Path, probe_path: Path) -> QualificationReport:
    identity = _identity_from_dict(_read_object(identity_path, label="identity artifact"))
    probe = _read_object(probe_path, label="probe artifact")
    if probe.get("schema_version") != PROBE_SCHEMA:
        raise QualificationCliError("probe artifact schema is unsupported")
    if probe.get("identity_digest") != identity.identity_digest:
        raise QualificationCliError("probe identity digest does not match exact identity")
    try:
        coverage = probe["coverage"]
        if not isinstance(coverage, dict):
            raise TypeError("coverage is not an object")
        return QualificationReport(
            identity=identity,
            probes=tuple(
                ProbeEvidence(
                    request_digest=str(item["request_digest"]),
                    raw_response_digest=str(item["raw_response_digest"]),
                    observed_at=datetime.fromisoformat(str(item["observed_at"])),
                )
                for item in _object_sequence(probe["probes"], label="probes")
            ),
            coverage=QualificationCoverage(
                start=date.fromisoformat(str(coverage["start"])),
                end=date.fromisoformat(str(coverage["end"])),
                instruments=tuple(
                    str(item)
                    for item in _sequence(
                        coverage["instruments"],
                        label="coverage instruments",
                    )
                ),
                delisted_instruments=tuple(
                    str(item)
                    for item in _sequence(
                        coverage["delisted_instruments"],
                        label="coverage delisted instruments",
                    )
                ),
            ),
            results=tuple(
                CapabilityResult(
                    check=QualificationCheck(str(item["check"])),
                    status=CheckStatus(str(item["status"])),
                    evidence_digest=str(item["evidence_digest"]),
                )
                for item in _object_sequence(probe["results"], label="results")
            ),
            adjust_modes=tuple(
                str(item) for item in _sequence(probe["adjust_modes"], label="adjust modes")
            ),
            units=tuple(str(item) for item in _sequence(probe["units"], label="units")),
            observed_at=datetime.fromisoformat(str(probe["observed_at"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise QualificationCliError("probe artifact is invalid") from error


def write_report_artifact(output_root: Path, report: QualificationReport) -> Path:
    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    payload = {**report.to_dict(), "report_digest": report.report_digest}
    body = _canonical_bytes(payload) + b"\n"
    target = root / f"{report.report_digest.removeprefix('sha256:')}.json"
    if target.exists():
        if target.read_bytes() == body:
            return target
        raise ArtifactConflictError("qualification artifact content conflicts")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=root,
            prefix=".qualification-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, target)
        except FileExistsError:
            if target.read_bytes() != body:
                raise ArtifactConflictError("qualification artifact content conflicts") from None
        return target
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _post_json(
    *,
    api_url: str,
    path: str,
    token: str,
    payload: object,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}{path}",
        data=_canonical_bytes(payload),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            value = json.loads(response.read())
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise ApiCommandError("qualification API command failed") from error
    if not isinstance(value, dict):
        raise ApiCommandError("qualification API returned an invalid response")
    if not all(
        isinstance(value.get(field), str) and value[field]
        for field in ("artifact_id", "state", "identity_digest", "report_digest")
    ):
        raise ApiCommandError("qualification API response is incomplete")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe")
    probe.add_argument("--identity", type=Path, required=True)
    probe.add_argument("--probe", type=Path, required=True)
    probe.add_argument("--output-root", type=Path, required=True)

    approve = subparsers.add_parser("approve")
    approve.add_argument("--identity-digest", required=True)
    approve.add_argument("--report-digest", required=True)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--policy-version", required=True)
    approve.add_argument("--effective-at", required=True)

    revoke = subparsers.add_parser("revoke")
    revoke.add_argument("--approval-id", required=True)
    revoke.add_argument("--kind", choices=[item.value for item in RevocationKind], required=True)
    revoke.add_argument("--reviewer", required=True)
    revoke.add_argument("--reason-digest", required=True)
    revoke.add_argument("--effective-at", required=True)

    for child in (probe, approve, revoke):
        child.add_argument("--api-url", required=True)
        child.add_argument("--timeout-seconds", type=float, default=8.0)
    return parser


def _token(environ: Mapping[str, str]) -> str:
    token = environ.get(SESSION_TOKEN_ENV, "").strip()
    if not token:
        raise QualificationCliError(f"{SESSION_TOKEN_ENV} is required")
    return token


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    args = _parser().parse_args(argv)
    environment = os.environ if environ is None else environ
    try:
        token = _token(environment)
        expected_identity_digest: str | None = None
        expected_report_digest: str | None = None
        if args.timeout_seconds <= 0:
            raise QualificationCliError("timeout must be positive")
        if args.command == "probe":
            report = build_report(args.identity, args.probe)
            write_report_artifact(args.output_root, report)
            path = "/v1/provider-qualifications/reports"
            payload: object = {
                "report": {**report.to_dict(), "report_digest": report.report_digest}
            }
            expected_identity_digest = report.identity.identity_digest
            expected_report_digest = report.report_digest
        elif args.command == "approve":
            path = "/v1/provider-qualifications/approvals"
            payload = {
                "identity_digest": args.identity_digest,
                "report_digest": args.report_digest,
                "reviewer": args.reviewer,
                "policy_version": args.policy_version,
                "effective_at": args.effective_at,
            }
            expected_identity_digest = args.identity_digest
            expected_report_digest = args.report_digest
        else:
            path = "/v1/provider-qualifications/revocations"
            payload = {
                "approval_id": args.approval_id,
                "kind": args.kind,
                "reviewer": args.reviewer,
                "reason_digest": args.reason_digest,
                "effective_at": args.effective_at,
            }
        response = _post_json(
            api_url=args.api_url,
            path=path,
            token=token,
            payload=payload,
            timeout_seconds=args.timeout_seconds,
        )
        if (
            expected_identity_digest is not None
            and response["identity_digest"] != expected_identity_digest
        ) or (
            expected_report_digest is not None
            and response["report_digest"] != expected_report_digest
        ):
            raise ApiCommandError("qualification API response binding does not match command")
    except ArtifactConflictError:
        print(json.dumps({"status": "ARTIFACT_CONFLICT"}), file=errors)
        return 3
    except ApiCommandError:
        print(json.dumps({"status": "API_COMMAND_FAILED"}), file=errors)
        return 4
    except QualificationCliError:
        print(json.dumps({"status": "INVALID_QUALIFICATION_INPUT"}), file=errors)
        return 2
    print(
        json.dumps(
            {
                "artifact_id": response.get("artifact_id"),
                "state": response.get("state"),
            },
            separators=(",", ":"),
        ),
        file=output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

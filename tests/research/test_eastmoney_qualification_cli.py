from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from astraquant_data.provider_identity import (
    ProviderCapability,
    ProviderIdentity,
    ProviderTransport,
)
from astraquant_data.provider_qualification import QualificationCheck
from tools.data.qualify_eastmoney import build_report, main

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _identity() -> ProviderIdentity:
    return ProviderIdentity(
        vendor="eastmoney",
        product="eastmoney-terminal",
        endpoint="market.daily-bars",
        capability=ProviderCapability.DAILY_BARS,
        interface="gm_python_sdk",
        interface_build="3.0.176",
        transport=ProviderTransport.NDJSON_BRIDGE,
        permission_tier="level1-history",
        schema_fingerprint=_digest("1"),
    )


def _probe(identity: ProviderIdentity) -> dict[str, object]:
    return {
        "schema_version": "astraquant.eastmoney-qualification-probe/v1",
        "identity_digest": identity.identity_digest,
        "probes": [
            {
                "request_digest": _digest("2"),
                "raw_response_digest": _digest("3"),
                "observed_at": NOW.isoformat(),
            }
        ],
        "coverage": {
            "start": date(2020, 1, 1).isoformat(),
            "end": date(2026, 8, 8).isoformat(),
            "instruments": ["600000.SSE"],
            "delisted_instruments": ["600001.SSE"],
        },
        "results": [
            {
                "check": check.value,
                "status": "PASS",
                "evidence_digest": _digest(format(index + 4, "x")),
            }
            for index, check in enumerate(QualificationCheck)
        ],
        "adjust_modes": ["NONE"],
        "units": ["price=CNY", "volume=share"],
        "observed_at": NOW.isoformat(),
    }


class _RecordingHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, object]]] = []
    response_override: ClassVar[dict[str, object] | None] = None

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        payload = json.loads(body)
        self.__class__.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "payload": payload,
            }
        )
        report = payload.get("report", {})
        response = self.__class__.response_override or {
            "artifact_id": report.get("report_digest", _digest("a")),
            "state": "UNQUALIFIED",
            "identity_digest": report.get(
                "identity_digest",
                payload.get("identity_digest", _digest("b")),
            ),
            "report_digest": report.get(
                "report_digest",
                payload.get("report_digest", _digest("a")),
            ),
        }
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.fixture
def api_server() -> Iterator[tuple[str, list[dict[str, object]]]]:
    _RecordingHandler.requests = []
    _RecordingHandler.response_override = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", _RecordingHandler.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_probe_writes_immutable_report_and_submits_only_through_api(
    tmp_path: Path,
    api_server: tuple[str, list[dict[str, object]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    api_url, requests = api_server
    identity = _identity()
    identity_path = tmp_path / "identity.json"
    probe_path = tmp_path / "probe.json"
    output_root = tmp_path / "formal" / "qualification"
    _write_json(identity_path, identity.to_dict())
    _write_json(probe_path, _probe(identity))

    exit_code = main(
        [
            "probe",
            "--identity",
            str(identity_path),
            "--probe",
            str(probe_path),
            "--output-root",
            str(output_root),
            "--api-url",
            api_url,
        ],
        environ={"ASTRAQUANT_SESSION_TOKEN": "private-token"},
    )

    assert exit_code == 0
    assert len(requests) == 1
    assert requests[0]["path"] == "/v1/provider-qualifications/reports"
    assert requests[0]["authorization"] == "Bearer private-token"
    request_payload = requests[0]["payload"]
    assert isinstance(request_payload, dict)
    report = request_payload["report"]
    assert isinstance(report, dict)
    artifact_name = f"{str(report['report_digest']).removeprefix('sha256:')}.json"
    artifact = output_root / artifact_name
    assert json.loads(artifact.read_text(encoding="utf-8")) == report
    output = capsys.readouterr().out
    assert "private-token" not in output
    assert "raw payload" not in output
    assert "UNQUALIFIED" in output


def test_cli_source_has_no_database_write_path() -> None:
    source = Path("tools/data/qualify_eastmoney.py").read_text(encoding="utf-8").casefold()

    assert "sqlalchemy" not in source
    assert "capture_repository" not in source
    assert "sqlite" not in source


def test_probe_rejects_identity_drift_before_network_call(
    tmp_path: Path,
    api_server: tuple[str, list[dict[str, object]]],
) -> None:
    api_url, requests = api_server
    identity = _identity()
    identity_path = tmp_path / "identity.json"
    probe_path = tmp_path / "probe.json"
    probe = _probe(identity)
    probe["identity_digest"] = _digest("f")
    _write_json(identity_path, identity.to_dict())
    _write_json(probe_path, probe)

    exit_code = main(
        [
            "probe",
            "--identity",
            str(identity_path),
            "--probe",
            str(probe_path),
            "--output-root",
            str(tmp_path / "formal"),
            "--api-url",
            api_url,
        ],
        environ={"ASTRAQUANT_SESSION_TOKEN": "private-token"},
    )

    assert exit_code != 0
    assert requests == []


def test_probe_rejects_non_object_evidence_entry_before_network_call(
    tmp_path: Path,
    api_server: tuple[str, list[dict[str, object]]],
) -> None:
    api_url, requests = api_server
    identity = _identity()
    identity_path = tmp_path / "identity.json"
    probe_path = tmp_path / "probe.json"
    probe = _probe(identity)
    probe["probes"] = ["not-an-evidence-object"]
    _write_json(identity_path, identity.to_dict())
    _write_json(probe_path, probe)

    exit_code = main(
        [
            "probe",
            "--identity",
            str(identity_path),
            "--probe",
            str(probe_path),
            "--output-root",
            str(tmp_path / "formal"),
            "--api-url",
            api_url,
        ],
        environ={"ASTRAQUANT_SESSION_TOKEN": "private-token"},
    )

    assert exit_code != 0
    assert requests == []


def test_probe_refuses_to_overwrite_tampered_artifact(
    tmp_path: Path,
    api_server: tuple[str, list[dict[str, object]]],
) -> None:
    api_url, requests = api_server
    identity = _identity()
    identity_path = tmp_path / "identity.json"
    probe_path = tmp_path / "probe.json"
    output_root = tmp_path / "formal"
    _write_json(identity_path, identity.to_dict())
    _write_json(probe_path, _probe(identity))
    report = build_report(identity_path, probe_path)
    artifact = output_root / f"{report.report_digest.removeprefix('sha256:')}.json"
    output_root.mkdir()
    artifact.write_text('{"tampered":true}\n', encoding="utf-8")

    exit_code = main(
        [
            "probe",
            "--identity",
            str(identity_path),
            "--probe",
            str(probe_path),
            "--output-root",
            str(output_root),
            "--api-url",
            api_url,
        ],
        environ={"ASTRAQUANT_SESSION_TOKEN": "private-token"},
    )

    assert exit_code == 3
    assert requests == []
    assert artifact.read_text(encoding="utf-8") == '{"tampered":true}\n'


def test_api_unavailable_fails_closed_without_secret_in_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identity = _identity()
    identity_path = tmp_path / "identity.json"
    probe_path = tmp_path / "probe.json"
    _write_json(identity_path, identity.to_dict())
    _write_json(probe_path, _probe(identity))

    exit_code = main(
        [
            "probe",
            "--identity",
            str(identity_path),
            "--probe",
            str(probe_path),
            "--output-root",
            str(tmp_path / "formal"),
            "--api-url",
            "http://127.0.0.1:1",
            "--timeout-seconds",
            "0.1",
        ],
        environ={"ASTRAQUANT_SESSION_TOKEN": "private-token"},
    )

    captured = capsys.readouterr()
    assert exit_code == 4
    assert "private-token" not in captured.out
    assert "private-token" not in captured.err


def test_cli_rejects_incomplete_success_response(
    api_server: tuple[str, list[dict[str, object]]],
) -> None:
    api_url, _requests = api_server
    _RecordingHandler.response_override = {"state": "APPROVED"}

    exit_code = main(
        [
            "approve",
            "--identity-digest",
            _digest("1"),
            "--report-digest",
            _digest("2"),
            "--reviewer",
            "reviewer-1",
            "--policy-version",
            "provider-policy/v1",
            "--effective-at",
            NOW.isoformat(),
            "--api-url",
            api_url,
        ],
        environ={"ASTRAQUANT_SESSION_TOKEN": "private-token"},
    )

    assert exit_code != 0


def test_approve_rejects_api_response_bound_to_different_report(
    api_server: tuple[str, list[dict[str, object]]],
) -> None:
    api_url, _requests = api_server
    _RecordingHandler.response_override = {
        "artifact_id": _digest("a"),
        "state": "APPROVED",
        "identity_digest": _digest("1"),
        "report_digest": _digest("f"),
    }

    exit_code = main(
        [
            "approve",
            "--identity-digest",
            _digest("1"),
            "--report-digest",
            _digest("2"),
            "--reviewer",
            "reviewer-1",
            "--policy-version",
            "provider-policy/v1",
            "--effective-at",
            NOW.isoformat(),
            "--api-url",
            api_url,
        ],
        environ={"ASTRAQUANT_SESSION_TOKEN": "private-token"},
    )

    assert exit_code != 0


@pytest.mark.parametrize(
    ("command", "path"),
    [
        (
            [
                "approve",
                "--identity-digest",
                _digest("1"),
                "--report-digest",
                _digest("2"),
                "--reviewer",
                "reviewer-1",
                "--policy-version",
                "provider-policy/v1",
                "--effective-at",
                NOW.isoformat(),
            ],
            "/v1/provider-qualifications/approvals",
        ),
        (
            [
                "revoke",
                "--approval-id",
                _digest("3"),
                "--kind",
                "REVOKED",
                "--reviewer",
                "reviewer-2",
                "--reason-digest",
                _digest("4"),
                "--effective-at",
                NOW.isoformat(),
            ],
            "/v1/provider-qualifications/revocations",
        ),
    ],
)
def test_governance_commands_only_post_to_authenticated_api(
    command: list[str],
    path: str,
    api_server: tuple[str, list[dict[str, object]]],
) -> None:
    api_url, requests = api_server

    exit_code = main(
        [*command, "--api-url", api_url],
        environ={"ASTRAQUANT_SESSION_TOKEN": "private-token"},
    )

    assert exit_code == 0
    assert requests[0]["path"] == path
    assert requests[0]["authorization"] == "Bearer private-token"

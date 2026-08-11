"""Database-free worker for one server-resolved formal Eastmoney capture."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from astraquant_api.formal_data_schemas import ResolvedFormalCaptureCommand
from astraquant_api.worker import WorkerMessage, WorkerMessageKind
from astraquant_data.adapters.eastmoney_batch import (
    CaptureCanceled,
    EastmoneyBatchAdapter,
    plan_session_coverage,
)
from astraquant_data.capture import CapturePlan, CapturePurpose
from astraquant_data.capture_store import CaptureStore
from astraquant_data.eastmoney_client import EastmoneyBridgeClient
from astraquant_data.eastmoney_protocol import to_eastmoney_symbol
from astraquant_data.provider_identity import (
    ProviderCapability,
    ProviderIdentity,
    ProviderTransport,
)
from astraquant_domain import Adjustment, BarFrequency, InstrumentId
from astraquant_domain.run_manifest import validate_digest

_FREQUENCIES = {
    BarFrequency.DAY: "1d",
    BarFrequency.MINUTE: "60s",
}
_ADJUSTMENTS = {
    Adjustment.NONE: 0,
    Adjustment.FORWARD: 1,
    Adjustment.BACKWARD: 2,
}


@dataclass(frozen=True, slots=True)
class FormalCaptureResult:
    command_digest: str
    capture_id: str
    seal_digest: str
    chunk_count: int
    row_count: int

    def __post_init__(self) -> None:
        for name in ("command_digest", "capture_id", "seal_digest"):
            object.__setattr__(self, name, validate_digest(name, getattr(self, name)))
        if self.chunk_count <= 0 or self.row_count < 0:
            raise ValueError("formal capture result counts are invalid")

    def to_payload(self) -> dict[str, object]:
        return {
            "command_digest": self.command_digest,
            "capture_id": self.capture_id,
            "seal_digest": self.seal_digest,
            "chunk_count": self.chunk_count,
            "row_count": self.row_count,
        }


FormalCaptureExecutor = Callable[..., FormalCaptureResult]


def run_formal_data_worker(
    task_id: str,
    queue: Any,
    cancel: Any,
    command_values: dict[str, object],
    capture_root_value: str,
    sdk_python_value: str,
    bridge_script_value: str,
    token: str,
    *,
    executor: FormalCaptureExecutor | None = None,
) -> None:
    try:
        command = ResolvedFormalCaptureCommand.model_validate(command_values)
        if cancel.is_set():
            raise CaptureCanceled("capture canceled before startup")
        queue.put(
            WorkerMessage(
                task_id=task_id,
                kind=WorkerMessageKind.PROGRESS,
                progress=10,
                current_step="formal_capture_starting",
            )
        )
        runtime_executor = executor or _execute_formal_capture
        result = runtime_executor(
            command=command,
            capture_root=Path(capture_root_value),
            sdk_python=Path(sdk_python_value),
            bridge_script=Path(bridge_script_value),
            token=token,
            cancel=cancel,
        )
        queue.put(
            WorkerMessage(
                task_id=task_id,
                kind=WorkerMessageKind.SUCCEEDED,
                progress=100,
                current_step="completed",
                payload=result.to_payload(),
            )
        )
    except CaptureCanceled:
        queue.put(
            WorkerMessage(
                task_id=task_id,
                kind=WorkerMessageKind.CANCELED,
                progress=0,
                current_step="canceled",
            )
        )
    except Exception as error:
        queue.put(
            WorkerMessage(
                task_id=task_id,
                kind=WorkerMessageKind.FAILED,
                progress=0,
                current_step="failed",
                payload={"error_type": type(error).__name__},
            )
        )


def _execute_formal_capture(
    *,
    command: ResolvedFormalCaptureCommand,
    capture_root: Path,
    sdk_python: Path,
    bridge_script: Path,
    token: str,
    cancel: Any,
) -> FormalCaptureResult:
    identity = _identity_from_command(command)
    try:
        frequency = _FREQUENCIES[command.frequency]
    except KeyError as error:
        raise ValueError("unsupported formal capture frequency") from error
    request = plan_session_coverage(
        symbol=to_eastmoney_symbol(InstrumentId.parse(command.instrument_id)),
        frequency=frequency,
        sessions=command.sessions,
        rows_per_session=command.rows_per_session,
        adjust=_ADJUSTMENTS[command.adjustment],
    )
    if request.coverage_membership_digest != command.coverage_membership_digest:
        raise ValueError("resolved coverage membership digest does not match command")
    plan = CapturePlan(
        identity_digest=command.identity_digest,
        report_digest=command.report_digest,
        approval_id=command.approval_id,
        endpoint=identity.endpoint,
        expected_chunk_count=len(request.pages),
        expected_row_count=request.expected_total,
        coverage_proof_digest=request.coverage_proof_digest,
        started_at=command.created_at,
        purpose=CapturePurpose.FORMAL_DATA,
    )
    client = EastmoneyBridgeClient(
        python_executable=sdk_python,
        bridge_script=bridge_script,
    )
    try:
        client.start()
        client.configure(token, permission_tier=identity.permission_tier)
        envelope = EastmoneyBatchAdapter(
            client=client,
            store=CaptureStore(capture_root),
            identity=identity,
        ).capture(
            request,
            plan=plan,
            recorded_at=datetime.now(UTC),
            should_cancel=cancel.is_set,
        )
    finally:
        client.stop()
    return FormalCaptureResult(
        command_digest=command.command_digest,
        capture_id=plan.capture_id,
        seal_digest=envelope.seal_digest,
        chunk_count=len(envelope.chunk_ids),
        row_count=request.expected_total,
    )


def _identity_from_command(command: ResolvedFormalCaptureCommand) -> ProviderIdentity:
    value = command.identity
    identity = ProviderIdentity(
        vendor=value["vendor"],
        product=value["product"],
        endpoint=value["endpoint"],
        capability=ProviderCapability(value["capability"]),
        interface=value["interface"],
        interface_build=value["interface_build"],
        transport=ProviderTransport(value["transport"]),
        permission_tier=value["permission_tier"],
        schema_fingerprint=value["schema_fingerprint"],
    )
    if identity.identity_digest != command.identity_digest:
        raise ValueError("formal command provider identity digest drift")
    return identity

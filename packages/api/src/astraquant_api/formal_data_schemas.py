"""Fail-closed schemas for server-resolved formal capture commands."""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from astraquant_domain import Adjustment, BarFrequency
from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest


class FormalCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=71, max_length=71)
    instrument_id: str = Field(min_length=5, max_length=32)
    frequency: BarFrequency
    start: date
    end: date
    adjustment: Adjustment

    @model_validator(mode="after")
    def validate_range(self) -> FormalCaptureRequest:
        validate_digest("approval_id", self.approval_id)
        if self.start > self.end:
            raise ValueError("start must not be after end")
        return self


class FormalIncrementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predecessor_capture_id: str = Field(min_length=71, max_length=71)
    end: date

    @model_validator(mode="after")
    def validate_predecessor(self) -> FormalIncrementRequest:
        validate_digest("predecessor_capture_id", self.predecessor_capture_id)
        return self


class ResolvedFormalCaptureCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: dict[str, str]
    identity_digest: str
    report_digest: str
    approval_id: str
    instrument_id: str
    frequency: BarFrequency
    start: date
    end: date
    adjustment: Adjustment
    sessions: tuple[date, ...]
    rows_per_session: int = Field(gt=0)
    coverage_membership_digest: str
    policy_digest: str
    created_at: datetime
    predecessor_capture_id: str | None = None
    schema_version: str = "astraquant.formal-capture-command/v1"

    @model_validator(mode="after")
    def validate_command(self) -> ResolvedFormalCaptureCommand:
        for name in (
            "identity_digest",
            "report_digest",
            "approval_id",
            "coverage_membership_digest",
            "policy_digest",
        ):
            validate_digest(name, getattr(self, name))
        if self.predecessor_capture_id is not None:
            validate_digest("predecessor_capture_id", self.predecessor_capture_id)
        if self.schema_version != "astraquant.formal-capture-command/v1":
            raise ValueError("unsupported formal capture command schema")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if not self.sessions or tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("sessions must be unique and strictly increasing")
        if self.sessions[0] < self.start or self.sessions[-1] > self.end:
            raise ValueError("sessions must stay inside requested range")
        return self

    @property
    def command_digest(self) -> str:
        body = canonical_json_bytes(self.model_dump(mode="json"))
        return f"sha256:{hashlib.sha256(body).hexdigest()}"

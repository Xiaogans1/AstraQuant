"""HTTP command schemas for provider qualification governance."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from astraquant_data.provider_qualification import RevocationKind


class QualificationReportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: dict[str, Any]


class ProviderApprovalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_digest: str = Field(min_length=71, max_length=71)
    report_digest: str = Field(min_length=71, max_length=71)
    reviewer: str = Field(min_length=1, max_length=200)
    policy_version: str = Field(min_length=1, max_length=200)
    effective_at: datetime


class ProviderRevocationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=71, max_length=71)
    kind: RevocationKind
    reviewer: str = Field(min_length=1, max_length=200)
    reason_digest: str = Field(min_length=71, max_length=71)
    effective_at: datetime


class QualificationCommandResponse(BaseModel):
    artifact_id: str
    state: str
    identity_digest: str
    report_digest: str

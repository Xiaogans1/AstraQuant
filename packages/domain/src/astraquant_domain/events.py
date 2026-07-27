"""Versioned events shared across process boundaries."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self
from uuid import UUID, uuid4

from astraquant_domain.clocks import Clock

_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: UUID
    correlation_id: UUID
    occurred_at: datetime
    event_type: str
    schema_version: int
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not _EVENT_TYPE_PATTERN.fullmatch(self.event_type):
            raise ValueError(f"Invalid event_type: {self.event_type!r}")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        clock: Clock,
        event_id: UUID | None = None,
        correlation_id: UUID | None = None,
        schema_version: int = 1,
    ) -> Self:
        return cls(
            event_id=event_id or uuid4(),
            correlation_id=correlation_id or uuid4(),
            occurred_at=clock.now(),
            event_type=event_type,
            schema_version=schema_version,
            payload=payload,
        )

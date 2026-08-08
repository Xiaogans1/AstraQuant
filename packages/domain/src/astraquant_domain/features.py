"""Point-in-time feature contracts consumed by strategies and AI models."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from astraquant_domain.identifiers import InstrumentId


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class FeatureRow:
    instrument_id: InstrumentId
    event_time: datetime
    available_time: datetime
    values: Mapping[str, float | None]

    def __post_init__(self) -> None:
        _require_aware("event_time", self.event_time)
        _require_aware("available_time", self.available_time)
        if self.available_time < self.event_time:
            raise ValueError("available_time must not precede event_time")
        if not self.values or any(not name.isidentifier() for name in self.values):
            raise ValueError("feature names must be non-empty identifiers")
        object.__setattr__(
            self,
            "values",
            MappingProxyType(dict(sorted(self.values.items()))),
        )


@dataclass(frozen=True, slots=True)
class FeatureFrame:
    decision_time: datetime
    definition_version: str
    rows: tuple[FeatureRow, ...]

    def __post_init__(self) -> None:
        _require_aware("decision_time", self.decision_time)
        if not self.definition_version.strip():
            raise ValueError("definition_version must not be empty")
        schemas = {tuple(row.values) for row in self.rows}
        if len(schemas) > 1:
            raise ValueError("all rows must share one feature schema")
        if any(row.available_time > self.decision_time for row in self.rows):
            raise ValueError("feature available_time exceeds decision_time")

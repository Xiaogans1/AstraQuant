"""Strict local data API contracts."""

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from astraquant_api.schemas import StrictModel


class DataImportRequest(StrictModel):
    provider: Literal["fixture", "akshare"]
    instrument_id: str = Field(pattern=r"^[A-Z0-9-]+\.[A-Z]+$")
    frequency: Literal["1d"]
    start: date
    end: date
    adjustment: Literal["none", "qfq", "hfq"] = "none"

    @model_validator(mode="after")
    def validate_range(self) -> "DataImportRequest":
        if self.end < self.start:
            raise ValueError("end must not precede start")
        return self


class DatasetSummary(StrictModel):
    dataset_id: str
    name: str
    asset_class: Literal["equity", "futures"]
    frequency: str
    snapshot_count: int = Field(ge=0)
    latest_snapshot_id: str | None
    latest_provider_id: str | None
    latest_row_count: int | None = Field(default=None, ge=0)
    latest_min_event_time: str | None
    latest_max_event_time: str | None


class SnapshotSummary(StrictModel):
    snapshot_id: str
    dataset_id: str
    status: Literal["PUBLISHED", "REJECTED"]
    row_count: int = Field(ge=0)
    provider_id: str
    created_at: str
    min_event_time: str
    max_event_time: str
    quality_issues: list[dict[str, object]]


class BarPreview(StrictModel):
    instrument_id: str
    event_time: str
    available_time: str
    open: str
    high: str
    low: str
    close: str
    volume: str

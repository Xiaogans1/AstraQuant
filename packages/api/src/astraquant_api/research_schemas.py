"""Public API schemas for research replay and dataset browsing."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from astraquant_domain import OrderSide


class LegacyResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_class: Literal["EXPLORATORY"] = "EXPLORATORY"


class LegacyResearchView(BaseModel):
    semantic_class: Literal["LEGACY_SEMANTICS"] = "LEGACY_SEMANTICS"
    evidence_class: Literal["LEGACY_UNVERIFIED"] = "LEGACY_UNVERIFIED"
    run_class: Literal["EXPLORATORY"] = "EXPLORATORY"


class DatasetSummaryView(LegacyResearchView):
    dataset_id: str
    instrument_id: str
    bar_count: int
    start: datetime
    end: datetime


class OpeningPositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0)
    available_quantity: int = Field(ge=0)
    average_cost: Decimal = Field(ge=0)


class ReplayInstrumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1, max_length=64)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    opening: OpeningPositionInput | None = None


class ReplayRequest(LegacyResearchRequest):
    instruments: list[ReplayInstrumentInput] = Field(min_length=1, max_length=20)
    model_id: str = Field(min_length=1, max_length=64)
    initial_cash: Decimal = Field(default=Decimal("100000"), gt=0)
    fully_invested: bool = Field(default=True)


class ReplayTradeView(BaseModel):
    index: int
    timestamp: datetime
    side: OrderSide
    price: Decimal
    quantity: int
    pnl: Decimal
    proba: float
    features: dict[str, float] = {}
    decision_note: str = ""


class ReplayBarView(BaseModel):
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class ReplayView(LegacyResearchView):
    instrument_id: str
    model_id: str
    model_status: str
    start: datetime
    end: datetime
    bars_count: int
    initial_cash: Decimal
    initial_equity: Decimal
    final_cash: Decimal
    realized_pnl: Decimal
    net_return_percent: float
    buy_hold_return_percent: float
    excess_return_percent: float
    max_drawdown_percent: float
    sharpe: float
    profit_factor: float
    buys: int
    sells: int
    win_rate: float
    position_remaining: int
    trades: list[ReplayTradeView]
    bars: list[ReplayBarView]
    equity_points: list[list[datetime | Decimal]]
    position_value_points: list[list[datetime | Decimal]]
    buy_hold_equity_points: list[list[datetime | Decimal]]


class RecordDatasetRequest(LegacyResearchRequest):
    instrument_id: str = Field(min_length=1, max_length=64)
    count: int = Field(default=5000, ge=100, le=20_000)


class RecordDatasetResult(LegacyResearchView):
    dataset_id: str
    instrument_id: str
    bar_count: int
    start: datetime
    end: datetime


class TrainRequest(LegacyResearchRequest):
    dataset_ids: list[str] = Field(default_factory=list, max_length=8)
    instruments: list[ReplayInstrumentInput] = Field(default_factory=list, max_length=8)
    model_id: str = Field(min_length=1, max_length=64)
    horizon: int = Field(default=5, ge=1, le=30)
    threshold: Decimal = Field(default=Decimal("0.005"), gt=0, le=Decimal("0.1"))


class TrainResult(LegacyResearchView):
    model_id: str
    status: str
    rows: int
    auc: float
    gross_return: float
    net_return: float
    trades: int
    recommended_buy: float
    recommended_sell: float
    artifact_path: str


class ExperimentSummaryView(LegacyResearchView):
    experiment_id: str
    created_at: datetime
    summary_json: str


class ExperimentView(LegacyResearchView):
    experiment_id: str
    created_at: datetime
    request_json: str
    summary_json: str
    results_json: str

"""Public API schemas for research replay and dataset browsing."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from astraquant_domain import OrderSide


class DatasetSummaryView(BaseModel):
    dataset_id: str
    instrument_id: str
    bar_count: int
    start: datetime
    end: datetime


class ReplayRequest(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=200)
    model_id: str = Field(min_length=1, max_length=64)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_cash: Decimal = Field(default=Decimal("100000"), gt=0)


class ReplayTradeView(BaseModel):
    index: int
    timestamp: datetime
    side: OrderSide
    price: Decimal
    quantity: int
    pnl: Decimal


class ReplayBarView(BaseModel):
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class ReplayView(BaseModel):
    dataset_id: str
    model_id: str
    instrument_id: str
    start: datetime
    end: datetime
    bars_count: int
    initial_cash: Decimal
    final_cash: Decimal
    realized_pnl: Decimal
    net_return_percent: float
    buys: int
    sells: int
    win_rate: float
    trades: list[ReplayTradeView]
    bars: list[ReplayBarView]
    equity_points: list[list[datetime | Decimal]]

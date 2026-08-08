"""Strict public schemas for the local realtime market API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EastmoneyConfigRequest(StrictModel):
    sdk_python_path: str = Field(min_length=1)
    token: SecretStr


class EastmoneyConfigStatus(StrictModel):
    provider_id: str = "eastmoney"
    sdk_configured: bool
    token_configured: bool


class MarketConnectionResponse(EastmoneyConfigStatus):
    state: str
    connected_at: datetime | None = None
    last_event_at: datetime | None = None
    error_code: str | None = None
    instrument_count: int = 0
    parse_error_count: int = 0
    reconnect_count: int = 0


class QuoteCardResponse(StrictModel):
    instrument_id: str
    name: str
    kind: str
    state: str
    event_time: datetime | None
    last_price: str | None
    change: str | None
    change_percent: str | None
    previous_close: str | None
    open: str | None
    high: str | None
    low: str | None
    volume: str | None
    turnover: str | None
    source_id: str | None


class UnavailableFeatureResponse(StrictModel):
    status: str = "UNAVAILABLE"
    reason: str


class QuantCandidateResponse(StrictModel):
    instrument_id: str
    score: int


class MarketHomeResponse(StrictModel):
    connection: MarketConnectionResponse
    core_indices: list[QuoteCardResponse]
    watchlist: list[QuoteCardResponse]
    selected_instrument: QuoteCardResponse | None
    breadth: UnavailableFeatureResponse
    intelligence: UnavailableFeatureResponse
    candidates: list[QuantCandidateResponse]
    as_of: datetime | None


class WatchlistRequest(StrictModel):
    instrument_id: str = Field(min_length=3, max_length=40)


class InstrumentSearchResponse(StrictModel):
    instrument_id: str
    name: str
    kind: str


class MarketBarResponse(StrictModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float
    previous_close: float | None


class RealtimeFeatureResponse(StrictModel):
    feature_snapshot_id: str
    status: str
    completed_bar_count: int
    reason_codes: list[str]


class SignalFrameResponse(StrictModel):
    signal_id: str
    instrument_id: str
    event_time: datetime
    decision_time: datetime
    expires_at: datetime
    action: str
    state: str
    reference_price: str | None
    confidence: str
    strategy_id: str
    strategy_version: str
    feature_version: str
    reason_codes: list[str]


class DecisionRecordResponse(StrictModel):
    decision_id: str
    feature_snapshot_id: str
    signal_id: str
    strategy_id: str
    strategy_version: str
    market_event_time: datetime
    decision_time: datetime
    advisory_checks: list[str]


class RealtimeQuantResponse(StrictModel):
    features: RealtimeFeatureResponse
    signal: SignalFrameResponse
    decision_record: DecisionRecordResponse

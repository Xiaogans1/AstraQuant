"""Research endpoints: recorded datasets and deterministic model replay."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter

from astraquant_api.app import ApiProblem
from astraquant_api.paper_repository import ModelRegistryRecord
from astraquant_api.research_schemas import (
    DatasetSummaryView,
    ReplayBarView,
    ReplayRequest,
    ReplayTradeView,
    ReplayView,
)
from astraquant_data.market_bars import MarketBar
from astraquant_data.research_store import list_datasets, load_dataset_bars
from astraquant_domain import InstrumentId
from astraquant_quant.replay import replay_bars
from astraquant_quant.research_features import build_feature_rows
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS


class ModelLookup(Protocol):
    def get_model(self, model_id: str) -> ModelRegistryRecord | None: ...


def build_research_router(
    *,
    data_root: Path,
    models: ModelLookup,
    authenticated: Any,
) -> APIRouter:
    router = APIRouter(prefix="/v1/research", dependencies=[authenticated])

    @router.get("/datasets", response_model=list[DatasetSummaryView])
    def datasets() -> list[DatasetSummaryView]:
        return [
            DatasetSummaryView(
                dataset_id=item.dataset_id,
                instrument_id=item.instrument_id,
                bar_count=item.bar_count,
                start=item.start,
                end=item.end,
            )
            for item in list_datasets(data_root)
        ]

    @router.post("/replay", response_model=ReplayView)
    def replay(request: ReplayRequest) -> ReplayView:
        model = models.get_model(request.model_id)
        if model is None:
            raise ApiProblem(404, "model_not_found", "未找到模型")
        if model.status != "APPROVED":
            raise ApiProblem(409, "model_not_approved", "model not approved for replay")
        try:
            bars, instrument_id = load_dataset_bars(data_root, request.dataset_id)
        except ValueError as error:
            raise ApiProblem(404, "dataset_not_found", str(error)) from None
        start_date = None if request.start_date is None else date.fromisoformat(request.start_date)
        end_date = None if request.end_date is None else date.fromisoformat(request.end_date)
        bars = _filter_bars(bars, start_date=start_date, end_date=end_date)
        if not bars:
            raise ApiProblem(422, "empty_replay_window", "所选时间段内没有数据")
        try:
            import json

            params = json.loads(model.params_json)
        except (TypeError, ValueError):
            params = {}
        predictor = _model_predictor(model)
        result = replay_bars(
            bars,
            instrument_id=InstrumentId.parse(instrument_id),
            predict=predictor,
            buy_threshold=float(params.get("buy_threshold", 0.6)),
            sell_threshold=float(params.get("sell_threshold", 0.4)),
            fee_rate=Decimal("0.00025"),
            initial_cash=request.initial_cash,
        )
        return ReplayView(
            dataset_id=request.dataset_id,
            model_id=request.model_id,
            instrument_id=result.instrument_id,
            start=result.start,
            end=result.end,
            bars_count=result.bars_count,
            initial_cash=result.initial_cash,
            final_cash=result.final_cash,
            realized_pnl=result.realized_pnl,
            net_return_percent=result.net_return_percent,
            buys=result.buys,
            sells=result.sells,
            win_rate=result.win_rate,
            trades=[
                ReplayTradeView(
                    index=trade.index,
                    timestamp=trade.timestamp,
                    side=trade.side,
                    price=trade.price,
                    quantity=trade.quantity,
                    pnl=trade.pnl,
                )
                for trade in result.trades
            ],
            bars=[
                ReplayBarView(
                    timestamp=bar.timestamp,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
                for bar in bars
            ],
            equity_points=[[timestamp, equity] for timestamp, equity in result.equity_points],
        )

    return router


def _model_predictor(
    model: ModelRegistryRecord,
) -> Callable[[list[MarketBar]], float]:
    from pathlib import Path

    import lightgbm as lgb

    artifact = Path(model.artifact_path)
    if not artifact.exists():
        raise ApiProblem(409, "model_artifact_missing", "模型工件文件不存在")
    booster = lgb.Booster(model_file=str(artifact))

    def predict(completed: list[MarketBar]) -> float:
        window = completed[-60:]
        features = build_feature_rows(window)
        if not features:
            return 0.0
        latest = features[-1]
        proba = booster.predict([[float(latest[key]) for key in MODEL_FEATURE_COLUMNS]])
        return float(proba[0])

    return predict


def _filter_bars(
    bars: list[MarketBar],
    *,
    start_date: date | None,
    end_date: date | None,
) -> list[MarketBar]:
    def keep(bar: MarketBar) -> bool:
        if start_date is not None and bar.timestamp.date() < start_date:
            return False
        return not (end_date is not None and bar.timestamp.date() > end_date)

    return [bar for bar in bars if keep(bar)]

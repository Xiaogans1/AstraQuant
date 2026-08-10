"""Research endpoints: recorded datasets and deterministic model replay."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter

from astraquant_api.app import ApiProblem
from astraquant_api.paper_repository import ExperimentRecord, ModelRegistryRecord
from astraquant_api.research_schemas import (
    DatasetSummaryView,
    ExperimentSummaryView,
    ExperimentView,
    RecordDatasetRequest,
    RecordDatasetResult,
    ReplayBarView,
    ReplayInstrumentInput,
    ReplayRequest,
    ReplayTradeView,
    ReplayView,
    TrainRequest,
    TrainResult,
)
from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_data.research_store import (
    list_datasets,
    load_dataset_bars,
    market_bars_to_domain,
    publish_dataset,
)
from astraquant_domain import InstrumentId
from astraquant_quant.replay import OpeningPosition, replay_bars
from astraquant_quant.research_features import build_feature_rows, build_training_rows
from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS


class ModelLookup(Protocol):
    def get_model(self, model_id: str) -> ModelRegistryRecord | None: ...

    def save_model(self, record: ModelRegistryRecord) -> None: ...

    def list_experiments(self, limit: int = 50) -> list[ExperimentRecord]: ...

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None: ...

    def save_experiment(self, record: ExperimentRecord) -> None: ...


def build_research_router(
    *,
    data_root: Path,
    models: ModelLookup,
    authenticated: Any,
    market_service: Any = None,
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

    @router.post("/datasets/record", response_model=RecordDatasetResult)
    async def record_dataset(request: RecordDatasetRequest) -> RecordDatasetResult:
        if market_service is None:
            raise ApiProblem(409, "recording_unavailable", "market service unavailable")
        try:
            instrument_id = InstrumentId.parse(request.instrument_id)
        except ValueError as error:
            raise ApiProblem(422, "invalid_instrument_id", str(error)) from None
        rows = await market_service.bars(
            str(instrument_id),
            period=MarketPeriod.MINUTE_1,
            count=request.count,
        )
        if not rows:
            raise ApiProblem(422, "empty_recording", "未取到该标的分钟线")
        info = publish_dataset(
            data_root,
            instrument_id=instrument_id,
            bars=market_bars_to_domain(instrument_id, rows),
            provider={"id": "eastmoney", "interface": "bridge", "version": "1"},
        )
        return RecordDatasetResult(
            dataset_id=info.dataset_id,
            instrument_id=info.instrument_id,
            bar_count=info.bar_count,
            start=info.start,
            end=info.end,
        )

    @router.post("/train", response_model=TrainResult)
    async def train(request: TrainRequest) -> TrainResult:
        import json as _json

        import lightgbm as lgb

        rows: list[dict[str, float | int]] = []
        for dataset_id in request.dataset_ids:
            bars, _instrument_id = load_dataset_bars(data_root, dataset_id)
            rows.extend(
                build_training_rows(
                    bars,
                    horizon=request.horizon,
                    threshold=request.threshold,
                )
            )
        for item in request.instruments:
            try:
                instrument_id = InstrumentId.parse(item.instrument_id)
            except ValueError as error:
                raise ApiProblem(422, "invalid_instrument_id", str(error)) from None
            start_date = None if item.start_date is None else date.fromisoformat(item.start_date)
            end_date = None if item.end_date is None else date.fromisoformat(item.end_date)
            bars = await _fetch_bars(market_service, instrument_id, start_date, end_date)
            if not bars:
                raise ApiProblem(
                    422,
                    "empty_training_window",
                    "所选时间段内没有数据",
                )
            rows.extend(
                build_training_rows(
                    bars,
                    horizon=request.horizon,
                    threshold=request.threshold,
                )
            )
        if len(rows) < 200:
            raise ApiProblem(422, "insufficient_training_rows", "训练样本不足 200 行")
        train_rows, test_rows = _purged_split(rows)
        if len(train_rows) < 100 or len(test_rows) < 50:
            raise ApiProblem(422, "insufficient_training_rows", "训练/验证样本不足")
        model = lgb.LGBMClassifier(
            n_estimators=120,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=30,
            verbose=-1,
        )
        x_train = [[float(row[key]) for key in MODEL_FEATURE_COLUMNS] for row in train_rows]
        y_train = [int(row["label"]) for row in train_rows]
        x_test = [[float(row[key]) for key in MODEL_FEATURE_COLUMNS] for row in test_rows]
        y_test = [int(row["label"]) for row in test_rows]
        model.fit(x_train, y_train)
        proba = [float(row[1]) for row in model.predict_proba(x_test)]
        auc = _auc(y_test, proba)
        recommended = _best_thresholds(proba, test_rows)
        artifact_dir = data_root.parent / "research" / "models"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = artifact_dir / f"{request.model_id}.txt"
        model.booster_.save_model(str(artifact))
        metrics = {
            "auc": auc,
            "gross_return": recommended["gross_return"],
            "net_return": recommended["net_return"],
            "trades": recommended["trades"],
        }
        now = datetime.now(UTC)
        models.save_model(
            ModelRegistryRecord(
                model_id=request.model_id,
                strategy_id="microstructure-lgbm",
                strategy_version="lgbm-v1",
                feature_version="minute-v1",
                artifact_path=str(artifact),
                metrics_json=_json.dumps(metrics),
                params_json=_json.dumps(
                    {
                        "buy_threshold": recommended["buy"],
                        "sell_threshold": recommended["sell"],
                    }
                ),
                status="DRAFT",
                created_at=now,
                updated_at=now,
                approved_at=None,
                semantic_class="LEGACY_SEMANTICS",
                evidence_class="LEGACY_UNVERIFIED",
                run_class="EXPLORATORY",
                manifest_schema="1",
                content_digest=None,
            )
        )
        return TrainResult(
            model_id=request.model_id,
            status="DRAFT",
            rows=len(rows),
            auc=auc,
            gross_return=float(recommended["gross_return"]),
            net_return=float(recommended["net_return"]),
            trades=int(recommended["trades"]),
            recommended_buy=recommended["buy"],
            recommended_sell=recommended["sell"],
            artifact_path=str(artifact),
        )

    @router.get("/experiments", response_model=list[ExperimentSummaryView])
    def experiments() -> list[ExperimentSummaryView]:
        return [
            ExperimentSummaryView(
                experiment_id=item.experiment_id,
                created_at=item.created_at,
                summary_json=item.summary_json,
            )
            for item in models.list_experiments()
        ]

    @router.get("/experiments/{experiment_id}", response_model=ExperimentView)
    def experiment_detail(experiment_id: str) -> ExperimentView:
        record = models.get_experiment(experiment_id)
        if record is None:
            raise ApiProblem(404, "experiment_not_found", "未找到实验")
        return ExperimentView(
            experiment_id=record.experiment_id,
            created_at=record.created_at,
            request_json=record.request_json,
            summary_json=record.summary_json,
            results_json=record.results_json,
        )

    @router.post("/replay", response_model=list[ReplayView])
    async def replay(request: ReplayRequest) -> list[ReplayView]:
        model = models.get_model(request.model_id)
        if model is None:
            raise ApiProblem(404, "model_not_found", "未找到模型")
        try:
            import json

            params = json.loads(model.params_json)
        except (TypeError, ValueError):
            params = {}
        predictor = _model_predictor(model)
        buy_threshold = float(params.get("buy_threshold", 0.6))
        sell_threshold = float(params.get("sell_threshold", 0.4))
        fee_rate = Decimal("0.00025")

        async def run_one(item: ReplayInstrumentInput) -> ReplayView:
            try:
                instrument_id = InstrumentId.parse(item.instrument_id)
            except ValueError as error:
                raise ApiProblem(422, "invalid_instrument_id", str(error)) from None
            start_date = None if item.start_date is None else date.fromisoformat(item.start_date)
            end_date = None if item.end_date is None else date.fromisoformat(item.end_date)
            bars = await _fetch_bars(market_service, instrument_id, start_date, end_date)
            if not bars:
                raise ApiProblem(422, "empty_replay_window", "所选时间段内没有数据")
            opening = None
            if item.opening is not None:
                opening = OpeningPosition(
                    quantity=item.opening.quantity,
                    available_quantity=item.opening.available_quantity,
                    average_cost=item.opening.average_cost,
                )
            result = replay_bars(
                bars,
                instrument_id=instrument_id,
                predict=predictor,
                buy_threshold=buy_threshold,
                sell_threshold=sell_threshold,
                fee_rate=fee_rate,
                initial_cash=request.initial_cash,
                opening=opening,
                fully_invested=request.fully_invested,
            )
            return ReplayView(
                instrument_id=result.instrument_id,
                model_id=request.model_id,
                model_status=model.status,
                start=result.start,
                end=result.end,
                bars_count=result.bars_count,
                initial_cash=result.initial_cash,
                initial_equity=result.initial_equity,
                final_cash=result.final_cash,
                realized_pnl=result.realized_pnl,
                net_return_percent=result.net_return_percent,
                buy_hold_return_percent=result.buy_hold_return_percent,
                excess_return_percent=result.excess_return_percent,
                max_drawdown_percent=result.max_drawdown_percent,
                sharpe=result.sharpe,
                profit_factor=result.profit_factor,
                buys=result.buys,
                sells=result.sells,
                win_rate=result.win_rate,
                position_remaining=result.position_remaining,
                trades=[
                    ReplayTradeView(
                        index=trade.index,
                        timestamp=trade.timestamp,
                        side=trade.side,
                        price=trade.price,
                        quantity=trade.quantity,
                        pnl=trade.pnl,
                        proba=trade.proba,
                        features=trade.features,
                        decision_note=trade.decision_note,
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
                position_value_points=[
                    [timestamp, value] for timestamp, value in result.position_value_points
                ],
                buy_hold_equity_points=[
                    [timestamp, value] for timestamp, value in result.buy_hold_equity_points
                ],
            )

        results = list(await asyncio.gather(*(run_one(item) for item in request.instruments)))
        _save_experiment(models, request, results)
        return results

    return router


def _save_experiment(
    models: ModelLookup, request: ReplayRequest, results: list[ReplayView]
) -> None:
    import json as _json
    from uuid import uuid4

    now = datetime.now(UTC)
    summary = {
        "model_id": request.model_id,
        "instruments": [item.instrument_id for item in request.instruments],
        "count": len(results),
        "net_return_percent": sum(item.net_return_percent for item in results),
        "trades": sum(item.buys + item.sells for item in results),
        "win_rate": (sum(item.win_rate for item in results) / len(results) if results else 0.0),
    }
    record = ExperimentRecord(
        experiment_id=str(uuid4()),
        request_json=_json.dumps(
            {
                "instruments": [
                    {
                        "instrument_id": item.instrument_id,
                        "start_date": item.start_date,
                        "end_date": item.end_date,
                    }
                    for item in request.instruments
                ],
                "model_id": request.model_id,
                "initial_cash": str(request.initial_cash),
            },
            ensure_ascii=False,
        ),
        summary_json=_json.dumps(summary, ensure_ascii=False),
        results_json=_json.dumps(
            [item.model_dump(mode="json") for item in results],
            ensure_ascii=False,
        ),
        created_at=now,
        semantic_class="LEGACY_SEMANTICS",
        evidence_class="LEGACY_UNVERIFIED",
        run_class="EXPLORATORY",
        manifest_schema="1",
        content_digest=None,
    )
    with contextlib.suppress(Exception):
        models.save_experiment(record)


async def _fetch_bars(
    market_service: Any,
    instrument_id: InstrumentId,
    start_date: date | None,
    end_date: date | None,
) -> list[MarketBar]:
    if market_service is None:
        raise ApiProblem(409, "replay_unavailable", "market service unavailable")
    days = 30
    if start_date is not None and end_date is not None:
        days = max((end_date - start_date).days + 2, 1)
    count = min(days * 240 + 240, 20_000)
    rows = await market_service.bars(
        str(instrument_id),
        period=MarketPeriod.MINUTE_1,
        count=count,
    )
    return _filter_bars(rows, start_date=start_date, end_date=end_date)


def _purged_split(
    rows: list[dict[str, float | int]],
    *,
    test_ratio: float = 0.3,
    embargo: int = 5,
) -> tuple[list[dict[str, float | int]], list[dict[str, float | int]]]:
    import math

    split_at = math.floor(len(rows) * (1 - test_ratio))
    return rows[:split_at], rows[split_at + embargo :]


def _auc(y_true: list[int], y_score: list[float]) -> float:
    pairs = sorted(zip(y_score, y_true, strict=True), key=lambda item: item[0])
    pos = sum(y_true)
    neg = len(y_true) - pos
    if pos == 0 or neg == 0:
        return 0.5
    rank_sum = sum(index + 1 for index, (_, y) in enumerate(pairs) if y == 1)
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def _best_thresholds(
    proba: list[float],
    test: list[dict[str, float | int]],
) -> dict[str, float]:
    results: list[dict[str, float]] = []
    for buy in (0.50, 0.55, 0.60):
        for sell in (0.35, 0.40, 0.45):
            trades = sum(1 for value in proba if value >= buy)
            gross = sum(
                float(row.get("future_return", 0.0))
                for index, row in enumerate(test)
                if proba[index] >= buy
            )
            net = gross - 0.0005 * trades
            results.append(
                {
                    "buy": buy,
                    "sell": sell,
                    "trades": float(trades),
                    "gross_return": gross,
                    "net_return": net,
                }
            )
    eligible = [item for item in results if item["trades"] >= 20]
    best = (
        max(eligible, key=lambda item: item["net_return"])
        if eligible
        else max(results, key=lambda item: item["net_return"])
    )
    return best


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

"""Fair, deterministic baseline comparison on shared walk-forward folds."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

import lightgbm as lgb
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import roc_auc_score  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from astraquant_quant.strategy_layer import MODEL_FEATURE_COLUMNS


class BaselineModel(StrEnum):
    NO_SKILL = "NO_SKILL"
    LOGISTIC_REGRESSION = "LOGISTIC_REGRESSION"
    LIGHTGBM = "LIGHTGBM"


class MatrixStatus(StrEnum):
    CHALLENGER = "CHALLENGER"
    NO_EDGE = "NO_EDGE"


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: str
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class FoldMetrics:
    fold_id: str
    test_rows: int
    auc: float
    gross_return: float
    net_return: float
    trades: int


@dataclass(frozen=True, slots=True)
class ModelSummary:
    model: BaselineModel
    folds: tuple[FoldMetrics, ...]
    auc: float
    gross_return: float
    net_return: float
    trades: int
    positive_folds: int


@dataclass(frozen=True, slots=True)
class BaselineMatrixReport:
    status: MatrixStatus
    challenger: BaselineModel | None
    models: tuple[ModelSummary, ...]
    seed: int
    prediction_threshold: float
    fee_rate: Decimal


def expanding_walk_forward(
    rows: Sequence[object],
    *,
    minimum_train_size: int,
    test_size: int,
    fold_count: int,
) -> tuple[WalkForwardFold, ...]:
    if minimum_train_size <= 0 or test_size <= 0 or fold_count <= 0:
        raise ValueError("walk-forward sizes must be positive")
    initial_train_size = len(rows) - test_size * fold_count
    if initial_train_size < minimum_train_size:
        raise ValueError("insufficient rows for requested walk-forward folds")
    folds = []
    for offset in range(fold_count):
        test_start = initial_train_size + offset * test_size
        test_end = test_start + test_size
        folds.append(
            WalkForwardFold(
                fold_id=f"fold-{offset + 1:02d}",
                train_indices=tuple(range(test_start)),
                test_indices=tuple(range(test_start, test_end)),
            )
        )
    return tuple(folds)


def run_baseline_matrix(
    rows: Sequence[dict[str, float | int]],
    *,
    folds: Sequence[WalkForwardFold],
    fee_rate: Decimal,
    prediction_threshold: float,
    seed: int,
) -> BaselineMatrixReport:
    if fee_rate < 0:
        raise ValueError("fee_rate must not be negative")
    if not 0 < prediction_threshold < 1:
        raise ValueError("prediction_threshold must be between zero and one")
    exact_folds = tuple(folds)
    if not exact_folds:
        raise ValueError("folds must not be empty")
    _validate_rows(rows)
    summaries = tuple(
        _evaluate_model(
            model,
            rows,
            exact_folds,
            fee_rate=fee_rate,
            prediction_threshold=prediction_threshold,
            seed=seed,
        )
        for model in BaselineModel
    )
    best = max(summaries, key=lambda value: (value.net_return, value.model.value))
    has_edge = best.net_return > 0
    return BaselineMatrixReport(
        status=MatrixStatus.CHALLENGER if has_edge else MatrixStatus.NO_EDGE,
        challenger=best.model if has_edge else None,
        models=summaries,
        seed=seed,
        prediction_threshold=prediction_threshold,
        fee_rate=fee_rate,
    )


def _validate_rows(rows: Sequence[dict[str, float | int]]) -> None:
    if not rows:
        raise ValueError("rows must not be empty")
    required = {*MODEL_FEATURE_COLUMNS, "label", "future_return"}
    if any(required - set(row) for row in rows):
        raise ValueError("rows do not contain the required model fields")
    if any(int(row["label"]) not in (0, 1) for row in rows):
        raise ValueError("labels must be binary")


def _evaluate_model(
    model: BaselineModel,
    rows: Sequence[dict[str, float | int]],
    folds: tuple[WalkForwardFold, ...],
    *,
    fee_rate: Decimal,
    prediction_threshold: float,
    seed: int,
) -> ModelSummary:
    metrics = []
    for fold in folds:
        train = [rows[index] for index in fold.train_indices]
        test = [rows[index] for index in fold.test_indices]
        probabilities = _predict(model, train, test, seed=seed)
        labels = [int(row["label"]) for row in test]
        auc = 0.5 if len(set(labels)) < 2 else float(roc_auc_score(labels, probabilities))
        selected_returns = [
            Decimal(str(row["future_return"]))
            for row, probability in zip(test, probabilities, strict=True)
            if probability >= prediction_threshold
        ]
        trades = len(selected_returns)
        gross = sum(selected_returns, start=Decimal("0"))
        net = gross - Decimal(2) * fee_rate * trades
        metrics.append(
            FoldMetrics(
                fold_id=fold.fold_id,
                test_rows=len(test),
                auc=auc,
                gross_return=float(gross),
                net_return=float(net),
                trades=trades,
            )
        )
    exact_metrics = tuple(metrics)
    return ModelSummary(
        model=model,
        folds=exact_metrics,
        auc=sum(value.auc * value.test_rows for value in exact_metrics)
        / sum(value.test_rows for value in exact_metrics),
        gross_return=sum(value.gross_return for value in exact_metrics),
        net_return=sum(value.net_return for value in exact_metrics),
        trades=sum(value.trades for value in exact_metrics),
        positive_folds=sum(value.net_return > 0 for value in exact_metrics),
    )


def _predict(
    model: BaselineModel,
    train: list[dict[str, float | int]],
    test: list[dict[str, float | int]],
    *,
    seed: int,
) -> list[float]:
    train_y = [int(row["label"]) for row in train]
    prevalence = sum(train_y) / len(train_y)
    if model is BaselineModel.NO_SKILL or len(set(train_y)) < 2:
        return [prevalence] * len(test)
    train_x = [[float(row[name]) for name in MODEL_FEATURE_COLUMNS] for row in train]
    test_x = [[float(row[name]) for name in MODEL_FEATURE_COLUMNS] for row in test]
    if model is BaselineModel.LOGISTIC_REGRESSION:
        estimator = make_pipeline(
            StandardScaler(),
            LogisticRegression(random_state=seed, max_iter=1_000),
        )
    else:
        estimator = lgb.LGBMClassifier(
            n_estimators=80,
            learning_rate=0.05,
            num_leaves=15,
            min_child_samples=10,
            random_state=seed,
            n_jobs=1,
            deterministic=True,
            force_col_wise=True,
            verbosity=-1,
        )
    estimator.fit(train_x, train_y)
    return [float(value[1]) for value in estimator.predict_proba(test_x)]

"""Deterministic Ridge and LightGBM baselines for Stage B v2."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, cast

import numpy as np
from lightgbm import LGBMRegressor
from sklearn.linear_model import Ridge  # type: ignore[import-untyped]

from astraquant_domain import ReturnCalibrationPolicy
from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest
from astraquant_quant.cross_sectional_splits import CrossSectionalFoldRows
from astraquant_quant.return_calibration import CalibrationSample, fit_huber_linear


class CrossSectionalModelKind(StrEnum):
    RIDGE = "RIDGE"
    LIGHTGBM = "LIGHTGBM"
    DOUBLE_ENSEMBLE = "DOUBLE_ENSEMBLE"
    SHARED_MLP = "SHARED_MLP"
    STOCKMIXER_V2 = "STOCKMIXER_V2"


class _Predictor(Protocol):
    def predict(self, values: np.ndarray) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class CrossSectionalBaselineRow:
    row_id: int
    decision_time: datetime
    instrument_id: str
    horizon_sessions: int
    features: Mapping[str, float]
    cross_sectional_rank: float
    market_excess_return: float
    training_eligible: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


@dataclass(frozen=True, slots=True)
class CrossSectionalPrediction:
    row_id: int
    decision_time: datetime
    instrument_id: str
    rank_score: float
    calibrated_expected_return: float


@dataclass(frozen=True, slots=True)
class CrossSectionalBaselineResult:
    model_kind: CrossSectionalModelKind
    fold_id: str
    fold_digest: str
    assignment_digest: str
    horizon_sessions: int
    seed: int
    feature_columns: tuple[str, ...]
    fit_count: int
    inner_valid_count: int
    outer_test_count: int
    processor_digest: str
    model_digest: str
    calibrator_digest: str
    calibration_policy_digest: str
    predictions: tuple[CrossSectionalPrediction, ...]
    prediction_digest: str
    evaluated_sessions: int
    positive_rank_ic_sessions: int
    mean_ic: float
    mean_rank_ic: float
    mean_top_bottom_spread: float


@dataclass(frozen=True, slots=True)
class _FoldProcessor:
    columns: tuple[str, ...]
    medians: tuple[float, ...]
    scales: tuple[float, ...]
    processor_digest: str

    def transform(self, rows: Sequence[CrossSectionalBaselineRow]) -> np.ndarray:
        matrix = _feature_matrix(rows, self.columns)
        medians = np.asarray(self.medians, dtype=np.float64)
        scales = np.asarray(self.scales, dtype=np.float64)
        imputed = np.where(np.isnan(matrix), medians, matrix)
        return np.clip((imputed - medians) / scales, -3.0, 3.0)


def run_cross_sectional_baseline(
    rows: Sequence[CrossSectionalBaselineRow],
    *,
    assignment: CrossSectionalFoldRows,
    model_kind: CrossSectionalModelKind,
    seed: int,
) -> CrossSectionalBaselineResult:
    """Train on fit only, calibrate on inner-valid, evaluate untouched outer-test."""

    return run_cross_sectional_baselines(
        rows,
        assignment=assignment,
        model_kind=model_kind,
        seeds=(seed,),
    )[0]


def run_cross_sectional_baselines(
    rows: Sequence[CrossSectionalBaselineRow],
    *,
    assignment: CrossSectionalFoldRows,
    model_kind: CrossSectionalModelKind,
    seeds: Sequence[int],
) -> tuple[CrossSectionalBaselineResult, ...]:
    """Train one fold for multiple seeds while reusing deterministic preprocessing."""

    values = tuple(rows)
    exact_seeds = tuple(seeds)
    if (
        not exact_seeds
        or len(set(exact_seeds)) != len(exact_seeds)
        or any(isinstance(seed, bool) or seed < 0 for seed in exact_seeds)
    ):
        raise ValueError("baseline seeds must be unique non-negative integers")
    columns, _ = _validate_rows(values)
    _validate_assignment(assignment, len(values))
    fit_rows = tuple(
        values[index] for index in assignment.fit_indices if values[index].training_eligible
    )
    valid_rows = tuple(values[index] for index in assignment.inner_valid_indices)
    test_rows = tuple(values[index] for index in assignment.outer_test_indices)
    if len(fit_rows) < 3 or len(valid_rows) < 3 or not test_rows:
        raise ValueError("baseline fold has insufficient fit, validation or test rows")
    processor = _fit_processor(fit_rows, columns)
    fit_x = processor.transform(fit_rows)
    valid_x = processor.transform(valid_rows)
    test_x = processor.transform(test_rows)
    fit_y = np.asarray(
        [row.cross_sectional_rank for row in fit_rows],
        dtype=np.float64,
    )
    fitted_seeds = exact_seeds[:1] if model_kind is CrossSectionalModelKind.RIDGE else exact_seeds
    fitted: dict[int, CrossSectionalBaselineResult] = {}
    for seed in fitted_seeds:
        model = _fit_model(model_kind, fit_x, fit_y, seed)
        valid_scores = np.asarray(model.predict(valid_x), dtype=np.float64)
        test_scores = np.asarray(model.predict(test_x), dtype=np.float64)
        fitted[seed] = _score_predictions(
            values,
            assignment=assignment,
            model_kind=model_kind,
            seed=seed,
            valid_scores=valid_scores,
            test_scores=test_scores,
            processor_digest=processor.processor_digest,
            model_digest=_local_model_digest(model_kind, seed),
        )
    if model_kind is CrossSectionalModelKind.RIDGE:
        base = fitted[fitted_seeds[0]]
        return tuple(replace(base, seed=seed) for seed in exact_seeds)
    return tuple(fitted[seed] for seed in exact_seeds)


def _local_model_digest(model_kind: CrossSectionalModelKind, seed: int) -> str:
    payload: dict[str, object] = {
        "model_kind": model_kind.value,
        "schema_version": "astraquant.cross-sectional-local-model/v1",
    }
    if model_kind is not CrossSectionalModelKind.RIDGE:
        payload["seed"] = seed
    return _digest(payload)


def score_cross_sectional_predictions(
    rows: Sequence[CrossSectionalBaselineRow],
    *,
    assignment: CrossSectionalFoldRows,
    model_kind: CrossSectionalModelKind,
    seed: int,
    valid_scores: Sequence[float],
    test_scores: Sequence[float],
    processor_digest: str,
    model_digest: str,
) -> CrossSectionalBaselineResult:
    """Calibrate externally trained scores without exposing outer-test labels."""

    if model_kind not in {
        CrossSectionalModelKind.DOUBLE_ENSEMBLE,
        CrossSectionalModelKind.SHARED_MLP,
        CrossSectionalModelKind.STOCKMIXER_V2,
    }:
        raise ValueError("external score contract only accepts isolated runner models")
    return _score_predictions(
        tuple(rows),
        assignment=assignment,
        model_kind=model_kind,
        seed=seed,
        valid_scores=np.asarray(valid_scores, dtype=np.float64),
        test_scores=np.asarray(test_scores, dtype=np.float64),
        processor_digest=validate_digest("processor_digest", processor_digest),
        model_digest=validate_digest("model_digest", model_digest),
    )


def _score_predictions(
    values: tuple[CrossSectionalBaselineRow, ...],
    *,
    assignment: CrossSectionalFoldRows,
    model_kind: CrossSectionalModelKind,
    seed: int,
    valid_scores: np.ndarray,
    test_scores: np.ndarray,
    processor_digest: str,
    model_digest: str,
) -> CrossSectionalBaselineResult:
    columns, horizon = _validate_rows(values)
    _validate_assignment(assignment, len(values))
    fit_rows = tuple(
        values[index] for index in assignment.fit_indices if values[index].training_eligible
    )
    valid_rows = tuple(values[index] for index in assignment.inner_valid_indices)
    test_rows = tuple(values[index] for index in assignment.outer_test_indices)
    if len(valid_scores) != len(valid_rows) or len(test_scores) != len(test_rows):
        raise ValueError("baseline score coverage does not match fold assignment")
    if not np.isfinite(valid_scores).all() or not np.isfinite(test_scores).all():
        raise ValueError("baseline model produced non-finite scores")
    calibration_policy = ReturnCalibrationPolicy.stage_b_v2()
    calibrator = fit_huber_linear(
        tuple(
            CalibrationSample(
                score=float(score),
                realized_return=row.market_excess_return,
            )
            for row, score in zip(valid_rows, valid_scores, strict=True)
        ),
        policy=calibration_policy,
        segment="inner_valid",
    )
    calibrator_digest = _digest(
        {
            "intercept": calibrator.intercept.hex(),
            "policy_digest": calibrator.policy_digest,
            "sample_count": calibrator.sample_count,
            "slope": calibrator.slope.hex(),
        }
    )
    predictions = tuple(
        CrossSectionalPrediction(
            row_id=row.row_id,
            decision_time=row.decision_time,
            instrument_id=row.instrument_id,
            rank_score=float(score),
            calibrated_expected_return=calibrator.predict(float(score)),
        )
        for row, score in zip(test_rows, test_scores, strict=True)
    )
    prediction_digest = _digest(
        [
            {
                "calibrated_expected_return": item.calibrated_expected_return.hex(),
                "decision_time": item.decision_time.isoformat(),
                "instrument_id": item.instrument_id,
                "rank_score": item.rank_score.hex(),
                "row_id": item.row_id,
            }
            for item in predictions
        ]
    )
    metrics = _metrics(test_rows, predictions)
    return CrossSectionalBaselineResult(
        model_kind=model_kind,
        fold_id=assignment.fold_id,
        fold_digest=assignment.fold_digest,
        assignment_digest=assignment.assignment_digest,
        horizon_sessions=horizon,
        seed=seed,
        feature_columns=columns,
        fit_count=len(fit_rows),
        inner_valid_count=len(valid_rows),
        outer_test_count=len(test_rows),
        processor_digest=processor_digest,
        model_digest=model_digest,
        calibrator_digest=calibrator_digest,
        calibration_policy_digest=calibration_policy.calibration_digest,
        predictions=predictions,
        prediction_digest=prediction_digest,
        evaluated_sessions=metrics[0],
        positive_rank_ic_sessions=metrics[1],
        mean_ic=metrics[2],
        mean_rank_ic=metrics[3],
        mean_top_bottom_spread=metrics[4],
    )


def _validate_rows(
    rows: tuple[CrossSectionalBaselineRow, ...],
) -> tuple[tuple[str, ...], int]:
    if not rows:
        raise ValueError("baseline rows must not be empty")
    columns = tuple(rows[0].features)
    horizons = {row.horizon_sessions for row in rows}
    if len(horizons) != 1:
        raise ValueError("baseline rows must contain exactly one horizon")
    identities: set[tuple[datetime, str]] = set()
    row_ids: set[int] = set()
    for row in rows:
        if row.decision_time.tzinfo is None or row.decision_time.utcoffset() is None:
            raise ValueError("baseline decision_time must be timezone-aware")
        if not row.instrument_id or tuple(row.features) != columns:
            raise ValueError("baseline feature schema must be canonical")
        if any(math.isinf(float(value)) for value in row.features.values()):
            raise ValueError("baseline feature values must not be infinite")
        if not math.isfinite(row.cross_sectional_rank) or not math.isfinite(
            row.market_excess_return
        ):
            raise ValueError("baseline target values must be finite")
        if not 0 <= row.cross_sectional_rank <= 1:
            raise ValueError("baseline rank target must be in [0, 1]")
        identity = (row.decision_time, row.instrument_id)
        if identity in identities or row.row_id in row_ids:
            raise ValueError("baseline row identities must be unique")
        identities.add(identity)
        row_ids.add(row.row_id)
    return columns, next(iter(horizons))


def _validate_assignment(assignment: CrossSectionalFoldRows, row_count: int) -> None:
    groups = (
        assignment.fit_indices,
        assignment.inner_valid_indices,
        assignment.outer_test_indices,
    )
    if any(not group for group in groups):
        raise ValueError("baseline assignment groups must not be empty")
    if any(index < 0 or index >= row_count for group in groups for index in group):
        raise ValueError("baseline assignment index is out of range")
    if (
        set(groups[0]) & set(groups[1])
        or set(groups[0]) & set(groups[2])
        or set(groups[1]) & set(groups[2])
    ):
        raise ValueError("baseline assignment groups must be disjoint")


def _fit_processor(
    fit_rows: tuple[CrossSectionalBaselineRow, ...],
    columns: tuple[str, ...],
) -> _FoldProcessor:
    matrix = _feature_matrix(fit_rows, columns)
    medians = np.zeros(len(columns), dtype=np.float64)
    scales = np.ones(len(columns), dtype=np.float64)
    for index in range(len(columns)):
        finite = matrix[np.isfinite(matrix[:, index]), index]
        if len(finite) == 0:
            continue
        center = float(np.median(finite))
        mad = float(np.median(np.abs(finite - center)))
        medians[index] = center
        scales[index] = max(1.4826 * mad, 1e-12)
    processor_digest = _digest(
        {
            "clip": [-3.0, 3.0],
            "columns": list(columns),
            "medians": [value.hex() for value in medians],
            "scales": [value.hex() for value in scales],
            "schema_version": "astraquant.cross-sectional-fold-processor/v1",
        }
    )
    return _FoldProcessor(
        columns=columns,
        medians=tuple(float(value) for value in medians),
        scales=tuple(float(value) for value in scales),
        processor_digest=processor_digest,
    )


def _feature_matrix(
    rows: Sequence[CrossSectionalBaselineRow],
    columns: tuple[str, ...],
) -> np.ndarray:
    return np.asarray(
        [[float(row.features[name]) for name in columns] for row in rows],
        dtype=np.float64,
    )


def _fit_model(
    model_kind: CrossSectionalModelKind,
    fit_x: np.ndarray,
    fit_y: np.ndarray,
    seed: int,
) -> _Predictor:
    if model_kind is CrossSectionalModelKind.RIDGE:
        return cast(_Predictor, Ridge(alpha=1.0).fit(fit_x, fit_y))
    if model_kind is CrossSectionalModelKind.LIGHTGBM:
        return cast(
            _Predictor,
            LGBMRegressor(
                objective="regression",
                learning_rate=0.05,
                n_estimators=80,
                num_leaves=15,
                max_depth=4,
                min_child_samples=10,
                subsample=1.0,
                colsample_bytree=1.0,
                reg_alpha=0.0,
                reg_lambda=1.0,
                random_state=seed,
                deterministic=True,
                force_col_wise=True,
                n_jobs=1,
                verbosity=-1,
            ).fit(fit_x, fit_y),
        )
    raise ValueError(f"unsupported cross-sectional model: {model_kind}")


def _metrics(
    rows: tuple[CrossSectionalBaselineRow, ...],
    predictions: tuple[CrossSectionalPrediction, ...],
) -> tuple[int, int, float, float, float]:
    by_time: dict[datetime, list[tuple[float, float, float]]] = {}
    for row, prediction in zip(rows, predictions, strict=True):
        by_time.setdefault(row.decision_time, []).append(
            (
                prediction.rank_score,
                row.cross_sectional_rank,
                row.market_excess_return,
            )
        )
    values: list[tuple[float, float, float]] = []
    for cohort in by_time.values():
        if len(cohort) < 2:
            continue
        scores = np.asarray([item[0] for item in cohort], dtype=np.float64)
        returns = np.asarray([item[2] for item in cohort], dtype=np.float64)
        ic = _correlation(scores, returns)
        rank_ic = _correlation(_average_ranks(scores), _average_ranks(returns))
        ordered = sorted(cohort, key=lambda item: item[0])
        count = max(1, math.ceil(len(ordered) * 0.1))
        bottom = sum(item[2] for item in ordered[:count]) / count
        top = sum(item[2] for item in ordered[-count:]) / count
        values.append((ic, rank_ic, top - bottom))
    if not values:
        raise ValueError("baseline outer test has no evaluable cross-sections")
    return (
        len(values),
        sum(rank_ic > 0 for _, rank_ic, _ in values),
        sum(ic for ic, _, _ in values) / len(values),
        sum(rank_ic for _, rank_ic, _ in values) / len(values),
        sum(spread for _, _, spread in values) / len(values),
    )


def _average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        rank = (position + end) / 2
        ranks[order[position : end + 1]] = rank
        position = end + 1
    return ranks


def _correlation(left: np.ndarray, right: np.ndarray) -> float:
    if np.ptp(left) <= 1e-12 or np.ptp(right) <= 1e-12:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"

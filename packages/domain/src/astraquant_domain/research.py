"""Stable contracts for comparable multi-task model training."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum


class TrainingTaskKind(StrEnum):
    """Production training tasks that may be modelled and combined independently."""

    BASE_TARGET = "BASE_TARGET"
    CROSS_SECTIONAL_ROTATION = "CROSS_SECTIONAL_ROTATION"
    TREND = "TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    INTRADAY_T = "INTRADAY_T"
    RISK = "RISK"


class ScoreSemantics(StrEnum):
    """Meaning of a model score; consumers must not infer this from its range."""

    PROBABILITY = "PROBABILITY"
    EXPECTED_RETURN = "EXPECTED_RETURN"
    CROSS_SECTIONAL_RANK = "CROSS_SECTIONAL_RANK"
    RISK_SCORE = "RISK_SCORE"


def _require_text(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class TrainingTaskSpec:
    """Model-independent identity of one fair training and evaluation task."""

    task_id: str
    kind: TrainingTaskKind
    label_name: str
    horizon_bars: int
    score_semantics: ScoreSemantics
    universe_id: str
    execution_policy_id: str
    evaluation_metrics: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _require_text("task_id", self.task_id))
        object.__setattr__(
            self,
            "label_name",
            _require_text("label_name", self.label_name),
        )
        if self.horizon_bars <= 0:
            raise ValueError("horizon_bars must be positive")
        object.__setattr__(
            self,
            "universe_id",
            _require_text("universe_id", self.universe_id),
        )
        object.__setattr__(
            self,
            "execution_policy_id",
            _require_text("execution_policy_id", self.execution_policy_id),
        )
        metrics = tuple(
            sorted(
                _require_text("evaluation_metrics item", item) for item in self.evaluation_metrics
            )
        )
        if not metrics:
            raise ValueError("evaluation_metrics must not be empty")
        if len(set(metrics)) != len(metrics):
            raise ValueError("evaluation_metrics must not contain duplicates")
        object.__setattr__(self, "evaluation_metrics", metrics)

    @property
    def task_digest(self) -> str:
        payload = {
            "evaluation_metrics": list(self.evaluation_metrics),
            "execution_policy_id": self.execution_policy_id,
            "horizon_bars": self.horizon_bars,
            "kind": self.kind.value,
            "label_name": self.label_name,
            "score_semantics": self.score_semantics.value,
            "task_id": self.task_id,
            "universe_id": self.universe_id,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    def assert_comparable_with(self, other: TrainingTaskSpec) -> None:
        """Raise when two model results do not describe the same task."""

        for field in (
            "task_id",
            "kind",
            "label_name",
            "horizon_bars",
            "score_semantics",
            "universe_id",
            "execution_policy_id",
            "evaluation_metrics",
        ):
            if getattr(self, field) != getattr(other, field):
                raise ValueError(f"training tasks differ in {field}")

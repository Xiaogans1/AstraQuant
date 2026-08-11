"""Turn S3 model evidence into held targets and canonical executable plans."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from astraquant_quant.targets import (
    ForecastEvidenceStatus,
    ForecastInput,
    ForecastTargetPolicy,
    PositionProjection,
    TargetIntentKind,
    build_base_target,
    reconcile_target,
)
from astraquant_quant.tplan import TPlanRequest, TPlanType, build_tplan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plan-targets")
    parser.add_argument("s3_report", type=Path)
    parser.add_argument("--minimum-evidence-trades", type=int, default=30)
    parser.add_argument("--current-target", type=int, default=0)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.minimum_evidence_trades <= 0:
        raise ValueError("minimum evidence trades must be positive")
    if arguments.current_target < 0:
        raise ValueError("current target must not be negative")
    raw = arguments.s3_report.read_bytes()
    payload = json.loads(raw)
    models = _models(payload)
    policy = ForecastTargetPolicy(
        enter_probability=Decimal("0.6"),
        exit_probability=Decimal("0.4"),
        max_position_percent=Decimal("20"),
        round_trip_cost_rate=Decimal("0.0005"),
    )
    model_results = {
        name: _model_plan(
            name,
            model,
            minimum_evidence_trades=arguments.minimum_evidence_trades,
            current_target=arguments.current_target,
            policy=policy,
        )
        for name, model in sorted(models.items())
    }
    report = {
        "schema_version": "astraquant.target-planning/v1",
        "source_report_sha256": hashlib.sha256(raw).hexdigest(),
        "minimum_evidence_trades": arguments.minimum_evidence_trades,
        "models": model_results,
        "canonical_validated_target": _canonical_validated_target(policy),
        "canonical_t1": _canonical_t1(),
        "canonical_tplans": _canonical_tplans(),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )
    return 0


def _models(payload: object) -> Mapping[str, Mapping[str, object]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("models"), Mapping):
        raise ValueError("S3 report must contain a models object")
    result: dict[str, Mapping[str, object]] = {}
    for name, value in payload["models"].items():
        if not isinstance(name, str) or not isinstance(value, Mapping):
            raise ValueError("S3 model entries are invalid")
        result[name] = value
    return result


def _model_plan(
    name: str,
    model: Mapping[str, object],
    *,
    minimum_evidence_trades: int,
    current_target: int,
    policy: ForecastTargetPolicy,
) -> dict[str, object]:
    trades = _integer(model, "executed_trades")
    net_return = _decimal(model, "net_return")
    if trades < minimum_evidence_trades:
        status = ForecastEvidenceStatus.INSUFFICIENT_EVIDENCE
    elif net_return <= 0:
        status = ForecastEvidenceStatus.REJECTED
    else:
        status = ForecastEvidenceStatus.VALIDATED
    target = build_base_target(
        ForecastInput(
            forecast_id=f"{name}:s3-evidence",
            probability_up=Decimal("0.5"),
            expected_return=Decimal("0"),
            evidence_status=status,
        ),
        policy,
        current_target_quantity=current_target,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )
    return {
        "executed_trades": trades,
        "net_return": str(net_return),
        "evidence_status": status.value,
        "base_target": asdict(target),
    }


def _canonical_validated_target(policy: ForecastTargetPolicy) -> dict[str, object]:
    target = build_base_target(
        ForecastInput(
            forecast_id="canonical-validated-forecast",
            probability_up=Decimal("0.75"),
            expected_return=Decimal("0.01"),
            evidence_status=ForecastEvidenceStatus.VALIDATED,
        ),
        policy,
        current_target_quantity=0,
        equity=Decimal("100000"),
        price=Decimal("10"),
    )
    return asdict(target)


def _canonical_t1() -> dict[str, object]:
    result = reconcile_target(
        target_quantity=0,
        position=PositionProjection(
            actual_quantity=2000,
            rule_sellable_quantity=1000,
            reserved_sell_quantity=0,
            working_buy_quantity=0,
            working_sell_quantity=0,
        ),
        cash_available=Decimal("0"),
        price=Decimal("10"),
        buy_cost_buffer_rate=Decimal("0.0005"),
        lot_size=100,
        intent_kind=TargetIntentKind.RISK_REDUCTION,
    )
    return asdict(result)


def _canonical_tplans() -> dict[str, object]:
    common: dict[str, Any] = {
        "base_target_quantity": 2000,
        "actual_quantity": 2000,
        "opening_sellable_quantity": 1000,
        "requested_quantity": 1000,
        "price": Decimal("10"),
        "expected_incremental_return": Decimal("0.002"),
        "round_trip_cost_rate": Decimal("0.0005"),
        "evidence_status": ForecastEvidenceStatus.VALIDATED,
        "lot_size": 100,
    }
    sell_first = build_tplan(
        TPlanRequest(
            plan_id="canonical-sell-first",
            plan_type=TPlanType.SELL_THEN_BUYBACK,
            reserved_opening_quantity=200,
            cash_available=Decimal("0"),
            **common,
        )
    )
    buy_first = build_tplan(
        TPlanRequest(
            plan_id="canonical-buy-first",
            plan_type=TPlanType.BUY_THEN_SELL_BASE,
            reserved_opening_quantity=0,
            cash_available=Decimal("5500"),
            **common,
        )
    )
    return {
        sell_first.plan_type.value: asdict(sell_first),
        buy_first.plan_type.value: asdict(buy_first),
    }


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return item


def _decimal(value: Mapping[str, object], key: str) -> Decimal:
    try:
        result = Decimal(str(value[key]))
    except (KeyError, ValueError) as error:
        raise ValueError(f"{key} must be numeric") from error
    if not result.is_finite():
        raise ValueError(f"{key} must be finite")
    return result


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())

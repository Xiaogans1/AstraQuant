"""Register a trained legacy model artifact into the Demo registry.

The AUC/net gate and ``--force`` only affect LEGACY/EXPLORATORY records.
They can never create or upgrade a FORMAL model release.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

from astraquant_api.config import RuntimeConfig
from astraquant_api.database import create_database, migrate_database
from astraquant_api.paper_repository import ModelRegistryRecord, PaperRepository


def register_approved_model(
    *,
    model_id: str,
    strategy_id: str,
    strategy_version: str,
    feature_version: str,
    artifact_path: str,
    metrics: dict[str, float],
    params: dict[str, object] | None = None,
    force: bool = False,
    run_class: str = "EXPLORATORY",
) -> str:
    if run_class != "EXPLORATORY":
        raise ValueError("legacy publish-model only supports run_class=EXPLORATORY")
    auc = float(metrics.get("auc", 0.0))
    net_return = float(metrics.get("net_return", 0.0))
    if not (math.isfinite(auc) and math.isfinite(net_return)):
        raise ValueError("metrics must be finite")
    if auc <= 0.55 or net_return <= 0.0:
        raise ValueError(
            f"publish gate failed: auc {auc:.4f} (need > 0.55), "
            f"net_return {net_return:.4f} (need > 0)"
        )
    artifact = Path(artifact_path)
    if not artifact.exists():
        raise ValueError(f"artifact not found: {artifact_path}")
    config = RuntimeConfig.from_environment()
    database_url = f"sqlite:///{config.database_path}"
    migrate_database(database_url)
    repository = PaperRepository(create_database(database_url))
    existing = repository.get_model(model_id)
    if existing is not None and not force:
        raise ValueError(f"model {model_id} already registered (use --force to update)")
    now = datetime.now(UTC)
    repository.save_model(
        ModelRegistryRecord(
            model_id=model_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            feature_version=feature_version,
            artifact_path=str(artifact.resolve()),
            metrics_json=json.dumps(metrics),
            params_json=json.dumps(params or {}),
            status="APPROVED",
            created_at=now if existing is None else existing.created_at,
            updated_at=now,
            approved_at=now,
            semantic_class="LEGACY_SEMANTICS",
            evidence_class="LEGACY_UNVERIFIED",
            run_class="EXPLORATORY",
            manifest_schema="1",
            content_digest=None,
        )
    )
    return model_id


def main() -> int:
    parser = argparse.ArgumentParser(prog="publish-model")
    parser.add_argument("model_id")
    parser.add_argument("--strategy-id", default="microstructure-lgbm")
    parser.add_argument("--strategy-version", default="lgbm-v1")
    parser.add_argument("--feature-version", default="minute-v1")
    parser.add_argument("--artifact", required=True, help="LightGBM model file path")
    parser.add_argument("--metrics", required=True, help="metrics JSON file path")
    parser.add_argument("--params", default=None, help="inference params JSON file path")
    parser.add_argument("--force", action="store_true", help="overwrite an existing model")
    parser.add_argument(
        "--run-class",
        choices=("EXPLORATORY",),
        default="EXPLORATORY",
        help="legacy tool cannot publish FORMAL models",
    )
    args = parser.parse_args()
    try:
        metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
        params = (
            None
            if args.params is None
            else json.loads(Path(args.params).read_text(encoding="utf-8"))
        )
        model_id = register_approved_model(
            model_id=args.model_id,
            strategy_id=args.strategy_id,
            strategy_version=args.strategy_version,
            feature_version=args.feature_version,
            artifact_path=args.artifact,
            metrics=metrics,
            params=params,
            force=args.force,
            run_class=args.run_class,
        )
    except (ValueError, OSError) as error:
        print(f"publish failed: {error}", file=sys.stderr)
        return 1
    print(f"legacy exploratory model registered: {model_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

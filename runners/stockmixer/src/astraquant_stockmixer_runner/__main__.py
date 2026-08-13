"""Command-line entry point for sealed StockMixer fold training."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .artifacts import write_training_artifact
from .contracts import load_request
from .stage_b_v2_shared_mlp import current_runner_identity, run_shared_mlp_request
from .training import TrainingConfig, train_fold


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="astraquant-stockmixer-runner")
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train")
    train.add_argument("request", type=Path)
    train.add_argument("--output-root", required=True, type=Path)
    train.add_argument("--fold-id", required=True, action="append")
    train.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    train.add_argument("--seed", type=int, default=20260813)
    train.add_argument("--epochs", type=int, default=50)
    train.add_argument("--batch-size", type=int, default=64)
    train.add_argument("--learning-rate", type=float, default=1e-3)
    train.add_argument("--weight-decay", type=float, default=1e-4)
    train.add_argument("--ranking-weight", type=float, default=0.1)
    train.add_argument("--validation-time-count", type=int, default=500)
    train.add_argument("--purge-time-count", type=int, default=6)
    train.add_argument("--patience", type=int, default=8)
    train.add_argument("--minimum-improvement", type=float, default=1e-8)
    train.add_argument("--hidden-dim", type=int, default=64)
    train.add_argument("--market-dim", type=int, default=32)
    train.add_argument("--scales", default="1,2,4")
    shared = commands.add_parser("shared-mlp")
    shared.add_argument("request", type=Path)
    shared.add_argument("--output", required=True, type=Path)
    identity = commands.add_parser("identity")
    identity.add_argument("--device", choices=("cpu", "cuda"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "shared-mlp":
            run_shared_mlp_request(arguments.request, arguments.output)
            print(arguments.output)
            return 0
        if arguments.command == "identity":
            print(
                json.dumps(
                    current_runner_identity(arguments.device),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0
        folds = tuple(arguments.fold_id)
        if len(folds) != len(set(folds)):
            raise ValueError("fold-id values must be unique")
        request = load_request(arguments.request)
        config = TrainingConfig(
            seed=arguments.seed,
            epochs=arguments.epochs,
            batch_size=arguments.batch_size,
            learning_rate=arguments.learning_rate,
            weight_decay=arguments.weight_decay,
            ranking_weight=arguments.ranking_weight,
            validation_time_count=arguments.validation_time_count,
            purge_time_count=arguments.purge_time_count,
            patience=arguments.patience,
            minimum_improvement=arguments.minimum_improvement,
            hidden_dim=arguments.hidden_dim,
            market_dim=arguments.market_dim,
            scales=_scales(arguments.scales),
        )
        for fold_id in folds:
            result = train_fold(
                request,
                fold_id=fold_id,
                config=config,
                device=arguments.device,
            )
            artifact = write_training_artifact(
                result,
                request=request,
                config=config,
                output_root=arguments.output_root / fold_id,
            )
            print(artifact.response_path)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"StockMixer training failed: {error}", file=sys.stderr)
        return 1
    return 0


def _scales(value: str) -> tuple[int, ...]:
    try:
        result = tuple(int(item) for item in value.split(","))
    except ValueError as error:
        raise ValueError("scales must be comma-separated integers") from error
    if not result or any(scale <= 0 for scale in result):
        raise ValueError("scales must be comma-separated positive integers")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

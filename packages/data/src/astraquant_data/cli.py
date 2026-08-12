"""Command-line entry points for reproducible local data collection."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from typing import cast

from astraquant_data.adapters.akshare import AkShareFiveMinuteBarProvider
from astraquant_data.akshare_batch import AkShareFiveMinuteBatchCollector
from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_data.provider_registry import ProviderRegistry
from astraquant_data.providers import HistoryRequest
from astraquant_domain import Adjustment, BarFrequency, InstrumentId


def main() -> None:
    parser = argparse.ArgumentParser(prog="astraquant-data")
    subcommands = parser.add_subparsers(dest="command", required=True)
    batch = subcommands.add_parser("collect-5m", help="collect exploratory A-share 5m bars")
    batch.add_argument("--provider", default="akshare")
    batch.add_argument("--date", required=True, type=date.fromisoformat)
    batch.add_argument("--instrument", action="append", required=True)
    batch.add_argument("--adjustment", choices=[item.value for item in Adjustment], default="none")
    batch.add_argument("--checkpoint", required=True, type=Path)
    batch.add_argument("--data-root", required=True, type=Path)
    batch.add_argument("--dataset-id")
    batch.add_argument("--max-workers", type=int, default=4)
    batch.add_argument("--max-attempts", type=int, default=3)
    batch.add_argument("--backoff-seconds", type=float, default=1.0)
    arguments = parser.parse_args()
    if arguments.command == "collect-5m":
        _collect_five_minute(arguments)


def _collect_five_minute(arguments: argparse.Namespace) -> None:
    registry = ProviderRegistry[AkShareFiveMinuteBarProvider]()
    registry.register("akshare", AkShareFiveMinuteBarProvider)
    provider = registry.create(str(arguments.provider))
    instruments = tuple(InstrumentId.parse(value) for value in arguments.instrument)
    adjustment = Adjustment(str(arguments.adjustment))
    collector = AkShareFiveMinuteBatchCollector(
        provider=provider,
        checkpoint_path=arguments.checkpoint,
        max_workers=arguments.max_workers,
        max_attempts=arguments.max_attempts,
        backoff_seconds=arguments.backoff_seconds,
    )
    result = collector.collect(
        instruments=instruments,
        trading_date=arguments.date,
        adjustment=adjustment,
    )
    if result.failures:
        print(
            json.dumps(
                {
                    "status": "incomplete",
                    "checkpoint": str(result.checkpoint_path),
                    "completed": [str(value) for value in result.completed],
                    "failures": [
                        {
                            "instrument_id": str(value.instrument_id),
                            "error_type": value.error_type,
                            "message": value.message,
                        }
                        for value in result.failures
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        raise SystemExit(2)
    prior_publication = _prior_publication(result.checkpoint_path, result.evidence.content_digest)
    if prior_publication is not None:
        prior_publication["resumed"] = [str(value) for value in result.resumed]
        print(json.dumps(prior_publication, ensure_ascii=False, sort_keys=True))
        return
    metadata = provider.provider_metadata(
        _metadata_request(instruments[0], arguments.date, adjustment)
    )
    dataset_id = arguments.dataset_id or _default_dataset_id(arguments.date, adjustment)
    snapshot = ParquetSnapshotStore(arguments.data_root).publish_bars(
        dataset_id=dataset_id,
        bars=result.bars,
        provider={
            "id": metadata.provider_id,
            "interface": metadata.interface,
            "version": metadata.version,
        },
        calendar_version=metadata.calendar_version,
        availability_policy=metadata.availability_policy,
        series_kind=metadata.series_kind,
        roll_policy=metadata.roll_policy,
        expected_trading_dates={arguments.date},
    )
    evidence_path = result.checkpoint_path / "published-evidence.json"
    publication: dict[str, object] = {
        "status": "published",
        "dataset_id": dataset_id,
        "snapshot_id": snapshot.snapshot_id,
        "manifest_path": str(snapshot.manifest_path),
        "evidence_path": str(evidence_path),
        "row_count": len(result.bars),
        "resumed": [str(value) for value in result.resumed],
        "artifact_id": result.evidence.artifact_id,
        "content_digest": result.evidence.content_digest,
        "evidence_class": result.evidence.evidence_class.value,
        "role": result.evidence.role.value,
        "run_class": "EXPLORATORY",
    }
    _atomic_json(evidence_path, publication)
    print(json.dumps(publication, ensure_ascii=False, sort_keys=True))


def _metadata_request(
    instrument: InstrumentId, trading_date: date, adjustment: Adjustment
) -> HistoryRequest:
    return HistoryRequest(
        instrument_id=instrument,
        frequency=BarFrequency.FIVE_MINUTE,
        start=trading_date,
        end=trading_date,
        adjustment=adjustment,
    )


def _default_dataset_id(trading_date: date, adjustment: Adjustment) -> str:
    return f"cn-equity-akshare-5m-{trading_date.isoformat()}-{adjustment.value}"


def _prior_publication(checkpoint_path: Path, content_digest: str) -> dict[str, object] | None:
    path = checkpoint_path / "published-evidence.json"
    if not path.exists():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("checkpoint publication record must be an object")
    raw = cast(dict[str, object], loaded)
    manifest_path = Path(str(raw.get("manifest_path", "")))
    if raw.get("content_digest") != content_digest or not manifest_path.is_file():
        raise ValueError("checkpoint publication record is stale or inconsistent")
    raw["status"] = "already_published"
    return raw


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)

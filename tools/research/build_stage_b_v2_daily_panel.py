"""Build a repeatable Stage B v2 daily-panel manifest from exact snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from astraquant_data.daily_panel import (
    DailyPanelSource,
    build_exact_eastmoney_daily_panel,
)
from astraquant_domain.run_manifest import canonical_json_bytes

_REQUEST_SCHEMA = "astraquant.stage-b-v2-daily-panel-request/v1"
_OUTPUT_SCHEMA = "astraquant.stage-b-v2-daily-panel/v1"


@dataclass(frozen=True, slots=True)
class _UniverseRequest:
    members_by_time: Mapping[datetime, frozenset[str]]
    snapshot_digest: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.output_root.exists():
            raise ValueError("output_root must not already exist")
        raw = _read_json(arguments.request)
        if raw.get("schema_version") != _REQUEST_SCHEMA:
            raise ValueError("daily panel request schema mismatch")
        benchmark = _source(_required_mapping(raw, "benchmark"))
        raw_sources = _required_list(raw, "sources")
        sources = tuple(_source(_mapping(item, "source")) for item in raw_sources)
        universe_raw = _required_mapping(raw, "universe")
        universe = _universe(universe_raw)
        panel = build_exact_eastmoney_daily_panel(
            data_root=arguments.data_root,
            sources=sources,
            benchmark=benchmark,
            universe=universe,
        )
        normalized_request = {
            "benchmark": _source_value(benchmark),
            "schema_version": _REQUEST_SCHEMA,
            "sources": [
                _source_value(source)
                for source in sorted(sources, key=lambda item: item.instrument_id)
            ],
            "universe": {
                "members_by_time": [
                    {
                        "decision_time": decision_time.isoformat(),
                        "members": sorted(universe.members_by_time[decision_time]),
                    }
                    for decision_time in sorted(universe.members_by_time)
                ],
                "snapshot_digest": universe.snapshot_digest,
            },
        }
        body = {
            "schema_version": _OUTPUT_SCHEMA,
            "content_digest": panel.content_digest,
            "source_digest": panel.source_digest,
            "universe_snapshot_digest": panel.universe_snapshot_digest,
            "request_digest": _digest(normalized_request),
            "request": normalized_request,
            "session_count": len(panel.sessions),
            "session_start": panel.sessions[0].isoformat(),
            "session_end": panel.sessions[-1].isoformat(),
            "instrument_count": len(panel.instrument_bars),
            "instrument_bar_counts": {
                instrument_id: len(panel.instrument_bars[instrument_id])
                for instrument_id in sorted(panel.instrument_bars)
            },
            "membership_session_count": sum(
                bool(panel.eligible_by_session[session]) for session in panel.sessions
            ),
        }
        arguments.output_root.mkdir(parents=True)
        (arguments.output_root / "panel.json").write_text(
            json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"Stage B v2 daily panel failed: {error}", file=sys.stderr)
        return 2
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(raw, "request")


def _source(raw: Mapping[str, Any]) -> DailyPanelSource:
    return DailyPanelSource(
        dataset_id=_required_text(raw, "dataset_id"),
        instrument_id=_required_text(raw, "instrument_id"),
        snapshot_id=_required_text(raw, "snapshot_id"),
    )


def _source_value(source: DailyPanelSource) -> dict[str, str]:
    return {
        "dataset_id": source.dataset_id,
        "instrument_id": source.instrument_id,
        "snapshot_id": source.snapshot_id,
    }


def _universe(raw: Mapping[str, Any]) -> _UniverseRequest:
    members: dict[datetime, frozenset[str]] = {}
    for item in _required_list(raw, "members_by_time"):
        value = _mapping(item, "universe member")
        decision_time = datetime.fromisoformat(_required_text(value, "decision_time"))
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("universe decision time must be timezone-aware")
        raw_members = _required_list(value, "members")
        exact_members = frozenset(_text(member, "universe member") for member in raw_members)
        if decision_time in members:
            raise ValueError("universe decision times must be unique")
        members[decision_time] = exact_members
    if not members:
        raise ValueError("universe members_by_time must not be empty")
    return _UniverseRequest(
        members_by_time=members,
        snapshot_digest=_required_text(raw, "snapshot_digest"),
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _required_mapping(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    return _mapping(value.get(key), key)


def _required_list(value: Mapping[str, Any], key: str) -> list[object]:
    item = value.get(key)
    if not isinstance(item, list) or not item:
        raise ValueError(f"{key} must be a non-empty list")
    return item


def _required_text(value: Mapping[str, Any], key: str) -> str:
    return _text(value.get(key), key)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


if __name__ == "__main__":
    raise SystemExit(main())

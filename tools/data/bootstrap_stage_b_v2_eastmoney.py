"""Bootstrap resumable real Eastmoney daily snapshots for Stage B v2 research."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from astraquant_api.secret_store import CredentialSecretStore
from astraquant_data.eastmoney_client import EastmoneyBridgeClient
from astraquant_data.eastmoney_daily_bootstrap import (
    DailyBootstrapCandidate,
    eastmoney_daily_rows_to_domain_bars,
    publish_compact_daily_snapshot,
    select_liquid_common_a_share_candidates,
)
from astraquant_data.eastmoney_protocol import HistoryPageSpec, from_eastmoney_symbol
from astraquant_domain.run_manifest import canonical_json_bytes

_CHINA = ZoneInfo("Asia/Shanghai")
_SCHEMA = "astraquant.stage-b-v2-eastmoney-bootstrap/v1"
_SELECTION_SCHEMA = "astraquant.stage-b-v2-eastmoney-selection/v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-python", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--target-size", type=int, default=800)
    parser.add_argument("--benchmark", default="SHSE.000985")
    parser.add_argument("--quote-batch-size", type=int, default=50)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    token = CredentialSecretStore().get_eastmoney_token()
    if token is None:
        print("Eastmoney bootstrap failed: token is not configured", file=sys.stderr)
        return 2
    client = EastmoneyBridgeClient(
        python_executable=arguments.sdk_python,
        bridge_script=Path(__file__).parents[1] / "eastmoney_bridge.py",
        timeout_seconds=arguments.timeout_seconds,
    )
    try:
        client.start()
        client.configure(token, permission_tier="configured-readonly")
        result = bootstrap_daily_snapshots(
            client=client,
            output_root=arguments.output_root,
            start=arguments.start,
            end=arguments.end,
            target_size=arguments.target_size,
            benchmark_provider_symbol=arguments.benchmark,
            quote_batch_size=arguments.quote_batch_size,
        )
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Eastmoney bootstrap failed: {error}", file=sys.stderr)
        return 2
    finally:
        client.stop()
    print(
        json.dumps(
            {
                "status": result["status"],
                "instrument_count": result["instrument_count"],
                "content_digest": result["content_digest"],
            },
            separators=(",", ":"),
        )
    )
    return 0


def bootstrap_daily_snapshots(
    *,
    client: Any,
    output_root: Path,
    start: date,
    end: date,
    target_size: int,
    benchmark_provider_symbol: str,
    quote_batch_size: int = 50,
) -> dict[str, Any]:
    """Discover, fetch and publish exact daily snapshots with per-symbol resume files."""

    if start >= end:
        raise ValueError("bootstrap start must precede end")
    if not 1 <= quote_batch_size <= 50:
        raise ValueError("quote_batch_size must be between 1 and 50")
    root = output_root.resolve()
    complete_path = root / "bootstrap.json"
    if complete_path.is_file():
        return _read_verified(complete_path, _SCHEMA)
    root.mkdir(parents=True, exist_ok=True)
    selection_path = root / "selection.json"
    if selection_path.is_file():
        selection = _read_verified(selection_path, _SELECTION_SCHEMA)
        _assert_selection_request(
            selection,
            start=start,
            end=end,
            target_size=target_size,
            benchmark_provider_symbol=benchmark_provider_symbol,
        )
        candidates = tuple(_candidate(value) for value in selection["candidates"])
        interface_build = str(selection["interface_build"])
    else:
        catalog = client.stock_instruments_with_evidence()
        instruments = _object_rows(catalog.result, "stock catalog")
        quotes: list[dict[str, Any]] = []
        quote_evidence: list[dict[str, object]] = []
        symbols = [str(item["symbol"]) for item in instruments]
        for offset in range(0, len(symbols), quote_batch_size):
            response = client.current_with_evidence(symbols[offset : offset + quote_batch_size])
            quotes.extend(_object_rows(response.result, "current quote batch"))
            quote_evidence.append(response.evidence.to_dict())
        candidates = select_liquid_common_a_share_candidates(
            instruments,
            quotes,
            as_of=end,
            target_size=target_size,
        )
        interface_build = catalog.evidence.interface_build
        selection_body: dict[str, Any] = {
            "schema_version": _SELECTION_SCHEMA,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "target_size": target_size,
            "benchmark_provider_symbol": benchmark_provider_symbol,
            "interface_build": interface_build,
            "catalog_evidence": catalog.evidence.to_dict(),
            "quote_evidence": quote_evidence,
            "candidates": [_candidate_value(item) for item in candidates],
        }
        _write_verified(selection_path, selection_body)

    provider = {
        "id": "eastmoney",
        "interface": "gm_python_sdk",
        "version": interface_build,
    }
    sources = [
        _fetch_and_publish(
            client=client,
            root=root,
            provider=provider,
            provider_symbol=candidate.provider_symbol,
            instrument_id=candidate.instrument_id,
            start=start,
            end=end,
        )
        for candidate in candidates
    ]
    benchmark_id = str(from_eastmoney_symbol(benchmark_provider_symbol))
    benchmark = _fetch_and_publish(
        client=client,
        root=root,
        provider=provider,
        provider_symbol=benchmark_provider_symbol,
        instrument_id=benchmark_id,
        start=start,
        end=end,
    )
    body: dict[str, Any] = {
        "schema_version": _SCHEMA,
        "status": "COMPLETE",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "instrument_count": len(sources),
        "provider": provider,
        "selection_digest": _read_verified(selection_path, _SELECTION_SCHEMA)["content_digest"],
        "sources": sorted(sources, key=lambda item: str(item["instrument_id"])),
        "benchmark": benchmark,
    }
    return _write_verified(complete_path, body)


def _fetch_and_publish(
    *,
    client: Any,
    root: Path,
    provider: dict[str, str],
    provider_symbol: str,
    instrument_id: str,
    start: date,
    end: date,
) -> dict[str, Any]:
    progress_root = root / "progress"
    progress_root.mkdir(exist_ok=True)
    stem = provider_symbol.replace(".", "_")
    progress_path = progress_root / f"{stem}.json"
    if progress_path.is_file():
        return _read_verified(progress_path, "astraquant.stage-b-v2-daily-source/v1")
    spec = HistoryPageSpec(
        index=0,
        page_count=1,
        cursor=f"{start.isoformat()}/{end.isoformat()}",
        start_at=datetime.combine(start, time.min, tzinfo=_CHINA).astimezone(UTC),
        end_at=datetime.combine(end + timedelta(days=1), time.min, tzinfo=_CHINA).astimezone(UTC)
        - timedelta(microseconds=1),
    )
    call = client.history_page_with_evidence(
        symbol=provider_symbol,
        frequency="1d",
        page=spec,
        adjust=0,
        units=("price=CNY", "volume=share"),
    )
    rows = tuple(call.page.rows)
    bars = eastmoney_daily_rows_to_domain_bars(instrument_id, rows)
    raw_root = root / "raw"
    raw_root.mkdir(exist_ok=True)
    raw_body = {
        "schema_version": "astraquant.stage-b-v2-eastmoney-raw/v1",
        "provider_symbol": provider_symbol,
        "response": call.response.result,
        "evidence": call.response.evidence.to_dict(),
    }
    raw = _write_verified(raw_root / f"{stem}.json", raw_body)
    dataset_id = f"cn-equity-{instrument_id.lower().replace('.', '-')}-1d-none"
    published = publish_compact_daily_snapshot(
        root / "data",
        dataset_id=dataset_id,
        bars=bars,
        provider=provider,
        source_fetched_at=call.response.evidence.received_at,
    )
    source_body: dict[str, Any] = {
        "schema_version": "astraquant.stage-b-v2-daily-source/v1",
        "dataset_id": dataset_id,
        "instrument_id": instrument_id,
        "provider_symbol": provider_symbol,
        "snapshot_id": published.snapshot_id,
        "bar_count": len(bars),
        "start": bars[0].event_time.isoformat(),
        "end": bars[-1].event_time.isoformat(),
        "raw_digest": raw["content_digest"],
    }
    return _write_verified(progress_path, source_body)


def _candidate(value: object) -> DailyBootstrapCandidate:
    if not isinstance(value, dict):
        raise ValueError("selection candidate schema mismatch")
    return DailyBootstrapCandidate(
        instrument_id=str(value["instrument_id"]),
        provider_symbol=str(value["provider_symbol"]),
        security_name=str(value["security_name"]),
        listed_on=date.fromisoformat(str(value["listed_on"])),
        delisted_on=(
            None
            if value.get("delisted_on") is None
            else date.fromisoformat(str(value["delisted_on"]))
        ),
        current_turnover=float(value["current_turnover"]),
    )


def _candidate_value(value: DailyBootstrapCandidate) -> dict[str, object]:
    return {
        "instrument_id": value.instrument_id,
        "provider_symbol": value.provider_symbol,
        "security_name": value.security_name,
        "listed_on": value.listed_on.isoformat(),
        "delisted_on": None if value.delisted_on is None else value.delisted_on.isoformat(),
        "current_turnover": value.current_turnover,
    }


def _assert_selection_request(
    value: dict[str, Any],
    *,
    start: date,
    end: date,
    target_size: int,
    benchmark_provider_symbol: str,
) -> None:
    expected = (start.isoformat(), end.isoformat(), target_size, benchmark_provider_symbol)
    observed = (
        value.get("start"),
        value.get("end"),
        value.get("target_size"),
        value.get("benchmark_provider_symbol"),
    )
    if observed != expected:
        raise ValueError("existing selection does not match bootstrap request")


def _object_rows(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return [dict(item) for item in value]


def _write_verified(path: Path, body: dict[str, Any]) -> dict[str, Any]:
    value = {"content_digest": _digest(body), **body}
    encoded = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError(f"artifact conflicts with existing content: {path.name}")
    else:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(path)
    return value


def _read_verified(path: Path, schema: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != schema:
        raise ValueError(f"artifact schema mismatch: {path.name}")
    body = {key: item for key, item in value.items() if key != "content_digest"}
    if value.get("content_digest") != _digest(body):
        raise ValueError(f"artifact digest mismatch: {path.name}")
    return value


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


if __name__ == "__main__":
    raise SystemExit(main())

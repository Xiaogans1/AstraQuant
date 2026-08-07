"""Research tool: record recent minute bars as an immutable Parquet snapshot."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta
from pathlib import Path

from astraquant_api.config import RuntimeConfig
from astraquant_api.database import create_database, migrate_database
from astraquant_api.market_config import load_eastmoney_runtime_config
from astraquant_api.repository import TaskRepository
from astraquant_api.secret_store import CredentialSecretStore
from astraquant_data.adapters.eastmoney import EastmoneyProvider
from astraquant_data.eastmoney_client import EastmoneyBridgeClient
from astraquant_data.market_bars import MarketBar, MarketPeriod
from astraquant_data.parquet_store import ParquetSnapshotStore
from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId, SystemClock

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def bars_to_domain_bars(
    instrument_id: InstrumentId,
    rows: list[MarketBar],
) -> list[Bar]:
    bars: list[Bar] = []
    for row in rows:
        bars.append(
            Bar(
                instrument_id=instrument_id,
                frequency=BarFrequency.MINUTE,
                trading_date=row.timestamp.date(),
                event_time=row.timestamp,
                available_time=row.timestamp + timedelta(minutes=1),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                turnover=row.turnover,
                open_interest=None,
                settlement=None,
                adjustment=Adjustment.NONE,
                availability_estimated=False,
            )
        )
    return bars


async def fetch_and_publish(
    *,
    instrument_id: InstrumentId,
    sdk_python: Path,
    token: str,
    bridge_script: Path,
    data_root: Path,
    count: int,
) -> Path:
    client = EastmoneyBridgeClient(
        python_executable=sdk_python,
        bridge_script=bridge_script,
    )
    provider = EastmoneyProvider(client=client, clock=SystemClock())
    try:
        await asyncio.to_thread(provider.connect, token)
        rows = await asyncio.to_thread(
            provider.bars,
            instrument_id,
            period=MarketPeriod.MINUTE_1,
            count=count,
        )
    finally:
        await asyncio.to_thread(provider.disconnect)
    if not rows:
        raise ValueError("Eastmoney returned no minute bars")
    bars = bars_to_domain_bars(instrument_id, rows)
    snapshot = ParquetSnapshotStore(data_root).publish_bars(
        dataset_id=f"cn-equity-{instrument_id}-1m-none".lower().replace(".", "-"),
        bars=bars,
        provider={"id": "eastmoney", "interface": "bridge", "version": "1"},
        calendar_version="eastmoney",
        availability_policy="bar_end",
        expected_trading_dates={bar.trading_date for bar in bars},
        source_fetched_at=max(bar.available_time for bar in bars) + timedelta(minutes=1),
    )
    return snapshot.manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(prog="astraquant-fetch-minutes")
    parser.add_argument("instrument", help="instrument id, e.g. 159516.SZSE")
    parser.add_argument(
        "--count",
        type=int,
        default=2000,
        help="number of recent minute bars to fetch",
    )
    arguments = parser.parse_args()

    config = RuntimeConfig.from_environment()
    database_url = f"sqlite:///{config.database_path}"
    migrate_database(database_url)
    engine = create_database(database_url)
    repository = TaskRepository(engine)
    market_config = load_eastmoney_runtime_config(repository)
    token = CredentialSecretStore().get_eastmoney_token()
    if market_config.sdk_python is None or token is None:
        print("eastmoney sdk python path or token is not configured", file=sys.stderr)
        return 1
    try:
        instrument_id = InstrumentId.parse(arguments.instrument)
    except ValueError:
        print(f"无效的合约代码: {arguments.instrument}", file=sys.stderr)
        return 1
    manifest_path = asyncio.run(
        fetch_and_publish(
            instrument_id=instrument_id,
            sdk_python=market_config.sdk_python,
            token=token,
            bridge_script=_PROJECT_ROOT / "tools" / "eastmoney_bridge.py",
            data_root=config.state_dir / "data",
            count=arguments.count,
        )
    )
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

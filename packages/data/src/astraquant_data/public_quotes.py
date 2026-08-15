"""Small, bounded public-web quote clients for exploratory macOS market views."""

from __future__ import annotations

import json
import re
import ssl
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import certifi

from astraquant_domain import InstrumentId, LiveQuote, MarketEventQuality, Venue

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TIMEOUT_SECONDS = 8
_INDEX_IDS = frozenset(
    {"000001.SSE", "399001.SZSE", "399006.SZSE", "000688.SSE", "000300.SSE", "399852.SZSE"}
)


def fetch_public_quotes(
    instruments: Sequence[InstrumentId], received: datetime
) -> tuple[list[LiveQuote], int]:
    """Fetch only requested symbols, preferring Tencent and failing over to Sina."""
    if not instruments:
        return [], 0
    errors: list[Exception] = []
    for fetcher in (_fetch_tencent, _fetch_sina):
        try:
            return fetcher(instruments, received)
        except Exception as error:
            errors.append(error)
    details = "; ".join(f"{type(error).__name__}: {error}" for error in errors)
    raise ConnectionError(f"public quote providers unavailable ({details})")


def search_public_instruments(query: str, *, limit: int = 30) -> list[dict[str, str]]:
    """Search Tencent's bounded suggestion endpoint without downloading the whole market."""
    needle = query.strip()
    if not needle:
        return []
    payload = _download(f"https://smartbox.gtimg.cn/s3/?q={quote(needle)}&t=all")
    match = re.fullmatch(r'v_hint="(?P<body>.*)";?', payload.strip())
    if match is None:
        raise ValueError("Tencent search returned an invalid payload")
    decoded = json.loads(f'"{match.group("body")}"')
    results: list[dict[str, str]] = []
    for item in decoded.split("^"):
        fields = item.split("~")
        if len(fields) < 3 or fields[0] not in {"sh", "sz", "bj"}:
            continue
        venue = {"sh": "SSE", "sz": "SZSE", "bj": "BSE"}[fields[0]]
        results.append(
            {
                "instrument_id": f"{fields[1]}.{venue}",
                "symbol": fields[1],
                "sec_name": fields[2],
                "name": fields[2],
            }
        )
        if len(results) >= limit:
            break
    return results


def _fetch_tencent(
    instruments: Sequence[InstrumentId], received: datetime
) -> tuple[list[LiveQuote], int]:
    symbols = ",".join(_wire_symbol(item) for item in instruments)
    payload = _download(f"https://qt.gtimg.cn/q={symbols}")
    rows = {
        match.group("symbol"): match.group("body").split("~")
        for match in re.finditer(r'v_(?P<symbol>[a-z]{2}\d+)="(?P<body>[^"]*)";', payload)
    }
    quotes: list[LiveQuote] = []
    parse_errors = 0
    for instrument in instruments:
        fields = rows.get(_wire_symbol(instrument))
        try:
            if fields is None or len(fields) < 38:
                raise ValueError("missing Tencent quote row")
            event_time = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(tzinfo=_SHANGHAI)
            volume_multiplier = Decimal("1") if str(instrument) in _INDEX_IDS else Decimal("100")
            quotes.append(
                _quote(
                    instrument,
                    received=received,
                    event_time=event_time,
                    last=fields[3],
                    previous_close=fields[4],
                    opened=fields[5],
                    high=fields[33],
                    low=fields[34],
                    volume=Decimal(fields[6]) * volume_multiplier,
                    turnover=Decimal(fields[37]) * Decimal("10000"),
                    source_id="tencent-public-web",
                )
            )
        except (ArithmeticError, TypeError, ValueError):
            parse_errors += 1
    if not quotes:
        raise ValueError("Tencent returned no usable quotes")
    return quotes, parse_errors


def _fetch_sina(
    instruments: Sequence[InstrumentId], received: datetime
) -> tuple[list[LiveQuote], int]:
    symbols = ",".join(_wire_symbol(item) for item in instruments)
    payload = _download(
        f"https://hq.sinajs.cn/list={symbols}", referer="https://finance.sina.com.cn/"
    )
    rows = {
        match.group("symbol"): match.group("body").split(",")
        for match in re.finditer(r'var hq_str_(?P<symbol>[a-z]{2}\d+)="(?P<body>[^"]*)";', payload)
    }
    quotes: list[LiveQuote] = []
    parse_errors = 0
    for instrument in instruments:
        fields = rows.get(_wire_symbol(instrument))
        try:
            if fields is None or len(fields) < 32:
                raise ValueError("missing Sina quote row")
            event_time = datetime.fromisoformat(f"{fields[30]}T{fields[31]}").replace(
                tzinfo=_SHANGHAI
            )
            quotes.append(
                _quote(
                    instrument,
                    received=received,
                    event_time=event_time,
                    last=fields[3],
                    previous_close=fields[2],
                    opened=fields[1],
                    high=fields[4],
                    low=fields[5],
                    volume=fields[8],
                    turnover=fields[9],
                    source_id="sina-public-web",
                )
            )
        except (ArithmeticError, TypeError, ValueError):
            parse_errors += 1
    if not quotes:
        raise ValueError("Sina returned no usable quotes")
    return quotes, parse_errors


def _quote(
    instrument: InstrumentId,
    *,
    received: datetime,
    event_time: datetime,
    last: object,
    previous_close: object,
    opened: object,
    high: object,
    low: object,
    volume: object,
    turnover: object,
    source_id: str,
) -> LiveQuote:
    last_price = _positive(last)
    open_price = _positive_or(opened, last_price)
    high_price = max(_positive_or(high, last_price), open_price, last_price)
    low_price = min(_positive_or(low, last_price), open_price, last_price)
    return LiveQuote(
        instrument_id=instrument,
        trading_date=event_time.date(),
        event_time=event_time,
        received_time=received,
        last_price=last_price,
        previous_close=_optional_positive(previous_close),
        open=open_price,
        high=high_price,
        low=low_price,
        cumulative_volume=Decimal(str(volume)),
        cumulative_turnover=Decimal(str(turnover)),
        open_interest=None,
        bid=(),
        ask=(),
        source_id=source_id,
        quality=frozenset({MarketEventQuality.DELAYED}),
    )


def _download(url: str, *, referer: str | None = None) -> str:
    headers = {"User-Agent": "Mozilla/5.0 AstraQuant/0.1"}
    if referer is not None:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(request, timeout=_TIMEOUT_SECONDS, context=ssl_context) as response:
        payload: bytes = response.read()
    return payload.decode("gb18030")


def _wire_symbol(instrument: InstrumentId) -> str:
    prefix = {Venue.SSE: "sh", Venue.SZSE: "sz", Venue.BSE: "bj"}.get(instrument.venue)
    if prefix is None:
        raise ValueError(f"unsupported public quote venue: {instrument.venue}")
    return f"{prefix}{instrument.symbol}"


def _positive(value: object) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("price must be positive")
    return parsed


def _positive_or(value: object, fallback: Decimal) -> Decimal:
    try:
        return _positive(value)
    except (ArithmeticError, ValueError):
        return fallback


def _optional_positive(value: object) -> Decimal | None:
    try:
        return _positive(value)
    except (ArithmeticError, ValueError):
        return None

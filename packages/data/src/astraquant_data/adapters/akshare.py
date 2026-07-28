"""AKShare daily-bar normalization behind AstraQuant's read-only contracts."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from importlib.metadata import version
from typing import Any

from astraquant_data.calendars import TradingCalendar
from astraquant_data.providers import HistoryRequest
from astraquant_domain import Adjustment, Bar, BarFrequency, Venue

_EQUITY_VENUES = frozenset({Venue.SSE, Venue.SZSE, Venue.BSE})
_FUTURES_VENUES = frozenset({Venue.CFFEX, Venue.SHFE, Venue.DCE, Venue.CZCE, Venue.INE, Venue.GFEX})
_EQUITY_COLUMNS = frozenset({"日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"})
_FUTURES_COLUMNS = frozenset({"date", "open", "high", "low", "close", "volume", "hold", "settle"})


class ProviderSchemaError(ValueError):
    def __init__(self, provider_id: str, missing_columns: set[str]) -> None:
        self.provider_id = provider_id
        self.missing_columns = frozenset(missing_columns)
        missing = ", ".join(sorted(missing_columns))
        super().__init__(f"{provider_id} response missing required columns: {missing}")


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    provider_id: str
    interface: str
    version: str
    volume_unit: str
    series_kind: str
    roll_policy: str | None
    calendar_version: str
    availability_policy: str = "estimated_session_close_plus_1m"


class AkShareDailyBarProvider:
    def __init__(
        self,
        *,
        calendars: Mapping[Venue, TradingCalendar],
        client: Any | None = None,
    ) -> None:
        if client is None:
            import akshare  # type: ignore[import-untyped]

            client = akshare
        self._client = client
        self._calendars = dict(calendars)

    def provider_id(self) -> str:
        return "akshare"

    def provider_metadata(self, request: HistoryRequest) -> ProviderMetadata:
        venue = request.instrument_id.venue
        calendar = self._calendar(venue)
        if venue in _EQUITY_VENUES:
            interface = "stock_zh_a_hist"
            volume_unit = "share"
            series_kind = "instrument"
            roll_policy = None
        elif venue in _FUTURES_VENUES:
            interface = "futures_zh_daily_sina"
            volume_unit = "contract"
            continuous = request.instrument_id.symbol.endswith("0")
            series_kind = "continuous" if continuous else "contract"
            roll_policy = "upstream_provider" if continuous else None
        else:
            raise ValueError(f"unsupported AKShare venue: {venue.value}")
        return ProviderMetadata(
            provider_id=self.provider_id(),
            interface=interface,
            version=version("akshare"),
            volume_unit=volume_unit,
            series_kind=series_kind,
            roll_policy=roll_policy,
            calendar_version=calendar.calendar_version,
        )

    def fetch_bars(self, request: HistoryRequest) -> Sequence[Bar]:
        if request.frequency is not BarFrequency.DAY:
            raise ValueError("AKShare daily provider only supports 1d bars")
        venue = request.instrument_id.venue
        if venue in _EQUITY_VENUES:
            frame = self._client.stock_zh_a_hist(
                symbol=request.instrument_id.symbol,
                period="daily",
                start_date=request.start.strftime("%Y%m%d"),
                end_date=request.end.strftime("%Y%m%d"),
                adjust=("" if request.adjustment is Adjustment.NONE else request.adjustment.value),
                timeout=15,
            )
            self._require_columns(set(frame.columns), _EQUITY_COLUMNS)
            return tuple(
                self._equity_bar(request, row)
                for row in frame.to_dict(orient="records")
                if request.start <= _as_date(row["日期"]) <= request.end
            )
        if venue in _FUTURES_VENUES:
            if request.adjustment is not Adjustment.NONE:
                raise ValueError("futures daily bars do not accept stock adjustment modes")
            frame = self._client.futures_zh_daily_sina(symbol=request.instrument_id.symbol)
            self._require_columns(set(frame.columns), _FUTURES_COLUMNS)
            return tuple(
                self._futures_bar(request, row)
                for row in frame.to_dict(orient="records")
                if request.start <= _as_date(row["date"]) <= request.end
            )
        raise ValueError(f"unsupported AKShare venue: {venue.value}")

    def _equity_bar(self, request: HistoryRequest, row: Mapping[str, Any]) -> Bar:
        trading_date = _as_date(row["日期"])
        session = self._calendar(request.instrument_id.venue).session(trading_date)
        return Bar(
            instrument_id=request.instrument_id,
            frequency=request.frequency,
            trading_date=trading_date,
            event_time=session.session_close,
            available_time=session.session_close + timedelta(minutes=1),
            open=_decimal(row["开盘"]),
            high=_decimal(row["最高"]),
            low=_decimal(row["最低"]),
            close=_decimal(row["收盘"]),
            volume=_decimal(row["成交量"]) * 100,
            turnover=_decimal(row["成交额"]),
            open_interest=None,
            settlement=None,
            adjustment=request.adjustment,
            availability_estimated=True,
        )

    def _futures_bar(self, request: HistoryRequest, row: Mapping[str, Any]) -> Bar:
        trading_date = _as_date(row["date"])
        session = self._calendar(request.instrument_id.venue).session(trading_date)
        return Bar(
            instrument_id=request.instrument_id,
            frequency=request.frequency,
            trading_date=trading_date,
            event_time=session.session_close,
            available_time=session.session_close + timedelta(minutes=1),
            open=_decimal(row["open"]),
            high=_decimal(row["high"]),
            low=_decimal(row["low"]),
            close=_decimal(row["close"]),
            volume=_decimal(row["volume"]),
            turnover=None,
            open_interest=_decimal(row["hold"]),
            settlement=_decimal(row["settle"]),
            adjustment=Adjustment.NONE,
            availability_estimated=True,
        )

    def _calendar(self, venue: Venue) -> TradingCalendar:
        try:
            return self._calendars[venue]
        except KeyError:
            raise ValueError(f"missing versioned calendar for {venue.value}") from None

    def _require_columns(self, actual: set[str], required: frozenset[str]) -> None:
        missing = set(required - actual)
        if missing:
            raise ProviderSchemaError(self.provider_id(), missing)


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))

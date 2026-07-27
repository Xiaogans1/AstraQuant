"""Order values shared by backtest, Paper, and Live environments."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from astraquant_domain.identifiers import InstrumentId


class Environment(StrEnum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


@dataclass(frozen=True, slots=True)
class OrderRequest:
    client_order_id: UUID
    instrument_id: InstrumentId
    environment: Environment
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    time_in_force: TimeInForce
    limit_price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for LIMIT orders")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price must be omitted for MARKET orders")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("limit_price must be positive")

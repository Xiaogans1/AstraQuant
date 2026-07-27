"""Canonical identifiers for supported Chinese exchanges."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]*$")


class Venue(StrEnum):
    """Trading venue code used in canonical instrument identifiers."""

    SSE = "SSE"
    SZSE = "SZSE"
    BSE = "BSE"
    CFFEX = "CFFEX"
    SHFE = "SHFE"
    DCE = "DCE"
    CZCE = "CZCE"
    INE = "INE"
    GFEX = "GFEX"


@dataclass(frozen=True, slots=True, order=True)
class InstrumentId:
    """A canonical instrument key such as ``600000.SSE`` or ``RB2610.SHFE``."""

    symbol: str
    venue: Venue

    def __post_init__(self) -> None:
        normalized = self.symbol.strip().upper()
        if not _SYMBOL_PATTERN.fullmatch(normalized):
            raise ValueError(f"Invalid instrument symbol: {self.symbol!r}")
        object.__setattr__(self, "symbol", normalized)

    @classmethod
    def parse(cls, value: str) -> Self:
        parts = value.strip().split(".")
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"Invalid instrument identifier: {value!r}")
        symbol, venue = parts
        try:
            return cls(symbol=symbol, venue=Venue(venue.upper()))
        except ValueError as error:
            raise ValueError(f"Invalid instrument identifier: {value!r}") from error

    def __str__(self) -> str:
        return f"{self.symbol}.{self.venue.value}"

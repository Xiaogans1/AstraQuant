import pytest

from astraquant_domain.identifiers import InstrumentId, Venue


def test_parse_equity_identifier() -> None:
    instrument = InstrumentId.parse("600000.SSE")

    assert instrument.symbol == "600000"
    assert instrument.venue is Venue.SSE
    assert str(instrument) == "600000.SSE"


def test_normalize_futures_symbol_to_uppercase() -> None:
    instrument = InstrumentId.parse("rb2610.SHFE")

    assert str(instrument) == "RB2610.SHFE"


@pytest.mark.parametrize("value", ["", "600000", ".SSE", "600000.UNKNOWN", "600000.SSE.EXTRA"])
def test_reject_invalid_identifier(value: str) -> None:
    with pytest.raises(ValueError):
        InstrumentId.parse(value)

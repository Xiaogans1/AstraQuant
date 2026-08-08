import pytest

from astraquant_data.subscriptions import (
    CORE_INDICES,
    SubscriptionBudget,
    SubscriptionLimitReached,
)


def test_six_core_indices_are_always_first() -> None:
    budget = SubscriptionBudget()
    assert budget.active_instruments() == tuple(item.instrument_id for item in CORE_INDICES)
    assert len(CORE_INDICES) == 6


def test_persistent_and_temporary_lanes_respect_fifty_slot_budget() -> None:
    budget = SubscriptionBudget()
    for index in range(34):
        budget.add_persistent(f"{600000 + index}.SSE")
    for index in range(11):
        budget.add_temporary(f"{510000 + index}.SSE")

    active = budget.active_instruments()
    assert len(active) == 50
    assert "510000.SSE" not in active
    assert "510010.SSE" in active


def test_duplicate_instruments_consume_one_slot() -> None:
    budget = SubscriptionBudget()
    budget.add_persistent("600000.SSE")
    budget.add_persistent("600000.SSE")
    budget.add_temporary("600000.SSE")
    assert budget.active_instruments().count("600000.SSE") == 1


def test_full_persistent_lane_raises_instead_of_dropping_data() -> None:
    budget = SubscriptionBudget()
    for index in range(34):
        budget.add_persistent(f"{600000 + index}.SSE")
    with pytest.raises(SubscriptionLimitReached):
        budget.add_persistent("700000.SSE")


def test_core_indices_cannot_be_removed() -> None:
    budget = SubscriptionBudget()
    with pytest.raises(ValueError, match="core"):
        budget.remove("000001.SSE")


def test_promoting_temporary_instrument_to_persistent_keeps_one_copy() -> None:
    budget = SubscriptionBudget()
    budget.add_temporary("600000.SSE")
    budget.add_persistent("600000.SSE")
    assert budget.active_instruments().count("600000.SSE") == 1
    assert budget.persistent_instruments == ("600000.SSE",)

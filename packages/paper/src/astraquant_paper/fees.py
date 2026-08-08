"""Fee rules for the Paper ledger (single source: ``astraquant_domain.fees``).

Kept as a module for import compatibility; the canonical implementation lives
in the domain package so backtest, Paper and Live runtimes share one schedule.
"""

from astraquant_domain.fees import FeeBreakdown, FeeSchedule

__all__ = ["FeeBreakdown", "FeeSchedule"]

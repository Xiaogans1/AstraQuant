"""Built-in read-only market-data adapters."""

from astraquant_data.adapters.eastmoney import EastmoneyProvider
from astraquant_data.adapters.eastmoney_batch import EastmoneyBatchAdapter

__all__ = ["EastmoneyBatchAdapter", "EastmoneyProvider"]

import type { KLineData } from "klinecharts";

import type { MarketBar } from "../../api/market-contracts";

export function normalizeMarketBars(rows: MarketBar[]): KLineData[] {
  const unique = new Map<number, KLineData>();
  for (const row of rows) {
    const timestamp = Date.parse(row.timestamp);
    if (!Number.isFinite(timestamp)) {
      throw new Error("Market bar timestamp is invalid");
    }
    const prices = [row.open, row.high, row.low, row.close];
    if (
      prices.some((value) => !Number.isFinite(value) || value <= 0)
      || row.high < Math.max(row.open, row.close)
      || row.low > Math.min(row.open, row.close)
      || row.low > row.high
    ) {
      throw new Error("Market bar OHLC is invalid");
    }
    if (
      !Number.isFinite(row.volume)
      || row.volume < 0
      || !Number.isFinite(row.turnover)
      || row.turnover < 0
    ) {
      throw new Error("Market bar volume is invalid");
    }
    unique.set(timestamp, {
      timestamp,
      open: row.open,
      high: row.high,
      low: row.low,
      close: row.close,
      volume: row.volume,
      turnover: row.turnover,
    });
  }
  return [...unique.values()].sort((left, right) => left.timestamp - right.timestamp);
}

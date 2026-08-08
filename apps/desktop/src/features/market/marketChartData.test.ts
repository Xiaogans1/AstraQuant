import type { MarketBar } from "../../api/market-contracts";
import { normalizeMarketBars } from "./marketChartData";

const base: MarketBar = {
  timestamp: "2026-08-06T02:00:00Z",
  open: 0.701,
  high: 0.715,
  low: 0.699,
  close: 0.712,
  volume: 481_900,
  turnover: 34_260_000,
  previous_close: 0.701,
};

it("converts, sorts and deduplicates strict bars for KLineChart", () => {
  const bars = normalizeMarketBars([
    { ...base, timestamp: "2026-08-06T02:01:00Z", close: 0.710 },
    base,
    { ...base, timestamp: "2026-08-06T02:01:00Z", close: 0.713 },
  ]);

  expect(bars).toEqual([
    {
      timestamp: Date.parse("2026-08-06T02:00:00Z"),
      open: 0.701,
      high: 0.715,
      low: 0.699,
      close: 0.712,
      volume: 481_900,
      turnover: 34_260_000,
    },
    {
      timestamp: Date.parse("2026-08-06T02:01:00Z"),
      open: 0.701,
      high: 0.715,
      low: 0.699,
      close: 0.713,
      volume: 481_900,
      turnover: 34_260_000,
    },
  ]);
});

it("rejects malformed timestamps and inconsistent OHLC", () => {
  expect(() => normalizeMarketBars([{ ...base, timestamp: "not-a-time" }])).toThrow(
    "timestamp",
  );
  expect(() => normalizeMarketBars([{ ...base, high: 0.700 }])).toThrow("OHLC");
});

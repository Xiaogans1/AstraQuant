import { describe, expect, it } from "vitest";

import type { MarketBar, QuoteCard } from "../../api/market-contracts";
import { mergeLiveQuoteIntoIntradayBars } from "./liveIntraday";

const bars: MarketBar[] = [
  {
    timestamp: "2026-08-06T10:02:00+08:00",
    open: 0.7,
    high: 0.71,
    low: 0.69,
    close: 0.705,
    volume: 12_000,
    turnover: 8_460,
    previous_close: 0.701,
  },
];

describe("mergeLiveQuoteIntoIntradayBars", () => {
  it("updates the current minute high low and close without mutating history", () => {
    const result = mergeLiveQuoteIntoIntradayBars(
      bars,
      quoteAt("2026-08-06T10:02:20+08:00", "0.715"),
    );

    expect(result).not.toBe(bars);
    expect(result).toEqual([
      {
        ...bars[0],
        high: 0.715,
        close: 0.715,
      },
    ]);
    expect(bars[0]?.close).toBe(0.705);
  });

  it("extends the current minute low when the live price falls", () => {
    const result = mergeLiveQuoteIntoIntradayBars(
      bars,
      quoteAt("2026-08-06T10:02:40+08:00", "0.685"),
    );

    expect(result[0]).toMatchObject({ low: 0.685, close: 0.685 });
  });

  it("appends a provisional zero-volume bar for a newer minute", () => {
    const result = mergeLiveQuoteIntoIntradayBars(
      bars,
      quoteAt("2026-08-06T10:03:01+08:00", "0.716"),
    );

    expect(result).toHaveLength(2);
    expect(result[1]).toEqual({
      timestamp: "2026-08-06T02:03:00.000Z",
      open: 0.716,
      high: 0.716,
      low: 0.716,
      close: 0.716,
      volume: 0,
      turnover: 0,
      previous_close: 0.701,
    });
  });

  it.each([
    ["invalid price", quoteAt("2026-08-06T10:03:01+08:00", "0")],
    ["missing event time", quoteAt(null, "0.716")],
    ["lunch break", quoteAt("2026-08-06T12:00:00+08:00", "0.716")],
    ["out of order", quoteAt("2026-08-06T10:01:59+08:00", "0.716")],
  ])("ignores %s snapshots", (_label, quote) => {
    expect(mergeLiveQuoteIntoIntradayBars(bars, quote)).toBe(bars);
  });
});

function quoteAt(eventTime: string | null, lastPrice: string): QuoteCard {
  return {
    instrument_id: "159516.SZSE",
    name: "半导体设备ETF",
    kind: "fund",
    state: "LIVE",
    event_time: eventTime,
    last_price: lastPrice,
    change: "0.011",
    change_percent: "1.57",
    previous_close: "0.701",
    open: "0.680",
    high: "0.716",
    low: "0.677",
    volume: "481900",
    turnover: "34260000",
    source_id: "eastmoney",
  };
}

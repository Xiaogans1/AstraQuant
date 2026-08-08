import type { KLineData } from "klinecharts";

import { calculateIntradayAverage } from "./intradayAverage";

function bar(overrides: Partial<KLineData> = {}): KLineData {
  return {
    timestamp: Date.parse("2026-08-06T09:30:00+08:00"),
    open: 10,
    high: 10,
    low: 10,
    close: 10,
    volume: 100,
    turnover: 1_000,
    ...overrides,
  };
}

it("calculates the cumulative intraday average from real turnover and volume", () => {
  expect(calculateIntradayAverage([
    bar(),
    bar({
      timestamp: Date.parse("2026-08-06T09:31:00+08:00"),
      open: 12,
      high: 12,
      low: 12,
      close: 12,
      turnover: 1_200,
    }),
  ])).toEqual([
    { average: 10 },
    { average: 11 },
  ]);
});

it("falls back to typical price only for a bar with missing turnover", () => {
  expect(calculateIntradayAverage([
    bar({
      high: 12,
      low: 9,
      close: 9,
      turnover: 0,
    }),
  ])).toEqual([{ average: 10 }]);
});

it("does not invent an average before the first positive-volume bar", () => {
  expect(calculateIntradayAverage([
    bar({ volume: 0, turnover: 0 }),
    bar({
      timestamp: Date.parse("2026-08-06T09:31:00+08:00"),
      close: 11,
      high: 11,
      low: 11,
      volume: 50,
      turnover: 550,
    }),
  ])).toEqual([
    {},
    { average: 11 },
  ]);
});


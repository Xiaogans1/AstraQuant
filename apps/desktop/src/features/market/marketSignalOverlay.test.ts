import {
  toSignalOverlays,
  type MarketSignalMarker,
} from "./marketSignalOverlay";

it("never creates a marker when the quant core supplied no signal", () => {
  expect(toSignalOverlays([])).toEqual([]);
});

it("maps explicit quant signals without changing price or time", () => {
  const signals: MarketSignalMarker[] = [
    {
      id: "signal-buy-1",
      timestamp: 1_775_615_400_000,
      side: "BUY",
      price: 0.701,
      label: "放量突破",
      source: "QUANT",
    },
    {
      id: "signal-sell-1",
      timestamp: 1_775_619_000_000,
      side: "SELL",
      price: 0.715,
      label: "风控退出",
      source: "QUANT",
    },
  ];

  expect(toSignalOverlays(signals)).toEqual([
    {
      id: "signal-buy-1",
      timestamp: 1_775_615_400_000,
      price: 0.701,
      tag: "B",
      label: "放量突破",
      side: "BUY",
    },
    {
      id: "signal-sell-1",
      timestamp: 1_775_619_000_000,
      price: 0.715,
      tag: "S",
      label: "风控退出",
      side: "SELL",
    },
  ]);
});

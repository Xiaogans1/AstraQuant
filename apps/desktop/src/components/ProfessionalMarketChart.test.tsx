import { act, render, screen } from "@testing-library/react";
import type { DataLoaderGetBarsParams } from "klinecharts";

import type { MarketBar } from "../api/market-contracts";
import { ProfessionalMarketChart } from "./ProfessionalMarketChart";

const { chart, dispose, init, registerIndicator, registerOverlay } = vi.hoisted(() => {
  const chart = {
    setTimezone: vi.fn(),
    setSymbol: vi.fn(),
    setPeriod: vi.fn(),
    setStyles: vi.fn(),
    setDataLoader: vi.fn(),
    resetData: vi.fn(),
    removeIndicator: vi.fn(),
    createIndicator: vi.fn(),
    setRightMinVisibleBarCount: vi.fn(),
    setOffsetRightDistance: vi.fn(),
    setBarSpace: vi.fn(),
    getBarSpace: vi.fn(),
    scrollToRealTime: vi.fn(),
    convertFromPixel: vi.fn(),
    createOverlay: vi.fn(),
    removeOverlay: vi.fn(),
    subscribeAction: vi.fn(),
    unsubscribeAction: vi.fn(),
    resize: vi.fn(),
  };
  return {
    chart,
    dispose: vi.fn(),
    init: vi.fn(() => chart),
    registerIndicator: vi.fn(),
    registerOverlay: vi.fn(),
  };
});

vi.mock("klinecharts", () => ({
  init,
  dispose,
  registerIndicator,
  registerOverlay,
}));

class ResizeObserverMock {
  observe = vi.fn();
  disconnect = vi.fn();
  constructor(_callback: ResizeObserverCallback) {}
}

const bars: MarketBar[] = [
  {
    timestamp: "2026-08-06T09:30:00+08:00",
    open: 0.7,
    high: 0.71,
    low: 0.69,
    close: 0.705,
    volume: 100,
    turnover: 70.5,
    previous_close: 0.698,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  chart.getBarSpace.mockReturnValue({
    bar: 1,
    halfBar: 0.5,
    gapBar: 0.2,
    halfGapBar: 0.1,
  });
  vi.stubGlobal("ResizeObserver", ResizeObserverMock);
});

afterEach(() => vi.unstubAllGlobals());

it("loads real bars into a Shanghai-time intraday area chart", () => {
  render(
    <ProfessionalMarketChart
      instrumentId="159516.SZSE"
      period="intraday"
      mainIndicator="AVG"
      secondaryIndicator="VOL"
      showQuantSignals
      bars={bars}
    />,
  );

  expect(init).toHaveBeenCalledOnce();
  expect(chart.setTimezone).toHaveBeenCalledWith("Asia/Shanghai");
  expect(chart.setSymbol).toHaveBeenCalledWith(
    expect.objectContaining({ ticker: "159516.SZSE" }),
  );
  expect(chart.setPeriod).toHaveBeenCalledWith({ type: "minute", span: 1 });
  expect(chart.setStyles).toHaveBeenCalledWith(
    expect.objectContaining({ candle: expect.objectContaining({ type: "area" }) }),
  );
  expect(chart.setOffsetRightDistance).toHaveBeenCalledWith(
    expect.any(Number),
  );
  expect(chart.setOffsetRightDistance.mock.calls.at(-1)?.[0]).toBeGreaterThan(800);
  expect(registerIndicator).toHaveBeenCalledWith(
    expect.objectContaining({ name: "AVG" }),
  );
  expect(chart.createIndicator).toHaveBeenCalledWith(
    expect.objectContaining({ name: "AVG", paneId: "candle_pane" }),
    false,
  );
  expect(chart.createIndicator).toHaveBeenCalledWith(
    expect.objectContaining({ name: "VOL", paneId: "astraquant_secondary_pane" }),
    false,
  );
  expect(chart.removeIndicator).not.toHaveBeenCalledWith();

  const loader = chart.setDataLoader.mock.calls.at(-1)?.[0];
  const callback = vi.fn();
  loader.getBars({ callback } as unknown as DataLoaderGetBarsParams);
  expect(callback).toHaveBeenCalledWith([
    expect.objectContaining({ timestamp: Date.parse(bars[0]!.timestamp), close: 0.705 }),
  ], { backward: false, forward: false });
});

it("switches to candles and releases the chart on unmount", () => {
  const { rerender, unmount } = render(
    <ProfessionalMarketChart
      instrumentId="159516.SZSE"
      period="intraday"
      mainIndicator="AVG"
      secondaryIndicator="VOL"
      showQuantSignals
      bars={bars}
    />,
  );

  rerender(
    <ProfessionalMarketChart
      instrumentId="159516.SZSE"
      period="1d"
      mainIndicator="BOLL"
      secondaryIndicator="MACD"
      showQuantSignals
      bars={bars}
    />,
  );

  expect(chart.setPeriod).toHaveBeenLastCalledWith({ type: "day", span: 1 });
  expect(chart.setStyles).toHaveBeenLastCalledWith(
    expect.objectContaining({ candle: expect.objectContaining({ type: "candle_solid" }) }),
  );
  expect(chart.createIndicator).toHaveBeenCalledWith(
    expect.objectContaining({
      name: "BOLL",
      paneId: "candle_pane",
      calcParams: [20, 2],
    }),
    false,
  );
  expect(chart.createIndicator).toHaveBeenCalledWith(
    expect.objectContaining({ name: "MACD", paneId: "astraquant_secondary_pane" }),
    false,
  );

  unmount();
  expect(chart.unsubscribeAction).toHaveBeenCalledWith(
    "onCrosshairChange",
    expect.any(Function),
  );
  expect(dispose).toHaveBeenCalled();
});

it("shows hovered price and change together beside the crosshair", () => {
  chart.convertFromPixel.mockReturnValue([{
    value: 0.703,
    dataIndex: 0,
    timestamp: Date.parse(bars[0]!.timestamp),
  }]);
  render(
    <ProfessionalMarketChart
      instrumentId="159516.SZSE"
      period="intraday"
      mainIndicator="AVG"
      secondaryIndicator="VOL"
      showQuantSignals
      bars={bars}
    />,
  );

  const callback = chart.subscribeAction.mock.calls.find(
    ([action]) => action === "onCrosshairChange",
  )?.[1];
  expect(callback).toBeTypeOf("function");

  act(() => {
    callback({
      paneId: "candle_pane",
      x: 100,
      y: 160,
    });
  });

  expect(screen.getByRole("status", { name: "光标价格涨幅" })).toHaveTextContent(
    "0.7030+0.72%",
  );
  expect(chart.convertFromPixel).toHaveBeenCalledWith(
    [{ x: 100, y: 160 }],
    { paneId: "candle_pane" },
  );
});

it("reports the horizontally selected market bar and clears it on leave", () => {
  const onCrosshairBarChange = vi.fn();
  chart.convertFromPixel.mockReturnValue([{
    value: 0.703,
    dataIndex: 0,
    timestamp: Date.parse(bars[0]!.timestamp),
  }]);
  render(
    <ProfessionalMarketChart
      instrumentId="159516.SZSE"
      period="intraday"
      mainIndicator="AVG"
      secondaryIndicator="VOL"
      showQuantSignals
      bars={bars}
      onCrosshairBarChange={onCrosshairBarChange}
    />,
  );

  const callback = chart.subscribeAction.mock.calls.find(
    ([action]) => action === "onCrosshairChange",
  )?.[1];

  act(() => {
    callback({
      paneId: "candle_pane",
      x: 100,
      y: 160,
    });
  });
  expect(onCrosshairBarChange).toHaveBeenLastCalledWith(bars[0]);

  act(() => callback(undefined));
  expect(onCrosshairBarChange).toHaveBeenLastCalledWith(null);
});

it("keeps the last selected quote when a transient crosshair point cannot be resolved", () => {
  const onCrosshairBarChange = vi.fn();
  chart.convertFromPixel
    .mockReturnValueOnce([{
      value: 0.703,
      dataIndex: 0,
      timestamp: Date.parse(bars[0]!.timestamp),
    }])
    .mockReturnValueOnce([{
      value: 0.704,
      dataIndex: 999,
      timestamp: Date.parse(bars[0]!.timestamp) + 500,
    }]);
  render(
    <ProfessionalMarketChart
      instrumentId="159516.SZSE"
      period="intraday"
      mainIndicator="AVG"
      secondaryIndicator="VOL"
      showQuantSignals
      bars={bars}
      onCrosshairBarChange={onCrosshairBarChange}
    />,
  );
  const callback = chart.subscribeAction.mock.calls.find(
    ([action]) => action === "onCrosshairChange",
  )?.[1];

  act(() => callback({ paneId: "candle_pane", x: 100, y: 160 }));
  act(() => callback({ paneId: "candle_pane", x: 101, y: 160 }));

  expect(onCrosshairBarChange).toHaveBeenCalledTimes(1);
  expect(onCrosshairBarChange).toHaveBeenLastCalledWith(bars[0]);
});

it("renders only explicit quant buy and sell decisions as chart overlays", () => {
  render(
    <ProfessionalMarketChart
      instrumentId="159516.SZSE"
      period="intraday"
      mainIndicator="AVG"
      secondaryIndicator="VOL"
      showQuantSignals
      bars={bars}
      signals={[
        {
          id: "signal-buy",
          timestamp: Date.parse("2026-08-06T09:30:00+08:00"),
          side: "BUY",
          price: 0.705,
          label: "量价动量买入观察",
          source: "QUANT",
        },
      ]}
    />,
  );

  expect(registerOverlay).toHaveBeenCalledWith(
    expect.objectContaining({ name: "astraquantSignal" }),
  );
  expect(chart.removeOverlay).toHaveBeenCalledWith({
    groupId: "astraquant-quant-signals",
  });
  expect(chart.createOverlay).toHaveBeenCalledWith(
    expect.objectContaining({
      name: "astraquantSignal",
      groupId: "astraquant-quant-signals",
      points: [{ timestamp: Date.parse("2026-08-06T09:30:00+08:00"), value: 0.705 }],
      extendData: expect.objectContaining({ tag: "B", side: "BUY" }),
    }),
  );
});

it("hides quant overlays without removing chart indicators", () => {
  render(
    <ProfessionalMarketChart
      instrumentId="159516.SZSE"
      period="1d"
      mainIndicator="BOLL"
      secondaryIndicator="VOL"
      showQuantSignals={false}
      bars={bars}
      signals={[{
        id: "signal-buy",
        timestamp: Date.parse("2026-08-06T09:30:00+08:00"),
        side: "BUY",
        price: 0.705,
        label: "量价动量买入观察",
        source: "QUANT",
      }]}
    />,
  );

  expect(chart.removeOverlay).toHaveBeenCalledWith({
    groupId: "astraquant-quant-signals",
  });
  expect(chart.createOverlay).not.toHaveBeenCalled();
  expect(chart.createIndicator).toHaveBeenCalledWith(
    expect.objectContaining({
      name: "BOLL",
      paneId: "candle_pane",
      calcParams: [20, 2],
    }),
    false,
  );
});

it("prevents wheel zoom from shrinking an intraday session below the canvas", () => {
  render(
    <ProfessionalMarketChart
      instrumentId="159516.SZSE"
      period="intraday"
      mainIndicator="AVG"
      secondaryIndicator="VOL"
      showQuantSignals
      bars={bars}
    />,
  );

  expect(init).toHaveBeenCalledWith(
    expect.any(HTMLDivElement),
    expect.objectContaining({
      layout: {
        barSpaceLimit: expect.objectContaining({ min: 2.5 }),
      },
    }),
  );
  const callback = chart.subscribeAction.mock.calls.find(
    ([action]) => action === "onZoom",
  )?.[1];
  expect(callback).toBeTypeOf("function");

  act(() => callback({ scale: 0.8 }));

  expect(chart.setBarSpace).toHaveBeenLastCalledWith(4);
  expect(chart.scrollToRealTime).toHaveBeenCalledWith(0);
});

it("anchors partial provider history by trading time instead of bar count", () => {
  const closingBars: MarketBar[] = [{
    ...bars[0]!,
    timestamp: "2026-08-06T15:00:00+08:00",
  }];

  render(
    <ProfessionalMarketChart
      instrumentId="159516.SZSE"
      period="intraday"
      mainIndicator="AVG"
      secondaryIndicator="VOL"
      showQuantSignals
      bars={closingBars}
    />,
  );

  expect(chart.setOffsetRightDistance).toHaveBeenLastCalledWith(0);
});

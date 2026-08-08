import { useEffect, useMemo, useRef, useState } from "react";
import {
  dispose,
  init,
  registerIndicator,
  registerOverlay,
  type Chart,
  type Crosshair,
  type IndicatorCreate,
  type OverlayTemplate,
  type Period,
  type Point,
} from "klinecharts";

import type { MarketBar, MarketPeriod } from "../api/market-contracts";
import type {
  MainChartIndicator,
  SecondaryChartIndicator,
} from "./MarketChartToolbar";
import {
  buildCrosshairQuote,
  type CrosshairQuote,
} from "../features/market/crosshairQuote";
import { normalizeMarketBars } from "../features/market/marketChartData";
import { marketChartTheme } from "../features/market/marketChartTheme";
import { intradayAverageIndicator } from "../features/market/intradayAverage";
import {
  toSignalOverlays,
  type MarketSignalMarker,
  type MarketSignalOverlay,
} from "../features/market/marketSignalOverlay";

const QUANT_SIGNAL_GROUP_ID = "astraquant-quant-signals";
const CANDLE_PANE_ID = "candle_pane";
const SECONDARY_PANE_ID = "astraquant_secondary_pane";
const MINIMUM_KLINE_BAR_SPACE = 2.5;

const quantSignalOverlay: OverlayTemplate<MarketSignalOverlay> = {
  name: "astraquantSignal",
  totalStep: 2,
  lock: true,
  needDefaultPointFigure: false,
  needDefaultXAxisFigure: false,
  needDefaultYAxisFigure: false,
  createPointFigures: ({ overlay, coordinates }) => {
    const point = coordinates[0];
    if (point === undefined) return [];
    const signal = overlay.extendData;
    const color = signal.side === "BUY" ? "#ef5b5b" : "#21ad76";
    const y = point.y + (signal.side === "BUY" ? 22 : -22);
    return [
      {
        type: "circle",
        attrs: { x: point.x, y, r: 11 },
        styles: { style: "fill", color },
        ignoreEvent: true,
      },
      {
        type: "text",
        attrs: {
          x: point.x,
          y,
          text: signal.tag,
          align: "center",
          baseline: "middle",
        },
        styles: {
          color: "#ffffff",
          size: 11,
          weight: "bold",
        },
        ignoreEvent: true,
      },
    ];
  },
};

interface ProfessionalMarketChartProps {
  instrumentId: string;
  period: MarketPeriod;
  mainIndicator: MainChartIndicator;
  secondaryIndicator: SecondaryChartIndicator;
  showQuantSignals: boolean;
  bars: MarketBar[];
  signals?: MarketSignalMarker[];
  onCrosshairBarChange?: (bar: MarketBar | null) => void;
}

export function ProfessionalMarketChart({
  instrumentId,
  period,
  mainIndicator,
  secondaryIndicator,
  showQuantSignals,
  bars,
  signals = [],
  onCrosshairBarChange,
}: ProfessionalMarketChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const orderedBars = useMemo(() => orderMarketBars(bars), [bars]);
  const barsRef = useRef(orderedBars);
  const precisionRef = useRef(inferPricePrecision(bars));
  const onCrosshairBarChangeRef = useRef(onCrosshairBarChange);
  const [crosshairQuote, setCrosshairQuote] = useState<
    (CrosshairQuote & { top: number }) | null
  >(null);
  const layoutRef = useRef<{
    period: MarketPeriod;
    lastTimestamp: number | null;
  }>({
    period,
    lastTimestamp: timestampOfLastBar(orderedBars),
  });
  barsRef.current = orderedBars;
  precisionRef.current = inferPricePrecision(bars);
  onCrosshairBarChangeRef.current = onCrosshairBarChange;

  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    const chart = init(host, {
      locale: "zh-CN",
      timezone: "Asia/Shanghai",
      styles: marketChartTheme,
      layout: {
        barSpaceLimit: {
          min: MINIMUM_KLINE_BAR_SPACE,
          max: 50,
        },
      },
    });
    if (chart === null) return;
    registerIndicator(intradayAverageIndicator);
    registerOverlay(quantSignalOverlay);
    chartRef.current = chart;
    chart.setTimezone("Asia/Shanghai");
    const handleCrosshairChange = (value?: unknown) => {
      const crosshair = value as Crosshair | undefined;
      if (
        crosshair?.paneId !== "candle_pane"
        || crosshair.y === undefined
      ) {
        setCrosshairQuote(null);
        onCrosshairBarChangeRef.current?.(null);
        return;
      }
      const coordinate = crosshair.x === undefined
        ? { y: crosshair.y }
        : { x: crosshair.x, y: crosshair.y };
      const converted = chart.convertFromPixel(
        [coordinate],
        { paneId: crosshair.paneId },
      ) as Partial<Point>[];
      const point = converted[0];
      const sourceBar = (
        point?.dataIndex !== undefined
        && Number.isInteger(point.dataIndex)
        && point.dataIndex >= 0
      )
        ? (
            barsRef.current[point.dataIndex]
            ?? barsRef.current.find(
              (bar) => Date.parse(bar.timestamp) === point.timestamp,
            )
          )
        : barsRef.current.find(
            (bar) => Date.parse(bar.timestamp) === point?.timestamp,
          );
      if (sourceBar !== undefined) {
        onCrosshairBarChangeRef.current?.(sourceBar);
      }
      const price = point?.value;
      if (price === undefined || !Number.isFinite(price)) {
        setCrosshairQuote(null);
        return;
      }
      const quote = buildCrosshairQuote(
        price,
        sourceBar?.previous_close ?? null,
        precisionRef.current,
      );
      const maxTop = Math.max(host.clientHeight - 22, 22);
      setCrosshairQuote({
        ...quote,
        top: Math.min(Math.max(crosshair.y, 22), maxTop),
      });
    };
    chart.subscribeAction("onCrosshairChange", handleCrosshairChange);
    const handleZoom = () => {
      const minimum = minimumBarSpace(host, layoutRef.current.period);
      if (chart.getBarSpace().bar < minimum) {
        chart.setBarSpace(minimum);
        chart.scrollToRealTime(0);
      }
    };
    chart.subscribeAction("onZoom", handleZoom);

    const resizeObserver = new ResizeObserver(() => {
      chart.resize();
      applyChartLayout(
        chart,
        host,
        layoutRef.current.period,
        layoutRef.current.lastTimestamp,
      );
    });
    resizeObserver.observe(host);
    return () => {
      resizeObserver.disconnect();
      chart.unsubscribeAction("onCrosshairChange", handleCrosshairChange);
      chart.unsubscribeAction("onZoom", handleZoom);
      onCrosshairBarChangeRef.current?.(null);
      chartRef.current = null;
      dispose(chart);
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setSymbol({
      ticker: instrumentId,
      pricePrecision: inferPricePrecision(bars),
      volumePrecision: 0,
    });
  }, [bars, instrumentId]);

  useEffect(() => {
    const chart = chartRef.current;
    if (chart === null) return;
    const chartData = normalizeMarketBars(bars);
    const lastTimestamp = chartData.at(-1)?.timestamp ?? null;
    layoutRef.current = { period, lastTimestamp };
    chart.setStyles({
      candle: {
        type: period === "intraday" ? "area" : "candle_solid",
        area: {
          value: period === "intraday" ? "close" : "close",
        },
      },
    });
    chart.setPeriod(toChartPeriod(period));
    chart.setDataLoader({
      getBars: ({ callback }) => {
        callback(chartData, { backward: false, forward: false });
      },
    });
    const host = hostRef.current;
    chart.resetData();
    // resetData() delivers the bars synchronously, so overlays created right
    // after it are guaranteed to resolve their timestamps against the data.
    chart.removeOverlay({ groupId: QUANT_SIGNAL_GROUP_ID });
    if (showQuantSignals) {
      for (const signal of toSignalOverlays(signals)) {
        chart.createOverlay({
          name: quantSignalOverlay.name,
          groupId: QUANT_SIGNAL_GROUP_ID,
          paneId: CANDLE_PANE_ID,
          lock: true,
          points: [{ timestamp: signal.timestamp, value: signal.price }],
          extendData: signal,
        });
      }
    }
    if (host !== null) applyChartLayout(chart, host, period, lastTimestamp);
  }, [bars, period, showQuantSignals, signals]);

  useEffect(() => {
    const chart = chartRef.current;
    if (chart === null) return;
    chart.removeIndicator({ paneId: CANDLE_PANE_ID });
    chart.removeIndicator({ paneId: SECONDARY_PANE_ID });
    if (mainIndicator !== "NONE") {
      chart.createIndicator(mainIndicatorCreate(mainIndicator), false);
    }
    chart.createIndicator({
      name: secondaryIndicator,
      paneId: SECONDARY_PANE_ID,
    }, false);
  }, [mainIndicator, secondaryIndicator]);

  useEffect(() => {
    const chart = chartRef.current;
    if (chart === null) return;
    const apply = () => {
      chart.removeOverlay({ groupId: QUANT_SIGNAL_GROUP_ID });
      if (!showQuantSignals) return;
      for (const signal of toSignalOverlays(signals)) {
        chart.createOverlay({
          name: quantSignalOverlay.name,
          groupId: QUANT_SIGNAL_GROUP_ID,
          paneId: CANDLE_PANE_ID,
          lock: true,
          points: [{ timestamp: signal.timestamp, value: signal.price }],
          extendData: signal,
        });
      }
    };
    apply();
    // klinecharts resolves overlay points against the loaded data; when
    // signals arrive before the data (e.g. replay results), re-apply once
    // the visible range has been computed.
    chart.subscribeAction("onVisibleRangeChange", apply);
    return () => {
      chart.unsubscribeAction("onVisibleRangeChange", apply);
    };
  }, [showQuantSignals, signals]);

  return (
    <div
      className="professional-market-chart"
      role="img"
      aria-label={`${instrumentId}${period === "intraday" ? "分时" : "K线"}行情图`}
    >
      <div ref={hostRef} className="professional-market-chart__surface" />
      {crosshairQuote === null ? null : (
        <>
          <div
            className={`market-crosshair-quote market-crosshair-quote--${crosshairQuote.direction}`}
            role="status"
            aria-label="光标价格涨幅"
          >
            <strong>{crosshairQuote.priceText}</strong>
            {crosshairQuote.changeText === null ? null : (
              <span>{crosshairQuote.changeText}</span>
            )}
          </div>
          <div
            className={`market-crosshair-axis-label market-crosshair-axis-label--${crosshairQuote.direction}`}
            style={{ top: crosshairQuote.top }}
            aria-hidden="true"
          >
            <strong>{crosshairQuote.priceText}</strong>
            {crosshairQuote.changeText === null ? null : (
              <span>{crosshairQuote.changeText}</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function mainIndicatorCreate(
  indicator: Exclude<MainChartIndicator, "NONE">,
): IndicatorCreate {
  const create: IndicatorCreate = {
    name: indicator,
    paneId: CANDLE_PANE_ID,
  };
  if (indicator === "MA") create.calcParams = [5, 10, 20, 60];
  if (indicator === "BOLL") create.calcParams = [20, 2];
  return create;
}

function toChartPeriod(period: MarketPeriod): Period {
  const periods: Record<MarketPeriod, Period> = {
    intraday: { type: "minute", span: 1 },
    "1m": { type: "minute", span: 1 },
    "5m": { type: "minute", span: 5 },
    "15m": { type: "minute", span: 15 },
    "30m": { type: "minute", span: 30 },
    "60m": { type: "hour", span: 1 },
    "1d": { type: "day", span: 1 },
    "1w": { type: "week", span: 1 },
    "1mo": { type: "month", span: 1 },
    "1y": { type: "year", span: 1 },
  };
  return periods[period];
}

function inferPricePrecision(bars: MarketBar[]): number {
  const last = bars.at(-1)?.close;
  if (last === undefined) return 2;
  if (last < 1) return 4;
  if (last < 100) return 3;
  return 2;
}

function applyChartLayout(
  chart: Chart,
  host: HTMLDivElement,
  period: MarketPeriod,
  lastTimestamp: number | null,
) {
  if (period !== "intraday") {
    chart.setRightMinVisibleBarCount(5);
    chart.setOffsetRightDistance(56);
    return;
  }
  const remainingBars = remainingIntradayBars(lastTimestamp);
  const barSpace = minimumBarSpace(host, period);
  chart.setBarSpace(barSpace);
  chart.setRightMinVisibleBarCount(0);
  chart.setOffsetRightDistance(remainingBars * barSpace);
}

function minimumBarSpace(
  host: HTMLDivElement,
  period: MarketPeriod,
): number {
  if (period !== "intraday") return MINIMUM_KLINE_BAR_SPACE;
  const plotWidth = Math.max(host.clientWidth - 64, 960);
  return plotWidth / 240;
}

function orderMarketBars(bars: MarketBar[]): MarketBar[] {
  const unique = new Map<number, MarketBar>();
  for (const bar of bars) {
    const timestamp = Date.parse(bar.timestamp);
    if (Number.isFinite(timestamp)) unique.set(timestamp, bar);
  }
  return [...unique.entries()]
    .sort(([left], [right]) => left - right)
    .map(([, bar]) => bar);
}

function timestampOfLastBar(bars: MarketBar[]): number | null {
  const timestamp = bars.at(-1)?.timestamp;
  if (timestamp === undefined) return null;
  const parsed = Date.parse(timestamp);
  return Number.isFinite(parsed) ? parsed : null;
}

function remainingIntradayBars(timestamp: number | null): number {
  if (timestamp === null) return 0;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(timestamp));
  const hour = Number(parts.find((part) => part.type === "hour")?.value);
  const minute = Number(parts.find((part) => part.type === "minute")?.value);
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return 0;
  const tradingMinute = (hour * 60) + minute;
  if (tradingMinute <= 570) return 240;
  if (tradingMinute <= 690) return 240 - (tradingMinute - 570);
  if (tradingMinute < 780) return 120;
  if (tradingMinute <= 900) return 120 - (tradingMinute - 780);
  return 0;
}

import { useEffect, useRef, useState } from "react";
import {
  dispose,
  init,
  registerOverlay,
  type Chart,
  type Crosshair,
  type OverlayTemplate,
  type Period,
  type Point,
} from "klinecharts";

import type { MarketBar, MarketPeriod } from "../api/market-contracts";
import type { MarketIndicator } from "./MarketChartToolbar";
import {
  buildCrosshairQuote,
  type CrosshairQuote,
} from "../features/market/crosshairQuote";
import { normalizeMarketBars } from "../features/market/marketChartData";
import { marketChartTheme } from "../features/market/marketChartTheme";
import {
  toSignalOverlays,
  type MarketSignalMarker,
  type MarketSignalOverlay,
} from "../features/market/marketSignalOverlay";

const QUANT_SIGNAL_GROUP_ID = "astraquant-quant-signals";

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
  indicator: MarketIndicator;
  bars: MarketBar[];
  signals?: MarketSignalMarker[];
  onCrosshairBarChange?: (bar: MarketBar | null) => void;
}

export function ProfessionalMarketChart({
  instrumentId,
  period,
  indicator,
  bars,
  signals = [],
  onCrosshairBarChange,
}: ProfessionalMarketChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const barsRef = useRef(bars);
  const precisionRef = useRef(inferPricePrecision(bars));
  const onCrosshairBarChangeRef = useRef(onCrosshairBarChange);
  const [crosshairQuote, setCrosshairQuote] = useState<
    (CrosshairQuote & { top: number }) | null
  >(null);
  const layoutRef = useRef<{ period: MarketPeriod; barCount: number }>({
    period,
    barCount: bars.length,
  });
  barsRef.current = bars;
  precisionRef.current = inferPricePrecision(bars);
  onCrosshairBarChangeRef.current = onCrosshairBarChange;

  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    const chart = init(host, {
      locale: "zh-CN",
      timezone: "Asia/Shanghai",
      styles: marketChartTheme,
    });
    if (chart === null) return;
    registerOverlay(quantSignalOverlay);
    chartRef.current = chart;
    chart.setTimezone("Asia/Shanghai");
    const handleCrosshairChange = (value?: unknown) => {
      const crosshair = value as Crosshair | undefined;
      if (
        crosshair?.paneId !== "candle_pane"
        || crosshair.y === undefined
        || crosshair.kLineData?.timestamp === undefined
      ) {
        setCrosshairQuote(null);
        onCrosshairBarChangeRef.current?.(null);
        return;
      }
      const sourceBar = barsRef.current.find(
        (bar) => Date.parse(bar.timestamp) === crosshair.kLineData?.timestamp,
      );
      onCrosshairBarChangeRef.current?.(sourceBar ?? null);
      const converted = chart.convertFromPixel(
        [{ y: crosshair.y }],
        { paneId: crosshair.paneId },
      ) as Partial<Point>[];
      const price = converted[0]?.value;
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

    const resizeObserver = new ResizeObserver(() => {
      chart.resize();
      applyChartLayout(chart, host, layoutRef.current.period, layoutRef.current.barCount);
    });
    resizeObserver.observe(host);
    return () => {
      resizeObserver.disconnect();
      chart.unsubscribeAction("onCrosshairChange", handleCrosshairChange);
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
    layoutRef.current = { period, barCount: chartData.length };
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
    if (host !== null) applyChartLayout(chart, host, period, chartData.length);
  }, [bars, period]);

  useEffect(() => {
    const chart = chartRef.current;
    if (chart === null) return;
    chart.removeIndicator();
    if (period !== "intraday") {
      chart.createIndicator(indicator, indicator === "MA" || indicator === "BOLL");
    }
    chart.createIndicator("VOL", false);
  }, [indicator, period]);

  useEffect(() => {
    const chart = chartRef.current;
    if (chart === null) return;
    chart.removeOverlay({ groupId: QUANT_SIGNAL_GROUP_ID });
    for (const signal of toSignalOverlays(signals)) {
      chart.createOverlay({
        name: quantSignalOverlay.name,
        groupId: QUANT_SIGNAL_GROUP_ID,
        paneId: "candle_pane",
        lock: true,
        points: [{ timestamp: signal.timestamp, value: signal.price }],
        extendData: signal,
      });
    }
  }, [signals]);

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
  barCount: number,
) {
  if (period !== "intraday") {
    chart.setRightMinVisibleBarCount(5);
    chart.setOffsetRightDistance(56);
    return;
  }
  const sessionBars = 240;
  const remainingBars = Math.max(sessionBars - barCount, 0);
  const plotWidth = Math.max(host.clientWidth - 64, 960);
  const barSpace = plotWidth / sessionBars;
  chart.setBarSpace(barSpace);
  chart.setRightMinVisibleBarCount(0);
  chart.setOffsetRightDistance(remainingBars * barSpace);
}

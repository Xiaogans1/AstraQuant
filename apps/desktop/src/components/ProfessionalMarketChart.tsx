import { useEffect, useMemo, useRef, useState } from "react";
import {
  dispose,
  init,
  registerIndicator,
  type Chart,
  type Coordinate,
  type Crosshair,
  type IndicatorCreate,
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
import type { MarketSignalMarker } from "../features/market/marketSignalOverlay";

const QUANT_SIGNAL_GROUP_ID = "astraquant-quant-signals";
const CANDLE_PANE_ID = "candle_pane";
const SECONDARY_PANE_ID = "astraquant_secondary_pane";
const MINIMUM_KLINE_BAR_SPACE = 2.5;
const OVERVIEW_KLINE_BAR_SPACE = 0.1;

interface SignalConnection {
  fromId: string;
  toId: string;
  pnl: number;
}

interface ProfessionalMarketChartProps {
  instrumentId: string;
  period: MarketPeriod;
  mainIndicator: MainChartIndicator;
  secondaryIndicator: SecondaryChartIndicator;
  showQuantSignals: boolean;
  bars: MarketBar[];
  signals?: MarketSignalMarker[];
  onCrosshairBarChange?: (bar: MarketBar | null) => void;
  activeSignalId?: string | null;
  onSignalSelect?: (signalId: string | null) => void;
  connections?: SignalConnection[];
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
  activeSignalId = null,
  onSignalSelect,
  connections = [],
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
          min: OVERVIEW_KLINE_BAR_SPACE,
          max: 50,
        },
      },
    });
    if (chart === null) return;
    registerIndicator(intradayAverageIndicator);
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
        requestAnimationFrame(() => refreshSignalMarkers());
      },
    });
    const host = hostRef.current;
    chart.resetData();
    if (host !== null) applyChartLayout(chart, host, period, lastTimestamp);
    refreshSignalMarkers();
  }, [bars, period]);

  const [signalMarkers, setSignalMarkers] = useState<
    Array<{ signal: MarketSignalMarker; x: number; y: number }>
  >([]);
  const signalMarkersRef = useRef(signalMarkers);
  signalMarkersRef.current = signalMarkers;
  const retryRef = useRef(0);
  const lastActiveSignalIdRef = useRef<string | null>(null);

  const activeSignalIndex = activeSignalId === null
    ? -1
    : signals.findIndex((signal) => signal.id === activeSignalId);

  const selectSignal = (index: number) => {
    if (index < 0 || index >= signals.length) {
      onSignalSelect?.(null);
      return;
    }
    onSignalSelect?.(signals[index].id);
  };

  const jumpToSignal = (index: number) => {
    const chart = chartRef.current;
    if (chart === null || index < 0 || index >= signals.length) return;
    selectSignal(index);
    chart.scrollToTimestamp(signals[index].timestamp, 200);
    requestAnimationFrame(() => refreshSignalMarkers());
    requestAnimationFrame(() => requestAnimationFrame(() => refreshSignalMarkers()));
  };

  useEffect(() => {
    if (activeSignalId === null || activeSignalId === lastActiveSignalIdRef.current) return;
    lastActiveSignalIdRef.current = activeSignalId;
    const chart = chartRef.current;
    if (chart === null) return;
    const signal = signals.find((item) => item.id === activeSignalId);
    if (signal !== undefined) {
      chart.scrollToTimestamp(signal.timestamp, 200);
    }
  }, [activeSignalId, signals]);

  const zoomToOverview = () => {
    const chart = chartRef.current;
    const host = hostRef.current;
    if (chart === null || host === null || bars.length === 0) return;
    const plotWidth = Math.max(host.clientWidth - 64, 960);
    chart.setBarSpace(Math.max(plotWidth / bars.length, OVERVIEW_KLINE_BAR_SPACE));
    chart.scrollToRealTime(0);
    requestAnimationFrame(() => refreshSignalMarkers());
    requestAnimationFrame(() => requestAnimationFrame(() => refreshSignalMarkers()));
  };

  const zoomToRecent = () => {
    const chart = chartRef.current;
    const host = hostRef.current;
    if (chart === null || host === null) return;
    chart.setBarSpace(minimumBarSpace(host, period));
    chart.scrollToRealTime(0);
    requestAnimationFrame(() => refreshSignalMarkers());
    requestAnimationFrame(() => requestAnimationFrame(() => refreshSignalMarkers()));
  };

  const refreshSignalMarkers = () => {
    const chart = chartRef.current;
    if (chart === null) {
      setSignalMarkers([]);
      return;
    }
    if (!showQuantSignals) {
      setSignalMarkers([]);
      return;
    }
    const mapped = signals
      .map((signal) => {
        const pixels = chart.convertToPixel(
          [{ timestamp: signal.timestamp, value: signal.price }],
          { paneId: CANDLE_PANE_ID },
        ) as Array<Partial<Coordinate>>;
        const pixel = pixels[0];
        if (pixel === undefined || !Number.isFinite(pixel.x) || !Number.isFinite(pixel.y)) {
          return null;
        }
        return { signal, x: pixel.x, y: pixel.y };
      })
      .filter((item): item is { signal: MarketSignalMarker; x: number; y: number } => item !== null);
    if (mapped.length < signals.length && retryRef.current < 120) {
      // resetData() delivers bars asynchronously; keep retrying on animation
      // frames until convertToPixel can resolve the timestamps.
      retryRef.current += 1;
      requestAnimationFrame(refreshSignalMarkers);
      return;
    }
    retryRef.current = 0;
    const previous = signalMarkersRef.current;
    if (
      previous.length === mapped.length
      && mapped.every(
        (item, index) =>
          previous[index]?.signal.id === item.signal.id
          && previous[index]?.x === item.x
          && previous[index]?.y === item.y,
      )
    ) {
      return;
    }
    setSignalMarkers(mapped);
  };

  useEffect(() => {
    const chart = chartRef.current;
    if (chart === null) return;
    const apply = () => refreshSignalMarkers();
    apply();
    chart.subscribeAction("onScroll", apply);
    chart.subscribeAction("onZoom", apply);
    chart.subscribeAction("onVisibleRangeChange", apply);
    return () => {
      chart.unsubscribeAction("onScroll", apply);
      chart.unsubscribeAction("onZoom", apply);
      chart.unsubscribeAction("onVisibleRangeChange", apply);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showQuantSignals, signals]);

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

  return (
    <div
      className="professional-market-chart"
      role="img"
      aria-label={`${instrumentId}${period === "intraday" ? "分时" : "K线"}行情图`}
    >
      <div ref={hostRef} className="professional-market-chart__surface" />
      {signalMarkers.length === 0 ? null : (
        <svg
          className="professional-market-chart__signals"
          aria-hidden="true"
        >
          {connections.map((connection) => {
            const from = signalMarkers.find((marker) => marker.signal.id === connection.fromId);
            const to = signalMarkers.find((marker) => marker.signal.id === connection.toId);
            if (from === undefined || to === undefined) return null;
            return (
              <line
                key={`${connection.fromId}-${connection.toId}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke={connection.pnl >= 0 ? "#21ad76" : "#ef5b5b"}
                strokeWidth={1.5}
                strokeDasharray="6 4"
                opacity={0.7}
              >
                <title>{`配对盈亏 ${connection.pnl >= 0 ? "+" : ""}${formatMoneyLocal(connection.pnl)}（${connection.pnl >= 0 ? "盈" : "亏"}）`}</title>
              </line>
            );
          })}
          {signalMarkers.map(({ signal, x, y }, index) => {
            const isBuy = signal.side === "BUY";
            const color = isBuy ? "#ef5b5b" : "#21ad76";
            const isActive = index === activeSignalIndex;
            return (
              <g
                key={signal.id}
                className="professional-market-chart__signal"
                onClick={() => selectSignal(index)}
              >
                <circle
                  cx={x}
                  cy={y}
                  r={isActive ? 12 : 9}
                  fill={color}
                  stroke={isActive ? "#ffffff" : "none"}
                  strokeWidth={2}
                >
                  <title>{signal.label}</title>
                </circle>
                <text
                  x={x}
                  y={y + 3.5}
                  textAnchor="middle"
                  fontSize="10"
                  fontWeight="bold"
                  fill="#ffffff"
                >
                  {isBuy ? "B" : "S"}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      {signalMarkers.length === 0 ? null : (
        <div className="professional-market-chart__signalbar" role="toolbar" aria-label="买卖点导航">
          <button
            type="button"
            disabled={signals.length === 0}
            onClick={() => jumpToSignal(activeSignalIndex - 1)}
          >
            ← 上一个
          </button>
          <span className="professional-market-chart__signalbar-index">
            {activeSignalIndex >= 0 ? activeSignalIndex + 1 : "—"} / {signals.length}
          </span>
          <button
            type="button"
            disabled={signals.length === 0}
            onClick={() => jumpToSignal(activeSignalIndex + 1)}
          >
            下一个 →
          </button>
          <strong className="professional-market-chart__signalbar-detail">
            {activeSignalIndex >= 0 ? signals[activeSignalIndex].label : "点击图上 B/S 标记查看详情"}
          </strong>
          <button type="button" onClick={zoomToOverview}>显示整体</button>
          <button type="button" onClick={zoomToRecent}>回到最近</button>
        </div>
      )}
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

function formatMoneyLocal(value: number): string {
  return value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

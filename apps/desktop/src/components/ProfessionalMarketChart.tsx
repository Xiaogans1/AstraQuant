import { useEffect, useRef } from "react";
import { dispose, init, type Chart, type Period } from "klinecharts";

import type { MarketBar, MarketPeriod } from "../api/market-contracts";
import type { MarketIndicator } from "./MarketChartToolbar";
import { normalizeMarketBars } from "../features/market/marketChartData";
import { marketChartTheme } from "../features/market/marketChartTheme";

interface ProfessionalMarketChartProps {
  instrumentId: string;
  period: MarketPeriod;
  indicator: MarketIndicator;
  bars: MarketBar[];
}

export function ProfessionalMarketChart({
  instrumentId,
  period,
  indicator,
  bars,
}: ProfessionalMarketChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    const chart = init(host, {
      locale: "zh-CN",
      timezone: "Asia/Shanghai",
      styles: marketChartTheme,
    });
    if (chart === null) return;
    chartRef.current = chart;
    chart.setTimezone("Asia/Shanghai");

    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(host);
    return () => {
      resizeObserver.disconnect();
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
    if (period === "intraday") {
      chart.setBarSpace(4.5);
      chart.setRightMinVisibleBarCount(Math.max(240 - chartData.length, 0));
    } else {
      chart.setRightMinVisibleBarCount(5);
    }
    chart.resetData();
  }, [bars, period]);

  useEffect(() => {
    const chart = chartRef.current;
    if (chart === null) return;
    chart.removeIndicator();
    chart.createIndicator("VOL", false);
    chart.createIndicator(indicator, indicator === "MA" || indicator === "BOLL");
  }, [indicator]);

  return (
    <div
      ref={hostRef}
      className="professional-market-chart"
      role="img"
      aria-label={`${instrumentId}${period === "intraday" ? "分时" : "K线"}行情图`}
    />
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

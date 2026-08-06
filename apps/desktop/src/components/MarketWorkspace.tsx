import { useEffect, useState } from "react";

import type { ApiClient } from "../api/client";
import type {
  ConnectionState,
  MarketPeriod,
  QuoteCard,
} from "../api/market-contracts";
import { useMarketBarsQuery } from "../api/queries";
import {
  MarketChartToolbar,
  type MarketIndicator,
} from "./MarketChartToolbar";
import { ProfessionalMarketChart } from "./ProfessionalMarketChart";

interface MarketWorkspaceProps {
  client: ApiClient;
  quote: QuoteCard;
  state: ConnectionState;
}

export function MarketWorkspace({ client, quote, state }: MarketWorkspaceProps) {
  const [period, setPeriod] = useState<MarketPeriod>("intraday");
  const [indicator, setIndicator] = useState<MarketIndicator>("MA");
  const [fullscreen, setFullscreen] = useState(false);
  const barsQuery = useMarketBarsQuery(client, quote.instrument_id, period, state);

  useEffect(() => {
    const exitFullscreen = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreen(false);
    };
    document.addEventListener("keydown", exitFullscreen);
    return () => document.removeEventListener("keydown", exitFullscreen);
  }, []);

  return (
    <section
      className="terminal-panel market-workspace"
      data-fullscreen={fullscreen}
      data-testid="market-workspace"
      aria-label={`${quote.name}专业行情图`}
    >
      <header className="market-workspace__quote">
        <div className="market-workspace__identity">
          <p className="terminal-kicker">MARKET CHART / EASTMONEY</p>
          <h2>{quote.name}<span>{quote.instrument_id}</span></h2>
        </div>
        <div className="market-workspace__price">
          <strong>{formatPrice(quote.last_price)}</strong>
          <div>
            <MarketChange value={quote.change_percent} />
            <span>{formatSigned(quote.change)}</span>
          </div>
        </div>
        <dl className="market-workspace__stats">
          <QuoteStat label="今开" value={formatPrice(quote.open)} />
          <QuoteStat label="最高" value={formatPrice(quote.high)} />
          <QuoteStat label="最低" value={formatPrice(quote.low)} />
          <QuoteStat label="昨收" value={formatPrice(quote.previous_close)} />
          <QuoteStat label="成交量" value={formatCompact(quote.volume)} />
          <QuoteStat label="成交额" value={formatCompact(quote.turnover)} />
        </dl>
      </header>

      <MarketChartToolbar
        period={period}
        indicator={indicator}
        fullscreen={fullscreen}
        onPeriodChange={setPeriod}
        onIndicatorChange={setIndicator}
        onToggleFullscreen={() => setFullscreen((value) => !value)}
      />

      <div className="market-workspace__canvas">
        {barsQuery.isLoading ? (
          <div className="market-chart-state"><strong>正在读取真实行情</strong><p>从东财加载{periodLabel(period)}数据…</p></div>
        ) : barsQuery.isError ? (
          <div className="market-chart-state" role="alert"><strong>行情图加载失败</strong><p>请确认东财终端已登录并保持运行。</p></div>
        ) : barsQuery.data && barsQuery.data.length > 0 ? (
          <ProfessionalMarketChart
            instrumentId={quote.instrument_id}
            period={period}
            indicator={indicator}
            bars={barsQuery.data}
          />
        ) : (
          <div className="market-chart-state"><strong>暂无真实{periodLabel(period)}数据</strong><p>软件不会用演示行情填充空白。</p></div>
        )}
      </div>

      {period === "intraday" ? (
        <div className="market-session-axis" aria-label="A股交易时段">
          <span>09:30</span><span>11:30 / 13:00</span><span>15:00</span>
        </div>
      ) : null}
      <footer className="market-workspace__footer">
        <span>数据源：东财掘金只读行情</span>
        <span>{quote.event_time ? `快照：${formatTime(quote.event_time)}` : "尚无真实快照"}</span>
        <span>量化买卖点图层：等待策略引擎真实输出</span>
      </footer>
    </section>
  );
}

function QuoteStat({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function MarketChange({ value }: { value: string | null }) {
  if (value === null) return <span className="market-change">—</span>;
  const numeric = Number(value);
  return (
    <span className={`market-change ${numeric >= 0 ? "market-up" : "market-down"}`}>
      {numeric >= 0 ? "+" : ""}{numeric.toFixed(2)}%
    </span>
  );
}

function formatPrice(value: string | null): string {
  if (value === null) return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric)
    ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(numeric)
    : value;
}

function formatSigned(value: string | null): string {
  if (value === null) return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return `${numeric >= 0 ? "+" : ""}${numeric.toFixed(4)}`;
}

function formatCompact(value: string | null): string {
  if (value === null) return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  if (numeric >= 100_000_000) return `${(numeric / 100_000_000).toFixed(2)}亿`;
  if (numeric >= 10_000) return `${(numeric / 10_000).toFixed(2)}万`;
  return new Intl.NumberFormat("zh-CN").format(numeric);
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function periodLabel(period: MarketPeriod): string {
  const labels: Record<MarketPeriod, string> = {
    intraday: "分时",
    "1m": "1分钟",
    "5m": "5分钟",
    "15m": "15分钟",
    "30m": "30分钟",
    "60m": "60分钟",
    "1d": "日K",
    "1w": "周K",
    "1mo": "月K",
    "1y": "年K",
  };
  return labels[period];
}

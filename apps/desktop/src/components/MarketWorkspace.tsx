import { useEffect, useMemo, useState } from "react";

import type { ApiClient } from "../api/client";
import type {
  ConnectionState,
  MarketBar,
  MarketPeriod,
  QuoteCard,
  RealtimeQuantDecision,
} from "../api/market-contracts";
import { useMarketBarsQuery, useMarketSignalQuery } from "../api/queries";
import { mergeLiveQuoteIntoIntradayBars } from "../features/market/liveIntraday";
import type { MarketSignalMarker } from "../features/market/marketSignalOverlay";
import {
  MarketChartToolbar,
  type MainChartIndicator,
  type SecondaryChartIndicator,
} from "./MarketChartToolbar";
import { ProfessionalMarketChart } from "./ProfessionalMarketChart";

interface MarketWorkspaceProps {
  client: ApiClient;
  quote: QuoteCard;
  state: ConnectionState;
}

export function MarketWorkspace({ client, quote, state }: MarketWorkspaceProps) {
  const [period, setPeriod] = useState<MarketPeriod>("intraday");
  const [intradayMainIndicator, setIntradayMainIndicator] =
    useState<MainChartIndicator>("AVG");
  const [candleMainIndicator, setCandleMainIndicator] =
    useState<MainChartIndicator>("MA");
  const [secondaryIndicator, setSecondaryIndicator] =
    useState<SecondaryChartIndicator>("VOL");
  const [showQuantSignals, setShowQuantSignals] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const [crosshairBar, setCrosshairBar] = useState<MarketBar | null>(null);
  const barsQuery = useMarketBarsQuery(client, quote.instrument_id, period, state);
  const signalQuery = useMarketSignalQuery(
    client,
    quote.instrument_id,
    state,
  );
  const chartBars = useMemo(() => {
    const authoritativeBars = barsQuery.data ?? [];
    return period === "intraday"
      ? mergeLiveQuoteIntoIntradayBars(authoritativeBars, quote)
      : authoritativeBars;
  }, [barsQuery.data, period, quote]);
  const hasBars = chartBars.length > 0;
  const displayedPrice = crosshairBar?.close.toString() ?? quote.last_price;
  const displayedChange = crosshairChange(
    crosshairBar,
    quote.change,
    quote.previous_close,
  );
  const displayedChangePercent = crosshairChangePercent(
    crosshairBar,
    quote.change_percent,
    quote.previous_close,
  );
  const mainIndicator =
    period === "intraday" ? intradayMainIndicator : candleMainIndicator;
  const setMainIndicator =
    period === "intraday" ? setIntradayMainIndicator : setCandleMainIndicator;
  const signalMarkers = useMemo(
    () =>
      period === "intraday" || period === "1m"
        ? toSignalMarkers(signalQuery.data)
        : [],
    [period, signalQuery.data],
  );

  useEffect(() => {
    const exitFullscreen = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreen(false);
    };
    document.addEventListener("keydown", exitFullscreen);
    return () => document.removeEventListener("keydown", exitFullscreen);
  }, []);

  useEffect(() => {
    setCrosshairBar(null);
  }, [period, quote.instrument_id]);

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
          <strong>{formatPrice(displayedPrice)}</strong>
          <div>
            <MarketChange value={displayedChangePercent} />
            <span>{formatSigned(displayedChange)}</span>
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
        mainIndicator={mainIndicator}
        secondaryIndicator={secondaryIndicator}
        showQuantSignals={showQuantSignals}
        fullscreen={fullscreen}
        onPeriodChange={setPeriod}
        onMainIndicatorChange={setMainIndicator}
        onSecondaryIndicatorChange={setSecondaryIndicator}
        onToggleQuantSignals={() => setShowQuantSignals((value) => !value)}
        onToggleFullscreen={() => setFullscreen((value) => !value)}
      />

      <QuantSignalStatus
        decision={signalQuery.data}
        loading={signalQuery.isLoading}
        error={signalQuery.isError}
      />

      <div className="market-workspace__canvas">
        {hasBars ? (
          <ProfessionalMarketChart
            instrumentId={quote.instrument_id}
            period={period}
            mainIndicator={mainIndicator}
            secondaryIndicator={secondaryIndicator}
            showQuantSignals={showQuantSignals}
            bars={chartBars}
            signals={signalMarkers}
            onCrosshairBarChange={setCrosshairBar}
          />
        ) : barsQuery.isLoading ? (
          <div className="market-chart-state"><strong>正在读取真实行情</strong><p>从东财加载{periodLabel(period)}数据…</p></div>
        ) : barsQuery.isError ? (
          <div className="market-chart-state" role="alert"><strong>行情图加载失败</strong><p>请确认东财终端已登录并保持运行。</p></div>
        ) : (
          <div className="market-chart-state"><strong>暂无真实{periodLabel(period)}数据</strong><p>软件不会用演示行情填充空白。</p></div>
        )}
        {hasBars && barsQuery.isError ? (
          <div className="market-chart-warning" role="status">
            行情更新暂时失败，继续显示上次成功数据
          </div>
        ) : null}
      </div>

      {period === "intraday" ? (
        <div className="market-session-axis" aria-label="A股交易时段">
          <span>09:30</span><span>11:30 / 13:00</span><span>15:00</span>
        </div>
      ) : null}
      <footer className="market-workspace__footer">
        <span>数据源：东财掘金只读行情</span>
        <span>{quote.event_time ? `快照：${formatTime(quote.event_time)}` : "尚无真实快照"}</span>
        <span>{quantAuditText(signalQuery.data)}</span>
      </footer>
    </section>
  );
}

function QuantSignalStatus({
  decision,
  loading,
  error,
}: {
  decision: RealtimeQuantDecision | undefined;
  loading: boolean;
  error: boolean;
}) {
  if (error && decision === undefined) {
    return (
      <div className="market-quant-status" data-state="ERROR">
        <span>QUANT / REALTIME</span>
        <strong>量化服务暂不可用</strong>
        <small>行情图仍可正常使用</small>
      </div>
    );
  }
  if (decision === undefined) {
    return (
      <div className="market-quant-status" data-state="IDLE">
        <span>QUANT / REALTIME</span>
        <strong>{loading ? "实时量化核心计算中" : "实时量化核心等待行情"}</strong>
      </div>
    );
  }
  const { signal, features } = decision;
  const stateLabel =
    signal.state === "WARMING_UP"
      ? `预热中 · ${features.completed_bar_count}/20 根完成分钟`
      : signal.state === "SUPPRESSED"
        ? `信号已抑制 · ${reasonText(signal.reason_codes[0])}`
        : signal.action === "BUY"
          ? `买入观察 · ${formatConfidence(signal.confidence)}`
          : signal.action === "SELL"
            ? `卖出/回避观察 · ${formatConfidence(signal.confidence)}`
            : "继续观察 · 暂无明确买卖点";
  return (
    <div className="market-quant-status" data-state={signal.state} data-action={signal.action}>
      <span>QUANT / {signal.strategy_version}</span>
      <strong>{stateLabel}</strong>
      <small>{signal.reason_codes.map(reasonText).join(" · ")}</small>
    </div>
  );
}

function toSignalMarkers(
  decision: RealtimeQuantDecision | undefined,
): MarketSignalMarker[] {
  const signal = decision?.signal;
  if (
    signal === undefined
    || signal.state !== "ACTIVE"
    || (signal.action !== "BUY" && signal.action !== "SELL")
    || signal.reference_price === null
  ) {
    return [];
  }
  const timestamp = Date.parse(signal.event_time);
  const price = Number(signal.reference_price);
  if (!Number.isFinite(timestamp) || !Number.isFinite(price)) return [];
  return [{
    id: signal.signal_id,
    timestamp,
    side: signal.action,
    price,
    label: signal.reason_codes.map(reasonText).join(" · "),
    source: "QUANT",
  }];
}

function quantAuditText(decision: RealtimeQuantDecision | undefined): string {
  if (decision === undefined) return "量化决策：等待真实特征快照";
  return `决策留痕：${decision.decision_record.decision_id.slice(0, 12)} · ${decision.signal.strategy_version}`;
}

function formatConfidence(value: string): string {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${Math.round(numeric * 100)}%` : value;
}

function reasonText(code: string | undefined): string {
  if (code === undefined) return "等待原因";
  const labels: Record<string, string> = {
    FEATURES_READY: "实时特征已就绪",
    MOMENTUM_VOLUME_BREAKOUT: "动量、均线与成交量条件成立",
    DOWNTREND_EXIT: "短线趋势转弱",
    NO_CONFIRMED_EDGE: "未形成可确认优势",
    MARKET_NOT_LIVE: "行情非实时",
    MARKET_DATA_STALE: "行情数据过期",
    INSUFFICIENT_COMPLETED_BARS: "完成分钟不足",
  };
  return labels[code] ?? code;
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

function crosshairChange(
  bar: MarketBar | null,
  fallback: string | null,
  fallbackPreviousClose: string | null,
): string | null {
  if (bar === null) return fallback;
  const previousClose = crosshairPreviousClose(bar, fallbackPreviousClose);
  if (previousClose === null) return null;
  return (bar.close - previousClose).toString();
}

function crosshairChangePercent(
  bar: MarketBar | null,
  fallback: string | null,
  fallbackPreviousClose: string | null,
): string | null {
  if (bar === null) return fallback;
  const previousClose = crosshairPreviousClose(bar, fallbackPreviousClose);
  if (previousClose === null) return null;
  return (((bar.close / previousClose) - 1) * 100).toString();
}

function crosshairPreviousClose(
  bar: MarketBar,
  fallbackPreviousClose: string | null,
): number | null {
  if (bar.previous_close !== null && bar.previous_close > 0) {
    return bar.previous_close;
  }
  const parsedFallback = Number(fallbackPreviousClose);
  return Number.isFinite(parsedFallback) && parsedFallback > 0
    ? parsedFallback
    : null;
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

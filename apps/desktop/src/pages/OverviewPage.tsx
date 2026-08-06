import { useEffect, useMemo, useState } from "react";

import type { ApiClient } from "../api/client";
import type { IntradayBar, QuoteCard } from "../api/market-contracts";
import { MarketConnectionPanel } from "../components/MarketConnectionPanel";
import {
  useAddWatchlistMutation,
  useMarketConnectionQuery,
  useMarketHomeQuery,
  useMarketIntradayQuery,
  useMarketSearchQuery,
  useRemoveWatchlistMutation,
} from "../api/queries";

const coreIndexSlots: QuoteCard[] = [
  ["000001.SSE", "上证指数"],
  ["399001.SZSE", "深证成指"],
  ["399006.SZSE", "创业板指"],
  ["000688.SSE", "科创50"],
  ["000300.SSE", "沪深300"],
  ["399852.SZSE", "中证1000"],
].map(([instrument_id, name]) => ({
  instrument_id,
  name,
  kind: "index",
  state: "UNAVAILABLE",
  event_time: null,
  last_price: null,
  change: null,
  change_percent: null,
  previous_close: null,
  open: null,
  high: null,
  low: null,
  volume: null,
  turnover: null,
  source_id: null,
}));

export function OverviewPage({ client }: { client: ApiClient }) {
  const connectionQuery = useMarketConnectionQuery(client);
  const connection = connectionQuery.data;
  const homeQuery = useMarketHomeQuery(client, connection?.state);
  const home = homeQuery.data;
  const state = connection?.state ?? home?.connection.state ?? "UNAVAILABLE";
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const searchQuery = useMarketSearchQuery(client, search);
  const addWatchlist = useAddWatchlistMutation(client);
  const removeWatchlist = useRemoveWatchlistMutation(client);

  useEffect(() => {
    if (selectedId === null && home?.watchlist[0]) {
      setSelectedId(home.watchlist[0].instrument_id);
    }
  }, [home, selectedId]);

  const selected = useMemo(
    () => home?.watchlist.find((item) => item.instrument_id === selectedId)
      ?? home?.selected_instrument
      ?? home?.watchlist[0]
      ?? null,
    [home, selectedId],
  );
  const intradayQuery = useMarketIntradayQuery(client, selected?.instrument_id ?? null, state);

  if (homeQuery.isLoading) {
    return (
      <section className="market-terminal" aria-label="市场首页">
        <p className="market-loading">正在读取东财真实行情…</p>
        <div className="index-strip" aria-label="核心指数">
          {coreIndexSlots.map((index) => <QuoteTile key={index.instrument_id} quote={index} testId="core-index-loading" />)}
        </div>
      </section>
    );
  }

  if (homeQuery.isError || home === undefined) {
    return (
      <section className="market-terminal" aria-labelledby="market-home-title">
        <div className="market-unavailable">
          <h1 id="market-home-title">市场首页</h1>
          <strong>尚未连接东财行情</strong>
          <p>当前没有可展示的真实行情，程序不会用演示数字代替。</p>
        </div>
        <div className="index-strip" aria-label="核心指数">
          {coreIndexSlots.map((index) => <QuoteTile key={index.instrument_id} quote={index} testId="core-index" />)}
        </div>
      </section>
    );
  }

  return (
    <section className="market-terminal" aria-labelledby="market-home-title">
      <header className="market-toolbar">
        <div>
          <p className="market-toolbar__eyebrow">MARKET / REALTIME OBSERVATION</p>
          <h1 id="market-home-title">市场首页</h1>
        </div>
        <div className="market-toolbar__controls">
          <span className="source-badge" data-mode={state.toLowerCase()}>
            <span aria-hidden="true">●</span>东财掘金实时行情
          </span>
          <span className="readonly-badge">只读观察 · 不连接实盘账户</span>
          <span className="market-clock">
            {home.as_of ? <time>{formatTime(home.as_of)}</time> : null}
          </span>
        </div>
      </header>

      <MarketConnectionPanel client={client} compact />

      {state === "STALE" ? <div className="stale-banner"><strong>最后真实快照</strong><span>数据已延迟，不标记为实时。</span></div> : null}

      <div className="index-strip" aria-label="核心指数">
        {home.core_indices.map((index) => (
          <QuoteTile key={index.instrument_id} quote={index} testId="core-index" />
        ))}
      </div>

      <div className="market-primary-grid">
        <section className="terminal-panel watchlist-panel">
          <div className="terminal-panel__heading watchlist-heading">
            <div><p className="terminal-kicker">WATCHLIST / REAL DATA</p><h2>我的自选</h2></div>
            <label className="watchlist-search">
              <span className="sr-only">搜索证券</span>
              <input
                aria-label="搜索证券"
                type="search"
                value={search}
                placeholder="输入代码或名称"
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
          </div>
          {search.trim().length >= 2 ? (
            <div className="market-search-results">
              {searchQuery.isLoading ? <p>正在搜索东财证券目录…</p> : null}
              {searchQuery.isError ? <p role="alert">证券目录搜索失败，请稍后重试</p> : null}
              {searchQuery.data?.map((item) => (
                <button
                  key={item.instrument_id}
                  type="button"
                  onClick={() => {
                    addWatchlist.mutate(item.instrument_id);
                    setSearch("");
                    setSelectedId(item.instrument_id);
                  }}
                >
                  <strong>{item.name}</strong><span>{item.instrument_id}</span><em>加入自选</em>
                </button>
              ))}
              {!searchQuery.isLoading && searchQuery.data?.length === 0 ? <p>没有找到可订阅证券</p> : null}
            </div>
          ) : null}
          {home.watchlist.length === 0 ? (
            <div className="market-empty"><strong>自选列表为空</strong><p>搜索 A 股、ETF 或具体月份期货合约后加入。</p></div>
          ) : (
            <div className="watchlist-table-wrap">
              <table className="watchlist-table" aria-label="我的自选">
                <thead><tr><th>标的</th><th>最新</th><th>涨跌幅</th><th>数据状态</th><th /></tr></thead>
                <tbody>
                  {home.watchlist.map((item) => (
                    <tr key={item.instrument_id} data-selected={item.instrument_id === selected?.instrument_id} onClick={() => setSelectedId(item.instrument_id)}>
                      <td><div className="instrument-identity"><strong>{item.name}</strong><span>{item.instrument_id}</span></div></td>
                      <td>{formatNumber(item.last_price)}</td>
                      <td><MarketChange value={item.change_percent} /></td>
                      <td>{item.last_price === null ? "暂无真实数据" : state === "STALE" ? "已延迟" : "真实快照"}</td>
                      <td><button type="button" aria-label={`移除 ${item.name}`} onClick={(event) => { event.stopPropagation(); removeWatchlist.mutate(item.instrument_id); }}>移除</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="terminal-panel intraday-panel">
          <div className="terminal-panel__heading">
            <div><p className="terminal-kicker">INTRADAY / EASTMONEY</p><h2>{selected ? `${selected.name} · ${selected.instrument_id}` : "分时行情"}</h2></div>
          </div>
          {selected === null ? (
            <div className="market-empty"><strong>尚未选择证券</strong><p>从自选列表选择一个标的查看分时。</p></div>
          ) : (
            <>
              <div className="intraday-price"><strong>{formatNumber(selected.last_price)}</strong><MarketChange value={selected.change_percent} /></div>
              {intradayQuery.isLoading ? (
                <div className="market-empty"><strong>正在读取真实分时</strong><p>从东财加载当日分钟线…</p></div>
              ) : intradayQuery.isError ? (
                <div className="market-empty"><strong>分时数据读取失败</strong><p>请确认东财连接后重试。</p></div>
              ) : intradayQuery.data && intradayQuery.data.length > 0 ? (
                <IntradayChart bars={intradayQuery.data} name={selected.name} />
              ) : (
                <div className="market-empty"><strong>暂无真实分时数据</strong><p>当前交易日没有可用分钟线。</p></div>
              )}
              <p className="data-muted">当前快照无盘口数据</p>
            </>
          )}
        </section>
      </div>

      <div className="market-secondary-grid">
        <UnavailablePanel title="市场温度" eyebrow="MARKET BREADTH" reason={home.breadth.reason} />
        <UnavailablePanel title="AI 盘中情报" eyebrow="AI / INTELLIGENCE" reason={home.intelligence.reason} />
        <section className="terminal-panel">
          <div className="terminal-panel__heading"><div><p className="terminal-kicker">QUANT SCAN</p><h2>量化候选</h2></div></div>
          {home.candidates.length === 0 ? <div className="market-empty"><p>量化候选将在实时策略链路接入后生成</p></div> : null}
        </section>
      </div>
    </section>
  );
}

function QuoteTile({ quote, testId }: { quote: QuoteCard; testId: string }) {
  return (
    <article className="index-quote" data-testid={testId}>
      <span>{quote.name}</span>
      <strong>{formatNumber(quote.last_price)}</strong>
      {quote.last_price === null ? null : <MarketChange value={quote.change_percent} />}
    </article>
  );
}

function IntradayChart({ bars, name }: { bars: IntradayBar[]; name: string }) {
  const samples = bars.flatMap((bar) => {
    const close = Number(bar.close);
    const timestamp = typeof bar.bob === "string" ? bar.bob : typeof bar.eob === "string" ? bar.eob : null;
    return Number.isFinite(close) && timestamp !== null ? [{ close, timestamp }] : [];
  });
  if (samples.length === 0) {
    return <div className="market-empty"><strong>分时记录缺少价格</strong><p>东财返回了记录，但没有可绘制的收盘价。</p></div>;
  }

  const width = 640;
  const height = 176;
  const insetX = 8;
  const insetY = 12;
  const closes = samples.map((sample) => sample.close);
  const minimum = Math.min(...closes);
  const maximum = Math.max(...closes);
  const spread = Math.max(maximum - minimum, Math.abs(maximum) * 0.002, 0.001);
  const floor = minimum - spread * 0.12;
  const ceiling = maximum + spread * 0.12;
  const plotWidth = width - insetX * 2;
  const plotHeight = height - insetY * 2;
  const points = samples.map((sample, index) => ({
    x: insetX + (samples.length === 1 ? plotWidth / 2 : (index / (samples.length - 1)) * plotWidth),
    y: insetY + ((ceiling - sample.close) / (ceiling - floor)) * plotHeight,
  }));
  const linePath = points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const areaPath = `${linePath} L${points.at(-1)?.x.toFixed(2)},${height} L${points[0]?.x.toFixed(2)},${height} Z`;
  const rising = samples.at(-1)!.close >= samples[0]!.close;

  return (
    <figure className="intraday-chart" data-trend={rising ? "up" : "down"}>
      <figcaption>
        <strong>{samples.length} 条真实分钟线</strong>
        <span>{minimum.toFixed(3)} — {maximum.toFixed(3)}</span>
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${name}当日分时价格走势`} preserveAspectRatio="none">
        <g className="chart-grid" aria-hidden="true">
          {[0.25, 0.5, 0.75].map((ratio) => <line key={ratio} x1={insetX} x2={width - insetX} y1={height * ratio} y2={height * ratio} />)}
        </g>
        <path className="chart-area" d={areaPath} />
        <path className="chart-line" d={linePath} vectorEffect="non-scaling-stroke" />
        <circle className="chart-last-point" cx={points.at(-1)!.x} cy={points.at(-1)!.y} r="3.5" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="chart-axis"><span>{formatBarTime(samples[0]!.timestamp)}</span><span>11:30 / 13:00</span><span>{formatBarTime(samples.at(-1)!.timestamp)}</span></div>
    </figure>
  );
}

function UnavailablePanel({ title, eyebrow, reason }: { title: string; eyebrow: string; reason: string }) {
  return <section className="terminal-panel"><div className="terminal-panel__heading"><div><p className="terminal-kicker">{eyebrow}</p><h2>{title}</h2></div></div><div className="market-empty"><strong>当前不可用</strong><p>{reason}</p></div></section>;
}

function MarketChange({ value }: { value: string | null }) {
  if (value === null) return <span>—</span>;
  const numeric = Number(value);
  return <span className={`market-change ${numeric >= 0 ? "market-up" : "market-down"}`}>{numeric >= 0 ? "+" : ""}{numeric.toFixed(2)}%</span>;
}

function formatNumber(value: string | null): string {
  if (value === null) return "暂无真实数据";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(numeric) : value;
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value));
}

function formatBarTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

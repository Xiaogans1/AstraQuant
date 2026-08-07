import { useEffect, useMemo, useState } from "react";

import type { ApiClient } from "../api/client";
import type { QuoteCard } from "../api/market-contracts";
import { InstrumentSearchPicker } from "../components/InstrumentSearchPicker";
import { MarketConnectionPanel } from "../components/MarketConnectionPanel";
import { MarketWorkspace } from "../components/MarketWorkspace";
import {
  useAddWatchlistMutation,
  useMarketConnectionQuery,
  useMarketHomeQuery,
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
            <InstrumentSearchPicker
              client={client}
              value={null}
              className="watchlist-search"
              onChange={(selection) => {
                if (selection === null) return;
                addWatchlist.mutate(selection.instrument_id);
                setSelectedId(selection.instrument_id);
              }}
            />
          </div>
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

      </div>

      {selected ? (
        <MarketWorkspace client={client} quote={selected} state={state} />
      ) : (
        <section className="terminal-panel market-workspace">
          <div className="market-empty"><strong>尚未选择证券</strong><p>从自选列表选择一个标的后查看专业行情图。</p></div>
        </section>
      )}

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

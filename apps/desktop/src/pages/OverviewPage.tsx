import {
  useMemo,
  useState,
} from "react";

import {
  developmentMarketSnapshot,
  searchMarketCatalog,
} from "../features/market/developmentMarket";
import type {
  InstrumentKind,
  MarketInstrument,
} from "../features/market/types";

type WatchlistFilter = "all" | InstrumentKind;

const kindLabels: Record<InstrumentKind, string> = {
  stock: "股票",
  etf: "ETF",
  future: "期货",
};

export function OverviewPage() {
  const snapshot = developmentMarketSnapshot;
  const [watchlist, setWatchlist] = useState(snapshot.watchlist);
  const [selectedSymbol, setSelectedSymbol] = useState(
    snapshot.watchlist[0]?.symbol ?? "",
  );
  const [filter, setFilter] = useState<WatchlistFilter>("all");
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const selectedInstrument =
    watchlist.find((item) => item.symbol === selectedSymbol) ?? watchlist[0];
  const visibleWatchlist = watchlist.filter(
    (item) => filter === "all" || item.kind === filter,
  );
  const searchResults = useMemo(() => {
    const watchedSymbols = new Set(watchlist.map((item) => item.symbol));
    return searchMarketCatalog(search).filter(
      (item) => !watchedSymbols.has(item.symbol),
    );
  }, [search, watchlist]);

  function addToWatchlist(instrument: MarketInstrument) {
    setWatchlist((current) => [...current, instrument]);
    setSelectedSymbol(instrument.symbol);
    setFilter("all");
    setSearch("");
    setNotice("已加入本次会话的自选列表");
  }

  return (
    <section className="market-terminal" aria-labelledby="market-home-title">
      <header className="market-toolbar">
        <div>
          <p className="market-toolbar__eyebrow">MARKET / LIVE WORKSPACE</p>
          <h1 id="market-home-title">市场首页</h1>
        </div>
        <div className="market-toolbar__controls">
          <span className="source-badge" data-mode={snapshot.sourceMode}>
            <span aria-hidden="true">●</span>
            {snapshot.sourceLabel}
          </span>
          <span className="readonly-badge">只读观察 · 不连接实盘账户</span>
          <span className="market-clock">
            {snapshot.marketStatus} <time>{snapshot.asOf}</time>
          </span>
        </div>
      </header>

      <div className="index-strip" aria-label="主要指数">
        {snapshot.indexes.map((index) => (
          <article className="index-quote" key={index.symbol}>
            <span>{index.name}</span>
            <strong>{formatPrice(index.price)}</strong>
            <MarketChange value={index.changePercent} />
          </article>
        ))}
      </div>

      <div className="market-primary-grid">
        <section className="terminal-panel watchlist-panel">
          <div className="terminal-panel__heading watchlist-heading">
            <div>
              <p className="terminal-kicker">WATCHLIST</p>
              <h2>我的自选</h2>
            </div>
            <div className="watchlist-search">
              <label>
                <span className="sr-only">添加自选</span>
                <input
                  type="search"
                  aria-label="添加自选"
                  value={search}
                  placeholder="搜索代码或名称"
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setNotice(null);
                  }}
                />
              </label>
              {search.length > 0 ? (
                <div className="watchlist-search__results" aria-label="搜索结果">
                  {searchResults.length === 0 ? (
                    <p>没有可添加的匹配标的</p>
                  ) : (
                    searchResults.map((instrument) => (
                      <button
                        type="button"
                        key={instrument.symbol}
                        aria-label={`添加${instrument.name}`}
                        onClick={() => addToWatchlist(instrument)}
                      >
                        <span>
                          <strong>{instrument.name}</strong>
                          <small>{instrument.symbol}</small>
                        </span>
                        <b>＋</b>
                      </button>
                    ))
                  )}
                </div>
              ) : null}
            </div>
          </div>

          <div className="watchlist-filters" aria-label="自选类型">
            {([
              ["all", "全部"],
              ["stock", "股票"],
              ["etf", "ETF"],
              ["future", "期货"],
            ] as const).map(([value, label]) => (
              <button
                type="button"
                key={value}
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>

          {notice ? <p className="watchlist-notice" role="status">{notice}</p> : null}

          <div className="watchlist-table-wrap">
            <table className="watchlist-table" aria-label="我的自选">
              <thead>
                <tr>
                  <th>标的</th>
                  <th>最新</th>
                  <th>涨跌幅</th>
                  <th>成交额</th>
                  <th>量化状态</th>
                  <th>AI 计划</th>
                </tr>
              </thead>
              <tbody>
                {visibleWatchlist.map((instrument) => (
                  <tr
                    key={instrument.symbol}
                    data-selected={instrument.symbol === selectedInstrument?.symbol}
                  >
                    <td>
                      <button
                        type="button"
                        className="instrument-identity"
                        aria-label={`查看${instrument.name}`}
                        onClick={() => setSelectedSymbol(instrument.symbol)}
                      >
                        <strong>{instrument.name}</strong>
                        <span>
                          {kindLabels[instrument.kind]} · {instrument.symbol}
                        </span>
                      </button>
                    </td>
                    <td className="numeric-cell">{formatPrice(instrument.price)}</td>
                    <td><MarketChange value={instrument.changePercent} /></td>
                    <td>{instrument.turnover}</td>
                    <td><span className="quant-state">{instrument.quantStatus}</span></td>
                    <td>{instrument.aiBias}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {selectedInstrument ? (
          <InstrumentWorkspace instrument={selectedInstrument} />
        ) : null}
      </div>

      <div className="market-secondary-grid">
        <section className="terminal-panel market-breadth">
          <div className="terminal-panel__heading">
            <div>
              <p className="terminal-kicker">MARKET BREADTH</p>
              <h2>市场温度</h2>
            </div>
            <span>全 A 股</span>
          </div>
          <div className="breadth-counts">
            <span><b className="market-up">{snapshot.breadth.rising.toLocaleString()}</b> 上涨</span>
            <span><b>{snapshot.breadth.flat.toLocaleString()}</b> 平盘</span>
            <span><b className="market-down">{snapshot.breadth.falling.toLocaleString()}</b> 下跌</span>
          </div>
          <div className="breadth-bar" aria-label="市场涨跌分布">
            <i style={{ flex: snapshot.breadth.rising }} />
            <i style={{ flex: snapshot.breadth.flat }} />
            <i style={{ flex: snapshot.breadth.falling }} />
          </div>
          <div className="sector-strip">
            {snapshot.sectors.map((sector) => (
              <span key={sector.name}>
                {sector.name} <MarketChange value={sector.changePercent} />
              </span>
            ))}
          </div>
        </section>

        <section className="terminal-panel intelligence-card">
          <div className="terminal-panel__heading">
            <div>
              <p className="terminal-kicker">REG / INTELLIGENCE</p>
              <h2>AI 盘中情报</h2>
            </div>
            <span>{snapshot.intelligence.stage} · {snapshot.intelligence.progress}%</span>
          </div>
          <div className="intelligence-progress" aria-label={`情报处理进度 ${snapshot.intelligence.progress}%`}>
            <i style={{ width: `${snapshot.intelligence.progress}%` }} />
          </div>
          <h3>{snapshot.intelligence.title}</h3>
          <p>
            {snapshot.intelligence.evidenceCount} 条有效证据，正在审查 {snapshot.intelligence.challengeCount} 个反向判断。
            {snapshot.intelligence.summary}
          </p>
          <button type="button" disabled>证据室将在 AI 接入后开放</button>
        </section>

        <section className="terminal-panel quant-candidates">
          <div className="terminal-panel__heading">
            <div>
              <p className="terminal-kicker">QUANT SCAN</p>
              <h2>量化候选</h2>
            </div>
            <span>全市场扫描 · 模拟</span>
          </div>
          <ol>
            {snapshot.candidates.map((candidate, index) => (
              <li key={candidate.symbol}>
                <span className="candidate-rank">{String(index + 1).padStart(2, "0")}</span>
                <span>
                  <strong>{candidate.name}</strong>
                  <small>{candidate.reason}</small>
                </span>
                <b>{candidate.score}</b>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </section>
  );
}

function InstrumentWorkspace({ instrument }: { instrument: MarketInstrument }) {
  const path = buildLinePath(instrument.intraday, 620, 210);
  const areaPath = `${path} L 620 210 L 0 210 Z`;

  return (
    <section className="terminal-panel instrument-panel">
      <div className="terminal-panel__heading instrument-heading">
        <div>
          <p className="terminal-kicker">INTRADAY / {instrument.exchange}</p>
          <h2>{instrument.name} · {instrument.symbol}</h2>
        </div>
        <button type="button" disabled>加入 Paper</button>
      </div>
      <div className="instrument-tabs" aria-label="标的视图">
        <button type="button" aria-pressed="true">分时</button>
        <button type="button" disabled>日 K</button>
        <button type="button" disabled>资金</button>
        <button type="button" disabled>信号</button>
      </div>
      <div className="instrument-quote">
        <strong>{formatPrice(instrument.price)}</strong>
        <MarketChange value={instrument.changePercent} prefix={formatSigned(instrument.change)} />
      </div>
      <div className="intraday-chart" aria-label={`${instrument.name}分时图`}>
        <svg role="img" viewBox="0 0 620 210" preserveAspectRatio="none">
          <defs>
            <linearGradient id={`chart-fill-${instrument.symbol.replaceAll(".", "-")}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="currentColor" stopOpacity="0.26" />
              <stop offset="1" stopColor="currentColor" stopOpacity="0" />
            </linearGradient>
          </defs>
          <g className="chart-grid" aria-hidden="true">
            <line x1="0" y1="52" x2="620" y2="52" />
            <line x1="0" y1="105" x2="620" y2="105" />
            <line x1="0" y1="158" x2="620" y2="158" />
          </g>
          <path className="chart-area" d={areaPath} fill={`url(#chart-fill-${instrument.symbol.replaceAll(".", "-")})`} />
          <path className="chart-line" d={path} />
        </svg>
        <div className="chart-axis"><span>09:30</span><span>11:30 / 13:00</span><span>15:00</span></div>
      </div>
      <div className="instrument-depth">
        <div>
          <h3>盘口预览</h3>
          {instrument.orderBook.map((level) => (
            <p key={`${level.side}-${level.level}`}>
              <span>{level.side === "ask" ? "卖" : "买"}{chineseLevel(level.level)}</span>
              <b className={level.side === "ask" ? "market-down" : "market-up"}>{formatPrice(level.price)}</b>
              <span>{level.volume.toLocaleString()}</span>
            </p>
          ))}
        </div>
        <dl>
          <div><dt>量比</dt><dd>{instrument.volumeRatio.toFixed(2)}</dd></div>
          <div><dt>换手</dt><dd>{instrument.turnoverRate === null ? "—" : `${instrument.turnoverRate.toFixed(2)}%`}</dd></div>
          <div><dt>量化</dt><dd>{instrument.quantStatus}</dd></div>
          <div><dt>AI</dt><dd>{instrument.aiBias}</dd></div>
        </dl>
      </div>
    </section>
  );
}

function MarketChange({ value, prefix }: { value: number; prefix?: string }) {
  const direction = value > 0 ? "up" : value < 0 ? "down" : "flat";
  return (
    <span className={`market-change market-${direction}`}>
      {prefix ? `${prefix} ` : ""}{value > 0 ? "+" : ""}{value.toFixed(2)}%
    </span>
  );
}

function formatPrice(value: number): string {
  const fractionDigits = value < 10 ? 3 : value < 100 ? 2 : 2;
  return value.toLocaleString("zh-CN", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

function formatSigned(value: number): string {
  return `${value > 0 ? "+" : ""}${formatPrice(value)}`;
}

function buildLinePath(values: number[], width: number, height: number): string {
  if (values.length === 0) {
    return "";
  }
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const spread = maximum - minimum || 1;
  return values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - minimum) / spread) * (height - 24) - 12;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function chineseLevel(level: number): string {
  return ["", "一", "二", "三", "四", "五"][level] ?? String(level);
}

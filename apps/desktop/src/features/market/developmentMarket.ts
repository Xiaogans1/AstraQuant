import type {
  MarketInstrument,
  MarketSnapshot,
} from "./types";

const instruments: MarketInstrument[] = [
  {
    symbol: "600000.SSE",
    name: "浦发银行",
    kind: "stock",
    exchange: "上交所",
    price: 12.34,
    change: 0.21,
    changePercent: 1.73,
    turnover: "18.4 亿",
    quantStatus: "放量观察",
    aiBias: "偏多 · 72%",
    volumeRatio: 1.43,
    turnoverRate: 0.61,
    intraday: [12.08, 12.1, 12.07, 12.14, 12.17, 12.15, 12.22, 12.2, 12.28, 12.26, 12.34],
    orderBook: [
      { side: "ask", level: 2, price: 12.36, volume: 2104 },
      { side: "ask", level: 1, price: 12.35, volume: 1842 },
      { side: "bid", level: 1, price: 12.34, volume: 3621 },
      { side: "bid", level: 2, price: 12.33, volume: 1588 },
    ],
  },
  {
    symbol: "510300.SSE",
    name: "沪深300ETF",
    kind: "etf",
    exchange: "上交所",
    price: 4.128,
    change: 0.021,
    changePercent: 0.51,
    turnover: "32.7 亿",
    quantStatus: "接近买点",
    aiBias: "中性偏多",
    volumeRatio: 1.18,
    turnoverRate: 0.94,
    intraday: [4.101, 4.105, 4.099, 4.108, 4.112, 4.11, 4.119, 4.117, 4.123, 4.121, 4.128],
    orderBook: [
      { side: "ask", level: 2, price: 4.13, volume: 8500 },
      { side: "ask", level: 1, price: 4.129, volume: 12300 },
      { side: "bid", level: 1, price: 4.128, volume: 16400 },
      { side: "bid", level: 2, price: 4.127, volume: 9700 },
    ],
  },
  {
    symbol: "588000.SSE",
    name: "科创50ETF",
    kind: "etf",
    exchange: "上交所",
    price: 1.036,
    change: -0.003,
    changePercent: -0.29,
    turnover: "12.1 亿",
    quantStatus: "等待确认",
    aiBias: "震荡",
    volumeRatio: 0.89,
    turnoverRate: 1.12,
    intraday: [1.041, 1.04, 1.042, 1.039, 1.037, 1.038, 1.035, 1.037, 1.034, 1.035, 1.036],
    orderBook: [
      { side: "ask", level: 2, price: 1.038, volume: 20100 },
      { side: "ask", level: 1, price: 1.037, volume: 28600 },
      { side: "bid", level: 1, price: 1.036, volume: 31500 },
      { side: "bid", level: 2, price: 1.035, volume: 22900 },
    ],
  },
  {
    symbol: "RB0.SHFE",
    name: "螺纹主连",
    kind: "future",
    exchange: "上期所",
    price: 3241,
    change: 27,
    changePercent: 0.84,
    turnover: "—",
    quantStatus: "趋势增强",
    aiBias: "事件敏感",
    volumeRatio: 1.67,
    turnoverRate: null,
    intraday: [3210, 3218, 3215, 3224, 3221, 3230, 3228, 3237, 3233, 3239, 3241],
    orderBook: [
      { side: "ask", level: 2, price: 3243, volume: 438 },
      { side: "ask", level: 1, price: 3242, volume: 612 },
      { side: "bid", level: 1, price: 3241, volume: 731 },
      { side: "bid", level: 2, price: 3240, volume: 506 },
    ],
  },
  {
    symbol: "518880.SSE",
    name: "黄金ETF",
    kind: "etf",
    exchange: "上交所",
    price: 6.723,
    change: 0.042,
    changePercent: 0.63,
    turnover: "9.8 亿",
    quantStatus: "防御观察",
    aiBias: "事件偏多",
    volumeRatio: 1.24,
    turnoverRate: 0.48,
    intraday: [6.68, 6.687, 6.691, 6.699, 6.695, 6.706, 6.711, 6.708, 6.716, 6.72, 6.723],
    orderBook: [
      { side: "ask", level: 2, price: 6.725, volume: 7300 },
      { side: "ask", level: 1, price: 6.724, volume: 11200 },
      { side: "bid", level: 1, price: 6.723, volume: 9600 },
      { side: "bid", level: 2, price: 6.722, volume: 8100 },
    ],
  },
  {
    symbol: "000001.SZSE",
    name: "平安银行",
    kind: "stock",
    exchange: "深交所",
    price: 11.76,
    change: 0.18,
    changePercent: 1.55,
    turnover: "21.3 亿",
    quantStatus: "板块共振",
    aiBias: "偏多 · 69%",
    volumeRatio: 1.31,
    turnoverRate: 0.72,
    intraday: [11.58, 11.61, 11.6, 11.65, 11.63, 11.68, 11.7, 11.69, 11.73, 11.74, 11.76],
    orderBook: [
      { side: "ask", level: 2, price: 11.78, volume: 1720 },
      { side: "ask", level: 1, price: 11.77, volume: 2340 },
      { side: "bid", level: 1, price: 11.76, volume: 2980 },
      { side: "bid", level: 2, price: 11.75, volume: 1870 },
    ],
  },
];

export const marketCatalog = instruments;

export const developmentMarketSnapshot: MarketSnapshot = {
  sourceMode: "simulation",
  sourceLabel: "开发模拟行情",
  marketStatus: "交易中（模拟）",
  asOf: "10:28:36",
  indexes: [
    { symbol: "000001.SSE", name: "上证指数", price: 3421.68, changePercent: 0.62 },
    { symbol: "399001.SZSE", name: "深证成指", price: 10884.21, changePercent: 0.91 },
    { symbol: "399006.SZSE", name: "创业板指", price: 2176.43, changePercent: -0.18 },
    { symbol: "000300.SSE", name: "沪深 300", price: 4012.75, changePercent: 0.53 },
    { symbol: "000905.SSE", name: "中证 500", price: 5936.2, changePercent: 1.12 },
  ],
  watchlist: instruments.slice(0, 4),
  breadth: { rising: 3218, flat: 126, falling: 1842 },
  sectors: [
    { name: "银行", changePercent: 2.31 },
    { name: "算力", changePercent: 1.86 },
    { name: "光伏", changePercent: -1.12 },
    { name: "医药", changePercent: -0.74 },
  ],
  intelligence: {
    stage: "反证审查",
    progress: 68,
    title: "震荡偏强，金融权重占优",
    summary: "量化核心仍将根据实时价格确认买卖点；AI 结论只用于当日策略解释。",
    evidenceCount: 37,
    challengeCount: 8,
  },
  candidates: [
    { symbol: "510300.SSE", name: "沪深300ETF", reason: "动量 + 资金共振", score: 82 },
    { symbol: "600000.SSE", name: "浦发银行", reason: "板块强度 + 放量", score: 78 },
    { symbol: "518880.SSE", name: "黄金ETF", reason: "事件防御 + 趋势", score: 73 },
  ],
};

export function searchMarketCatalog(query: string): MarketInstrument[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (normalized.length === 0) {
    return [];
  }
  return marketCatalog
    .filter((item) =>
      `${item.symbol} ${item.name}`.toLocaleLowerCase().includes(normalized),
    )
    .slice(0, 6);
}

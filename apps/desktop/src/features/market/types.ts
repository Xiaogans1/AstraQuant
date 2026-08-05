export type InstrumentKind = "stock" | "etf" | "future";
export type MarketDirection = "up" | "down" | "flat";

export interface OrderBookLevel {
  side: "ask" | "bid";
  level: number;
  price: number;
  volume: number;
}

export interface MarketInstrument {
  symbol: string;
  name: string;
  kind: InstrumentKind;
  exchange: string;
  price: number;
  change: number;
  changePercent: number;
  turnover: string;
  quantStatus: string;
  aiBias: string;
  volumeRatio: number;
  turnoverRate: number | null;
  intraday: number[];
  orderBook: OrderBookLevel[];
}

export interface IndexQuote {
  symbol: string;
  name: string;
  price: number;
  changePercent: number;
}

export interface MarketBreadth {
  rising: number;
  flat: number;
  falling: number;
}

export interface SectorMove {
  name: string;
  changePercent: number;
}

export interface IntelligenceBrief {
  stage: string;
  progress: number;
  title: string;
  summary: string;
  evidenceCount: number;
  challengeCount: number;
}

export interface QuantCandidate {
  symbol: string;
  name: string;
  reason: string;
  score: number;
}

export interface MarketSnapshot {
  sourceMode: "simulation" | "realtime" | "delayed";
  sourceLabel: string;
  marketStatus: string;
  asOf: string;
  indexes: IndexQuote[];
  watchlist: MarketInstrument[];
  breadth: MarketBreadth;
  sectors: SectorMove[];
  intelligence: IntelligenceBrief;
  candidates: QuantCandidate[];
}

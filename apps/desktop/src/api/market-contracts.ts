export type ConnectionState =
  | "DISCONNECTED"
  | "CONNECTING"
  | "LIVE"
  | "STALE"
  | "CLOSED"
  | "UNAVAILABLE"
  | "ERROR";

export interface MarketConnection {
  provider_id: string;
  sdk_configured: boolean;
  token_configured: boolean;
  state: ConnectionState;
  connected_at: string | null;
  last_event_at: string | null;
  error_code: string | null;
  instrument_count: number;
  parse_error_count: number;
  reconnect_count: number;
}

export interface EastmoneyConfigRequest {
  sdk_python_path: string;
  token: string;
}

export interface EastmoneyConfigStatus {
  provider_id: string;
  sdk_configured: boolean;
  token_configured: boolean;
}

export interface QuoteCard {
  instrument_id: string;
  name: string;
  kind: string;
  state: ConnectionState;
  event_time: string | null;
  last_price: string | null;
  change: string | null;
  change_percent: string | null;
  previous_close: string | null;
  open: string | null;
  high: string | null;
  low: string | null;
  volume: string | null;
  turnover: string | null;
  source_id: string | null;
}

export interface UnavailableFeature {
  status: "UNAVAILABLE";
  reason: string;
}

export interface QuantCandidate {
  instrument_id: string;
  score: number;
}

export interface MarketHome {
  connection: MarketConnection;
  core_indices: QuoteCard[];
  watchlist: QuoteCard[];
  selected_instrument: QuoteCard | null;
  breadth: UnavailableFeature;
  intelligence: UnavailableFeature;
  candidates: QuantCandidate[];
  as_of: string | null;
}

export interface InstrumentSearchResult {
  instrument_id: string;
  name: string;
  kind: string;
}

export interface IntradayBar {
  symbol?: string;
  bob?: string;
  eob?: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  amount?: number;
  [key: string]: unknown;
}

export type MarketPeriod =
  | "intraday"
  | "1m"
  | "5m"
  | "15m"
  | "30m"
  | "60m"
  | "1d"
  | "1w"
  | "1mo"
  | "1y";

export interface MarketBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;
  previous_close: number | null;
}

export type SignalAction = "BUY" | "SELL" | "HOLD";
export type SignalState = "ACTIVE" | "SUPPRESSED" | "WARMING_UP";

export interface RealtimeFeatureStatus {
  feature_snapshot_id: string;
  status: "READY" | "WARMING_UP";
  completed_bar_count: number;
  reason_codes: string[];
}

export interface SignalFrame {
  signal_id: string;
  instrument_id: string;
  event_time: string;
  decision_time: string;
  expires_at: string;
  action: SignalAction;
  state: SignalState;
  reference_price: string | null;
  confidence: string;
  strategy_id: string;
  strategy_version: string;
  feature_version: string;
  reason_codes: string[];
}

export interface DecisionRecord {
  decision_id: string;
  feature_snapshot_id: string;
  signal_id: string;
  strategy_id: string;
  strategy_version: string;
  market_event_time: string;
  decision_time: string;
  advisory_checks: string[];
}

export interface RealtimeQuantDecision {
  features: RealtimeFeatureStatus;
  signal: SignalFrame;
  decision_record: DecisionRecord;
}

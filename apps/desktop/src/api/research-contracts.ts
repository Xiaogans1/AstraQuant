export interface ResearchDatasetSummary {
  dataset_id: string;
  instrument_id: string;
  bar_count: number;
  start: string;
  end: string;
}

export interface ReplayRequest {
  dataset_id: string;
  model_id: string;
  start_date: string | null;
  end_date: string | null;
  initial_cash: string;
}

export interface ReplayTrade {
  index: number;
  timestamp: string;
  side: "BUY" | "SELL";
  price: string;
  quantity: number;
  pnl: string;
}

export interface ReplayBar {
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

export interface ReplayResult {
  dataset_id: string;
  model_id: string;
  instrument_id: string;
  start: string;
  end: string;
  bars_count: number;
  initial_cash: string;
  final_cash: string;
  realized_pnl: string;
  net_return_percent: number;
  buys: number;
  sells: number;
  win_rate: number;
  trades: ReplayTrade[];
  bars: ReplayBar[];
  equity_points: Array<[string, string]>;
}

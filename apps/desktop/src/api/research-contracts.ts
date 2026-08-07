export interface ResearchDatasetSummary {
  dataset_id: string;
  instrument_id: string;
  bar_count: number;
  start: string;
  end: string;
}

export interface ReplayOpeningPosition {
  instrument_id: string;
  quantity: number;
  available_quantity: number;
  average_cost: string;
}

export interface ReplayInstrumentInput {
  instrument_id: string;
  start_date: string | null;
  end_date: string | null;
  opening?: ReplayOpeningPosition | null;
}

export interface ReplayRequest {
  instruments: ReplayInstrumentInput[];
  model_id: string;
  initial_cash: string;
}

export interface ReplayTrade {
  index: number;
  timestamp: string;
  side: "BUY" | "SELL";
  price: string;
  quantity: number;
  pnl: string;
  proba: number;
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
  instrument_id: string;
  model_id: string;
  model_status: string;
  start: string;
  end: string;
  bars_count: number;
  initial_cash: string;
  initial_equity: string;
  final_cash: string;
  realized_pnl: string;
  net_return_percent: number;
  max_drawdown_percent: number;
  sharpe: number;
  profit_factor: number;
  buys: number;
  sells: number;
  win_rate: number;
  position_remaining: number;
  trades: ReplayTrade[];
  bars: ReplayBar[];
  equity_points: Array<[string, string]>;
}

export interface TrainRequest {
  dataset_ids: string[];
  instruments: ReplayInstrumentInput[];
  model_id: string;
  horizon: number;
  threshold: string;
}

export interface TrainResult {
  model_id: string;
  status: string;
  rows: number;
  auc: number;
  gross_return: number;
  net_return: number;
  trades: number;
  recommended_buy: number;
  recommended_sell: number;
  artifact_path: string;
}

export interface ExperimentSummary {
  experiment_id: string;
  created_at: string;
  summary_json: string;
}

export interface ExperimentDetail {
  experiment_id: string;
  created_at: string;
  request_json: string;
  summary_json: string;
  results_json: string;
}

export interface DailySummaryRow {
  trading_date: string;
  equity_end: string;
  cash_end: string;
  equity_pnl: string;
  external_flow: string;
  strategy_pnl: string;
  strategy_pnl_percent: number | null;
  fills: string;
  has_daily_open: boolean;
}

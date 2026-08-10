export type PaperAccountMode = "PAPER" | "MIRROR";
export type PaperOrderSide = "BUY" | "SELL";
export type PaperOrderStatus = "FILLED" | "REJECTED";
export type LegacySemanticClass = "LEGACY_SEMANTICS";
export type LegacyEvidenceClass = "LEGACY_UNVERIFIED";
export type LegacyRunClass = "EXPLORATORY";

export interface PaperAccount {
  account_id: string;
  name: string;
  mode: PaperAccountMode;
  initial_cash: string;
  cash: string;
  created_at: string;
  updated_at: string;
  semantic_class: LegacySemanticClass;
  evidence_class: LegacyEvidenceClass;
  run_class: LegacyRunClass;
}

export interface PaperAccountSummary extends PaperAccount {
  initial_equity: string;
  total_equity: string;
  total_pnl: string;
}

export interface PaperPosition {
  instrument_id: string;
  name: string | null;
  quantity: number;
  available_quantity: number;
  average_cost: string;
  last_price: string | null;
  previous_close: string | null;
  market_value: string;
  unrealized_pnl: string;
  unrealized_pnl_percent: string | null;
  marked_at: string | null;
}

export interface PaperEquity {
  snapshot_id: string;
  cash: string;
  market_value: string;
  total_equity: string;
  initial_equity: string;
  total_pnl: string;
  total_pnl_percent: string | null;
  as_of: string;
}

export interface PaperAccountDetail {
  account: PaperAccount;
  positions: PaperPosition[];
  latest_equity: PaperEquity | null;
}

export interface PaperOrder {
  order_id: string;
  account_id: string;
  idempotency_key: string;
  instrument_id: string;
  side: PaperOrderSide;
  quantity: number;
  status: PaperOrderStatus;
  submitted_at: string;
  updated_at: string;
  reject_reason: string | null;
}

export interface PaperFill {
  fill_id: string;
  order_id: string;
  instrument_id: string;
  side: PaperOrderSide;
  quantity: number;
  price: string;
  gross_amount: string;
  total_fee: string;
  net_cash_flow: string;
  occurred_at: string;
}

export interface CreatePaperAccountRequest {
  name: string;
  mode: PaperAccountMode;
  initial_cash: string;
}

export interface OpeningPositionRequest {
  instrument_id: string;
  name: string | null;
  quantity: number;
  available_quantity: number;
  average_cost: string;
}

export interface PaperCashBalanceRequest {
  cash: string;
}

export interface PaperMarketOrderRequest {
  instrument_id: string;
  side: PaperOrderSide;
  quantity: number;
  name: string | null;
  stamp_duty_exempt: boolean;
}

export interface PaperOrderExecution {
  order: PaperOrder;
  fill: PaperFill | null;
  portfolio: PaperAccountDetail;
}

export interface PaperStrategyRunRequest {
  instrument_id: string;
  quantity: number;
  auto_execute: boolean;
  max_position_percent: string;
}

export interface PaperStrategySignal {
  signal_id: string;
  instrument_id: string;
  action: "BUY" | "SELL" | "HOLD";
  state: "ACTIVE" | "SUPPRESSED" | "WARMING_UP";
  reference_price: string | null;
  confidence: string;
  strategy_id: string;
  strategy_version: string;
  feature_version: string;
  reason_codes: string[];
  event_time: string;
  decision_time: string;
  expires_at: string;
}

export interface PaperStrategyRun {
  outcome: "HOLD" | "SUGGESTED" | "BLOCKED" | "EXECUTED";
  proposed_side: PaperOrderSide | null;
  proposed_quantity: number;
  risk_reason: string | null;
  decision_id: string;
  advisory_checks: string[];
  signal: PaperStrategySignal;
  order: PaperOrder | null;
  fill: PaperFill | null;
  semantic_class: LegacySemanticClass;
  evidence_class: LegacyEvidenceClass;
  run_class: LegacyRunClass;
}

export interface PaperStrategyStatus {
  loop_enabled: boolean;
  loop_interval_seconds: number;
  last_scan_at: string | null;
}

export interface ModelRegistryView {
  model_id: string;
  strategy_id: string;
  strategy_version: string;
  feature_version: string;
  artifact_path: string;
  metrics_json: string;
  params_json: string;
  status: string;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  semantic_class: LegacySemanticClass;
  evidence_class: LegacyEvidenceClass;
  run_class: LegacyRunClass;
}

export interface PaperFeeConfig {
  commission_rate: string;
  minimum_commission: string;
  stamp_duty_rate: string;
  transfer_fee_rate: string;
}

export interface DataImportRequest {
  provider: "fixture" | "akshare";
  instrument_id: string;
  frequency: "1d";
  start: string;
  end: string;
  adjustment: "none" | "qfq" | "hfq";
}

export interface DatasetSummary {
  dataset_id: string;
  name: string;
  asset_class: "equity" | "futures";
  frequency: string;
  snapshot_count: number;
  latest_snapshot_id: string | null;
  latest_provider_id: string | null;
  latest_row_count: number | null;
  latest_min_event_time: string | null;
  latest_max_event_time: string | null;
}

export interface QualityIssue {
  code: string;
  severity: "WARNING" | "ERROR";
  count: number;
  samples: string[];
}

export interface SnapshotSummary {
  snapshot_id: string;
  dataset_id: string;
  status: "PUBLISHED" | "REJECTED";
  row_count: number;
  provider_id: string;
  created_at: string;
  min_event_time: string;
  max_event_time: string;
  quality_issues: QualityIssue[];
}

export interface BarPreview {
  instrument_id: string;
  event_time: string;
  available_time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

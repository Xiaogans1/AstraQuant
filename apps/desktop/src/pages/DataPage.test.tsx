import { render, screen } from "@testing-library/react";

import type {
  BarPreview,
  DatasetSummary,
  SnapshotSummary,
} from "../api/data-contracts";
import { DataPage } from "./DataPage";

const dataset: DatasetSummary = {
  dataset_id: "cn-equity-600000-sse-1d-none",
  name: "600000.SSE 日线",
  asset_class: "equity",
  frequency: "1d",
  snapshot_count: 1,
  latest_snapshot_id: "snapshot-1",
  latest_provider_id: "eastmoney",
  latest_row_count: 5,
  latest_min_event_time: "2026-07-20T07:00:00Z",
  latest_max_event_time: "2026-07-24T07:00:00Z",
};

const snapshot: SnapshotSummary = {
  snapshot_id: "snapshot-1",
  dataset_id: dataset.dataset_id,
  status: "PUBLISHED",
  row_count: 5,
  provider_id: "eastmoney",
  created_at: "2026-07-28T08:00:00Z",
  min_event_time: "2026-07-20T07:00:00Z",
  max_event_time: "2026-07-24T07:00:00Z",
  quality_issues: [],
};

const bars: BarPreview[] = [
  {
    instrument_id: "600000.SSE",
    event_time: "2026-07-24T07:00:00Z",
    available_time: "2026-07-24T07:01:00Z",
    open: "10.30",
    high: "10.60",
    low: "10.20",
    close: "10.40",
    volume: "1400",
  },
];

test("removes the sample importer and honestly reports an empty real catalog", () => {
  render(
    <DataPage
      datasets={[{ ...dataset, latest_provider_id: "fixture" }]}
      snapshots={[]}
      bars={[]}
      selectedDatasetId={null}
      loading={false}
      stale={false}
      onSelectDataset={vi.fn()}
    />,
  );

  expect(screen.queryByText("导入本地样例")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "导入示例数据" })).not.toBeInTheDocument();
  expect(screen.queryByText("600000.SSE 日线")).not.toBeInTheDocument();
  expect(screen.getByText("尚无真实历史数据")).toBeVisible();
  expect(screen.getByText("数据只保存在本机")).toBeInTheDocument();
  expect(screen.getByText("不包含账户或下单连接")).toBeInTheDocument();
});

test("shows snapshot quality and a compact bar preview", () => {
  render(
    <DataPage
      datasets={[dataset]}
      snapshots={[snapshot]}
      bars={bars}
      selectedDatasetId={dataset.dataset_id}
      loading={false}
      stale={false}
      onSelectDataset={vi.fn()}
    />,
  );

  expect(screen.getByText("质量检查通过")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "收盘" })).toBeVisible();
  expect(screen.getByText("10.40")).toBeVisible();
  expect(screen.getByRole("button", { name: "作为特征输入" })).toBeEnabled();
});

test("conveys rejected quality by icon and text and blocks feature input", () => {
  const rejected: SnapshotSummary = {
    ...snapshot,
    status: "REJECTED",
    quality_issues: [
      {
        code: "MISSING_SESSION",
        severity: "WARNING",
        count: 2,
        samples: ["2026-07-21", "2026-07-22"],
      },
      {
        code: "AVAILABLE_AFTER_FETCH",
        severity: "ERROR",
        count: 1,
        samples: ["600000.SSE@2026-07-24"],
      },
    ],
  };

  render(
    <DataPage
      datasets={[dataset]}
      snapshots={[rejected]}
      bars={[]}
      selectedDatasetId={dataset.dataset_id}
      loading={false}
      stale={false}
      onSelectDataset={vi.fn()}
    />,
  );

  expect(screen.getByText("△ 警告")).toBeVisible();
  expect(screen.getByText("× 错误")).toBeVisible();
  expect(screen.getByRole("button", { name: "作为特征输入" })).toBeDisabled();
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ApiClient } from "../api/client";
import { StrategyLabPage } from "./StrategyLabPage";

vi.mock("../components/ProfessionalMarketChart", () => ({
  ProfessionalMarketChart: ({ bars, signals }: { bars: unknown[]; signals: unknown[] }) => (
    <div data-testid="replay-chart">
      chart {bars.length} bars {signals.length} signals
    </div>
  ),
}));

const dataset = {
  dataset_id: "cn-equity-159516-szse-1m-none",
  instrument_id: "159516.SZSE",
  bar_count: 5000,
  start: "2026-07-09T01:30:00Z",
  end: "2026-08-07T07:00:00Z",
};

const model = {
  model_id: "lgbm-minute-001",
  strategy_id: "microstructure-lgbm",
  strategy_version: "lgbm-v1",
  feature_version: "minute-v1",
  artifact_path: "models/lgbm-minute-v1.txt",
  metrics_json: "{}",
  params_json: '{"buy_threshold": 0.5, "sell_threshold": 0.35}',
  status: "APPROVED",
  created_at: "2026-08-07T00:00:00Z",
  updated_at: "2026-08-07T00:00:00Z",
  approved_at: "2026-08-07T00:00:00Z",
};

function renderLab(client: ApiClient) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <StrategyLabPage client={client} />
    </QueryClientProvider>,
  );
}

test("strategy lab lists datasets and approved models", async () => {
  const client = {
    listResearchDatasets: vi.fn().mockResolvedValue([dataset]),
    listPaperModels: vi.fn().mockResolvedValue([model]),
    runResearchReplay: vi.fn(),
  } as unknown as ApiClient;
  renderLab(client);
  expect(await screen.findByRole("heading", { name: "策略实验室" })).toBeVisible();
  await screen.findByText(/159516.SZSE · 5000 根/);
  expect(screen.getByText(/lgbm-minute-001 · lgbm-v1/)).toBeVisible();
  expect(screen.getByRole("button", { name: "运行历史回放" })).toBeDisabled();
});

test("running replay submits dataset, model and window", async () => {
  const runResearchReplay = vi.fn().mockResolvedValue({
    dataset_id: "cn-equity-159516-szse-1m-none",
    model_id: "lgbm-minute-001",
    instrument_id: "159516.SZSE",
    start: "2026-07-09T01:30:00Z",
    end: "2026-08-07T07:00:00Z",
    bars_count: 5000,
    initial_cash: "100000",
    final_cash: "113616",
    realized_pnl: "15915.24",
    net_return_percent: 13.616,
    buys: 43,
    sells: 43,
    win_rate: 0.6279,
    trades: [
      {
        index: 35,
        timestamp: "2026-07-09T02:05:00Z",
        side: "BUY",
        price: "0.71",
        quantity: 100,
        pnl: "0",
      },
    ],
    bars: [],
    equity_points: [],
  });
  const client = {
    listResearchDatasets: vi.fn().mockResolvedValue([dataset]),
    listPaperModels: vi.fn().mockResolvedValue([model]),
    runResearchReplay,
  } as unknown as ApiClient;
  renderLab(client);
  const user = userEvent.setup();

  await screen.findByText(/159516.SZSE · 5000 根/);
  await user.selectOptions(
    screen.getByRole("combobox", { name: "数据集（已录制真实分钟线）" }),
    "cn-equity-159516-szse-1m-none",
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "模型（仅已批准）" }),
    "lgbm-minute-001",
  );
  await user.click(screen.getByRole("button", { name: "运行历史回放" }));

  expect(runResearchReplay).toHaveBeenCalledWith({
    dataset_id: "cn-equity-159516-szse-1m-none",
    model_id: "lgbm-minute-001",
    start_date: null,
    end_date: null,
    initial_cash: "100000",
  });
  expect(await screen.findByText(/\+13.62%/)).toBeVisible();
  expect(screen.getByText(/43 \/ 43/)).toBeVisible();
  expect(screen.getByText(/买入 100 份 @ 0.71/)).toBeVisible();
});

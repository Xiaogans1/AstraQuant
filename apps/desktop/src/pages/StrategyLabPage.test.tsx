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

vi.mock("../components/InstrumentSearchPicker", () => ({
  InstrumentSearchPicker: ({ onChange }: { onChange: (value: { instrument_id: string; name: string } | null) => void }) => (
    <button
      type="button"
      data-testid="pick-instrument"
      onClick={() => onChange({ instrument_id: "159516.SZSE", name: "半导体设备ETF" })}
    >
      pick-instrument
    </button>
  ),
}));

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

const result = {
  instrument_id: "159516.SZSE",
  model_id: "lgbm-minute-001",
  model_status: "APPROVED",
  start: "2026-07-09T01:30:00Z",
  end: "2026-08-07T07:00:00Z",
  bars_count: 5000,
  initial_cash: "100000",
  initial_equity: "100000",
  final_cash: "113616",
  realized_pnl: "15915.24",
  net_return_percent: 13.616,
  buy_hold_return_percent: 4.5,
  excess_return_percent: 9.116,
  max_drawdown_percent: 3.2,
  sharpe: 1.8,
  profit_factor: 1.6,
  buys: 43,
  sells: 43,
  win_rate: 0.6279,
  position_remaining: 0,
  trades: [
    {
      index: 35,
      timestamp: "2026-07-10T02:05:00Z",
      side: "BUY",
      price: "0.71",
      quantity: 100,
      pnl: "0",
      proba: 0.61,
    },
    {
      index: 120,
      timestamp: "2026-07-10T04:30:00Z",
      side: "SELL",
      price: "0.75",
      quantity: 100,
      pnl: "3.56",
      proba: 0.22,
    },
  ],
  bars: [],
  equity_points: [],
  position_value_points: [],
  buy_hold_equity_points: [],
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

function baseClient() {
  return {
    listResearchDatasets: vi.fn().mockResolvedValue([]),
    listPaperModels: vi.fn().mockResolvedValue([model]),
    runResearchReplay: vi.fn(),
    listResearchExperiments: vi.fn().mockResolvedValue([]),
    listPaperAccounts: vi.fn().mockResolvedValue([]),
    listDailySummary: vi.fn().mockResolvedValue([]),
    listStrategyRunsOnDate: vi.fn().mockResolvedValue([]),
    listPaperPositions: vi.fn().mockResolvedValue([]),
    searchInstruments: vi.fn(),
    getMarketHome: vi.fn().mockResolvedValue({
      connection: { state: "LIVE" },
      watchlist: [],
      selected_instrument: null,
    }),
  } as unknown as ApiClient;
}

test("strategy lab loads approved models and disables batch run without picks", async () => {
  const client = baseClient();
  renderLab(client);
  expect(await screen.findByRole("heading", { name: "策略实验室" })).toBeVisible();
  await screen.findByText(/lgbm-minute-001 · lgbm-v1/);
  expect(screen.getByRole("button", { name: /批量运行 0 只/ })).toBeDisabled();
});

test("strategy lab presets the home watchlist instruments", async () => {
  const client = baseClient();
  client.getMarketHome = vi.fn().mockResolvedValue({
    connection: { state: "LIVE" },
    watchlist: [
      { instrument_id: "159516.SZSE", name: "半导体设备ETF" },
      { instrument_id: "513310.SSE", name: "纳指ETF" },
    ],
    selected_instrument: "159516.SZSE",
  });
  renderLab(client);

  await screen.findByText(/半导体设备ETF/);
  expect(screen.getByText(/纳指ETF/)).toBeVisible();
  expect(screen.getByRole("button", { name: "批量运行 2 只" })).toBeVisible();
});

test("replay with fully-invested opening sells renders without crashing", async () => {
  const openingSellResult = {
    ...result,
    trades: [
      {
        index: 60,
        timestamp: "2026-07-10T03:30:00Z",
        side: "SELL",
        price: "0.72",
        quantity: 1000,
        pnl: "18.5",
        proba: 0.2,
      },
    ],
  };
  const runResearchReplay = vi.fn().mockResolvedValue([openingSellResult]);
  const client = baseClient();
  client.runResearchReplay = runResearchReplay;
  renderLab(client);
  const user = userEvent.setup();

  await screen.findByText(/lgbm-minute-001 · lgbm-v1/);
  await user.click(screen.getByTestId("pick-instrument"));
  await user.selectOptions(
    screen.getByRole("combobox", { name: "模型" }),
    "lgbm-minute-001",
  );
  await user.click(screen.getByRole("button", { name: "批量运行 1 只" }));

  expect(await screen.findByText(/期初持仓/)).toBeVisible();
  expect(screen.getByText(/\+18.5/)).toBeVisible();
});

test("running batch replay submits instruments, model and window", async () => {  const runResearchReplay = vi.fn().mockResolvedValue([result]);
  const client = baseClient();
  client.runResearchReplay = runResearchReplay;
  renderLab(client);
  const user = userEvent.setup();

  await screen.findByText(/lgbm-minute-001 · lgbm-v1/);
  await user.click(screen.getByTestId("pick-instrument"));
  await user.selectOptions(
    screen.getByRole("combobox", { name: "模型" }),
    "lgbm-minute-001",
  );
  await user.click(screen.getByRole("button", { name: "批量运行 1 只" }));

  expect(runResearchReplay).toHaveBeenCalledWith({
    instruments: [
      {
        instrument_id: "159516.SZSE",
        start_date: null,
        end_date: null,
      },
    ],
    model_id: "lgbm-minute-001",
    initial_cash: "100000",
    fully_invested: true,
  });
  expect((await screen.findAllByText(/\+13.62%/)).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/\+4.50%/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/\+9.12%/).length).toBeGreaterThan(0);
  expect(screen.getByText(/43 \/ 43/)).toBeVisible();
  expect(screen.getByText(/0.7100/)).toBeVisible();
  expect(screen.getByText(/\+3.56/)).toBeVisible();
  expect(screen.getByText(/\+5.01%/)).toBeVisible();
});

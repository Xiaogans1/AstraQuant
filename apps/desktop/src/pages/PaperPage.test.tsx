import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ApiClient } from "../api/client";
import type {
  PaperAccountDetail,
  PaperAccountSummary,
} from "../api/paper-contracts";
import { PaperPage } from "./PaperPage";

const summary: PaperAccountSummary = {
  account_id: "account-1",
  name: "主模拟账户",
  mode: "PAPER",
  initial_cash: "100000",
  cash: "99279.99",
  created_at: "2026-08-06T06:30:00Z",
  updated_at: "2026-08-06T06:31:00Z",
  initial_equity: "100000",
  total_equity: "100240.50",
  total_pnl: "240.50",
};

const detail: PaperAccountDetail = {
  account: summary,
  positions: [
    {
      instrument_id: "159516.SZSE",
      name: "半导体设备ETF",
      quantity: 1000,
      available_quantity: 800,
      average_cost: "0.6800",
      last_price: "0.7140",
      market_value: "714.00",
      unrealized_pnl: "34.00",
      unrealized_pnl_percent: "5.0000",
      marked_at: "2026-08-06T06:31:00Z",
    },
  ],
  latest_equity: {
    snapshot_id: "snapshot-1",
    cash: "99279.99",
    market_value: "960.51",
    total_equity: "100240.50",
    initial_equity: "100000",
    total_pnl: "240.50",
    total_pnl_percent: "0.2405",
    as_of: "2026-08-06T06:31:00Z",
  },
};

function renderPage(client: ApiClient) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PaperPage client={client} />
    </QueryClientProvider>,
  );
}

test("empty workspace guides the user to create a local paper account", async () => {
  const client = {
    listPaperAccounts: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;

  renderPage(client);

  expect(
    await screen.findByRole("heading", { name: "建立第一本模拟账本" }),
  ).toBeVisible();
  expect(screen.getByText(/不会向券商发送委托/)).toBeVisible();
  expect(screen.getByRole("button", { name: "创建模拟账户" })).toBeEnabled();
});

test("account workspace shows real portfolio metrics and holdings", async () => {
  const client = {
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
  } as unknown as ApiClient;

  renderPage(client);

  expect(await screen.findByText("100,240.50")).toBeVisible();
  expect(screen.getByText("+240.50")).toBeVisible();
  expect(screen.getByText("半导体设备ETF")).toBeVisible();
  expect(screen.getByText("+5.00%")).toBeVisible();
  expect(screen.getByText("真实行情盯市")).toBeVisible();
});

test("creating an account sends the user-entered cash baseline", async () => {
  const createPaperAccount = vi.fn().mockResolvedValue(detail);
  const client = {
    listPaperAccounts: vi.fn().mockResolvedValue([]),
    createPaperAccount,
  } as unknown as ApiClient;
  renderPage(client);
  const user = userEvent.setup();

  await user.clear(await screen.findByLabelText("账户名称"));
  await user.type(screen.getByLabelText("账户名称"), "ETF 研究账户");
  await user.clear(screen.getByLabelText("初始现金"));
  await user.type(screen.getByLabelText("初始现金"), "200000");
  await user.click(screen.getByRole("button", { name: "创建模拟账户" }));

  expect(createPaperAccount).toHaveBeenCalledWith({
    name: "ETF 研究账户",
    mode: "PAPER",
    initial_cash: "200000",
  });
});

test("strategy console runs baseline in advisory mode and renders the audit result", async () => {
  const runPaperStrategy = vi.fn().mockResolvedValue({
    outcome: "HOLD",
    proposed_side: null,
    proposed_quantity: 100,
    risk_reason: null,
    decision_id: "decision-audit-1",
    advisory_checks: ["MARKET_LIVE", "FEATURES_WARMING_UP"],
    signal: {
      signal_id: "signal-audit-1",
      action: "HOLD",
      state: "WARMING_UP",
      reference_price: null,
      confidence: "0",
      strategy_id: "intraday-momentum-volume",
      strategy_version: "baseline-v1",
      feature_version: "realtime-v1",
      reason_codes: ["INSUFFICIENT_COMPLETED_BARS"],
      event_time: "2026-08-06T06:31:00Z",
      decision_time: "2026-08-06T06:31:00Z",
      expires_at: "2026-08-06T06:32:00Z",
    },
    order: null,
    fill: null,
  });
  const client = {
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    runPaperStrategy,
  } as unknown as ApiClient;
  renderPage(client);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "运行 baseline-v1" }));

  expect(runPaperStrategy).toHaveBeenCalledWith("account-1", {
    instrument_id: "159516.SZSE",
    quantity: 100,
    auto_execute: false,
    max_position_percent: "20",
  });
  expect(await screen.findByText("HOLD · WARMING_UP")).toBeVisible();
  expect(screen.getByText("INSUFFICIENT_COMPLETED_BARS")).toBeVisible();
  expect(screen.getByText("decision-audit-1")).toBeVisible();
});
